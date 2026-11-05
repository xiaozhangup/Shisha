from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import replace

import aiohttp
import psutil

from .analyzer import AnalysisError, Analyzer
from .config import ConfigStore, notification_target, todoist_group
from .media import MAX_MODEL_TOTAL, ImageError, ImageStore, PreparedImage
from .models import GroupMessage, Task
from .snowluma import SnowLumaClient
from .storage import History
from .todoist import TodoistClient
from .transport import TransportError, WebSocketTransport, authorization

log = logging.getLogger("shisha")


def connection_key(config: dict) -> tuple[str, str, str]:
    mode = config["mode"]
    return mode, config[f"{mode}_url"], config[f"{mode}_token"]


class Worker:
    def __init__(
        self, session: aiohttp.ClientSession, config: ConfigStore, history: History
    ):
        self.session, self.config, self.history = session, config, history
        self.images = ImageStore(session, history, self._refresh_image_url)
        self.process = psutil.Process()
        self.connection: asyncio.Task | None = None
        self.apply_lock = asyncio.Lock()
        self.connection_config: dict | None = None
        self.transport: WebSocketTransport | None = None
        self.sse_cursor: str | None = None
        self.timers: dict[tuple[int, int], asyncio.Task] = {}
        self.jobs: set[asyncio.Task] = set()
        self.buffers: dict[tuple[int, int], deque[GroupMessage]] = {}
        self.recent: dict[int, OrderedDict[int, GroupMessage]] = {}
        self.inflight: list[tuple[str, str]] = []
        self.connected = False
        self.last_error = ""

    async def apply(self) -> None:
        async with self.apply_lock:
            settings = deepcopy(self.config.value["snowluma"])
            if (
                self.connection
                and not self.connection.done()
                and connection_key(settings) == connection_key(self.connection_config)
            ):
                return
            if self.connection:
                self.connection.cancel()
                await asyncio.gather(self.connection, return_exceptions=True)
            self.connected = False
            self.last_error = ""
            self.sse_cursor = None
            self.connection_config = settings
            if self.config.path.exists():
                self.connection = asyncio.create_task(self._listen(settings))
            else:
                self.connection = None

    def status(self) -> dict:
        return {
            "configured": self.config.ready(),
            "connected": self.connected,
            "listening": bool(self.config.value["filter"]["groups"]),
            "group_count": len(self.config.value["filter"]["groups"]),
            "message_count": self.history.message_count(),
            "memory_bytes": self.process.memory_info().rss,
            "error": self.last_error,
            "mode": self.config.value["snowluma"]["mode"],
        }

    def client(self, config: dict) -> SnowLumaClient:
        transport = self.transport
        if transport and connection_key(config) != connection_key(transport.config):
            transport = None
        return SnowLumaClient(self.session, config, transport)

    async def _refresh_image_url(self, file: str) -> str:
        info = await self.client(self.config.value["snowluma"]).action(
            "get_image", {"file": file}
        )
        return str(info.get("url") or info.get("file") or "")

    async def _listen(self, connection: dict) -> None:
        while True:
            try:
                if connection["mode"] == "ws":
                    await self._listen_ws(connection)
                else:
                    await self._listen_sse(connection)
                self.last_error = "连接已断开，正在重连"
            except (TimeoutError, aiohttp.ClientError, OSError, TransportError) as exc:
                self.last_error = (
                    str(exc)
                    if isinstance(exc, TransportError)
                    else f"连接失败: {type(exc).__name__}"
                )
                log.warning("SnowLuma %s", self.last_error)
            finally:
                self.connected = False
                self.transport = None
            await asyncio.sleep(5)

    async def _listen_ws(self, connection: dict) -> None:
        async with WebSocketTransport(self.session, connection) as transport:
            self.transport = transport
            self.connected = True
            self.last_error = ""
            log.info("SnowLuma WebSocket 已连接")
            while (event := await transport.events.get()) is not None:
                await self._dispatch(event, connection)

    async def _listen_sse(self, connection: dict) -> None:
        headers = {
            "Accept": "text/event-stream",
            **authorization(connection["http_token"]),
        }
        if self.sse_cursor:
            headers["Last-Event-ID"] = self.sse_cursor
        url = f"{connection['http_url'].rstrip('/')}/_events"
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=45)
        async with self.session.get(url, headers=headers, timeout=timeout) as response:
            if response.status == 409 and self.sse_cursor:
                self.sse_cursor = None
                raise TransportError("HTTP 事件记录已过期，正在重新连接")
            if response.status == 404:
                raise TransportError("SnowLuma 的 HTTP 服务未启用 SSE")
            response.raise_for_status()
            if response.content_type != "text/event-stream":
                raise TransportError("SnowLuma HTTP 事件流格式不正确")
            self.connected = True
            self.last_error = ""
            log.info("SnowLuma HTTP 事件流已连接")
            data_lines, event_id = [], None
            async for raw in response.content:
                line = raw.decode("utf-8").rstrip("\r\n")
                if not line:
                    if data_lines:
                        try:
                            event = json.loads("\n".join(data_lines))
                            await self._dispatch(event, connection)
                            if event_id:
                                self.sse_cursor = event_id
                        except (ValueError, TypeError) as exc:
                            log.warning("忽略格式不正确的事件: %s", exc)
                    data_lines, event_id = [], None
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip(" "))
                elif line.startswith("id:"):
                    event_id = line[3:].lstrip(" ")

    async def _dispatch(self, event: dict, connection: dict) -> None:
        try:
            if not isinstance(event, dict):
                raise TypeError("事件必须是对象")
            await self._on_event(event, connection)
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("忽略格式不正确的事件: %s", exc)

    async def _on_event(self, event: dict, connection: dict) -> None:
        config = deepcopy(self.config.value)
        if event.get("post_type") == "message" and event.get("message_type") == "group":
            if str(event.get("group_id")) not in config["filter"]["groups"]:
                return
            msg = await self.client(connection).parse_message(event)
            if not self.history.save_message(msg):
                return
            for position in range(len(msg.images)):
                self.images.start(msg.group_id, msg.message_id, position)
            if msg.text.lstrip().startswith("/"):
                return
            group = self.recent.setdefault(msg.group_id, OrderedDict())
            group[msg.message_id] = msg
            while len(group) > 32:
                group.popitem(last=False)
            now = time.monotonic()
            for key, buffer in list(self.buffers.items()):
                while buffer and now - buffer[0].received_at > 300:
                    buffer.popleft()
                if not buffer:
                    del self.buffers[key]
            key = (msg.group_id, msg.user_id)
            self.buffers.setdefault(key, deque()).append(msg)
            if self.config.ready(msg.group_id) and (
                msg.at_all
                or "@全体成员" in msg.text
                or any(word in msg.text for word in config["filter"]["keywords"])
            ):
                previous = self.timers.pop(key, None)
                if previous:
                    previous.cancel()
                self.timers[key] = asyncio.create_task(
                    self._debounce(key, msg, config["filter"]["debounce_seconds"])
                )
        elif (
            event.get("post_type") == "notice"
            and event.get("notice_type") == "group_msg_emoji_like"
        ):
            if (
                str(event.get("group_id")) != notification_target(config)
                or str(event.get("group_id")) not in config["filter"]["groups"]
                or event.get("sub_type") != "add"
            ):
                return
            if event.get("user_id") == event.get("self_id"):
                return
            if self.config.ready(event["group_id"]) and any(
                str(like.get("emoji_id")) == "424" for like in event.get("likes", [])
            ):
                self._spawn(self._manual(event, config))

    def _spawn(self, coroutine) -> None:
        job = asyncio.create_task(coroutine)
        self.jobs.add(job)
        job.add_done_callback(self._job_done)

    def _job_done(self, job: asyncio.Task) -> None:
        self.jobs.discard(job)
        if not job.cancelled() and job.exception():
            log.error("任务处理失败", exc_info=job.exception())

    async def _debounce(
        self, key: tuple[int, int], trigger: GroupMessage, delay: int
    ) -> None:
        try:
            await asyncio.sleep(delay)
            config = deepcopy(self.config.value)
            if str(trigger.group_id) not in config["filter"][
                "groups"
            ] or not self.config.ready(trigger.group_id):
                return
            messages = list(self.buffers.pop(key, ()))
            index = next(
                (
                    i
                    for i, message in enumerate(messages)
                    if message.message_id == trigger.message_id
                ),
                None,
            )
            if index is None:
                return
            start = end = index
            while (
                start > 0
                and messages[start].received_at - messages[start - 1].received_at <= 60
            ):
                start -= 1
            while (
                end + 1 < len(messages)
                and messages[end + 1].received_at - messages[end].received_at <= 60
            ):
                end += 1
            relevant = messages[start : end + 1]
            text = "\n".join(message.text for message in relevant)
            if text.strip():
                self._spawn(
                    self._process(trigger, text, relevant, config, manual=False)
                )
        finally:
            if self.timers.get(key) is asyncio.current_task():
                del self.timers[key]

    async def _manual(self, event: dict, config: dict) -> None:
        client = self.client(config["snowluma"])
        message_id, group_id = int(event["message_id"]), int(event["group_id"])
        message = self.recent.get(group_id, {}).get(message_id)
        if message is None:
            message = await client.get_message(message_id)
        if message.group_id == group_id and message.text.strip():
            self.history.save_message(message, include_existing_images=True)
            for position in range(len(message.images)):
                self.images.start(message.group_id, message.message_id, position)
            await self._process(message, message.text, [message], config, manual=True)

    async def _notify(
        self,
        client: SnowLumaClient,
        config: dict,
        message: GroupMessage,
        text: str,
        images: list[PreparedImage] | None = None,
    ) -> None:
        if not config["filter"]["notify_enabled"]:
            return
        target = int(notification_target(config))
        own_sender = config["notification"]["sender"] == "self"
        sender = client if own_sender else self.client(config["notification"])
        if message.group_id == target:
            await sender.send(
                target,
                text,
                reply_to=message.message_id if own_sender else None,
                images=images,
            )
        else:
            await sender.send(
                target,
                f"{text}\n\n来自: {message.group_name or message.group_id} ({message.group_id})\n原文:\n{message_preview(message)[:69]}",
                images=images,
            )

    async def _process(
        self,
        message: GroupMessage,
        text: str,
        messages: list[GroupMessage],
        config: dict,
        manual: bool,
    ) -> None:
        client = self.client(config["snowluma"])
        if config["filter"]["notify_enabled"] and message.group_id == int(
            notification_target(config)
        ):
            try:
                await client.mark(message)
            except (TimeoutError, aiohttp.ClientError, RuntimeError) as exc:
                log.warning("无法添加表情回应: %s", exc)
        context, image_refs = image_context(messages)
        try:
            images = await asyncio.gather(
                *(self.images.prepare(*image) for image in image_refs)
            )
            if sum(len(image.model_data) for image in images) > MAX_MODEL_TOTAL:
                raise ImageError("一次摘要的图片合计超过 32 MiB")
        except ImageError as exc:
            request_id = self.history.start_ai(message, context, messages, image_refs)
            self.history.finish_ai(request_id, "failed", f"图片读取失败：{exc}")
            log.warning("AI 提取失败: %s", exc)
            await self._notify(client, config, message, f"摘要提取失败：{exc}")
            return

        image_hash = ""
        if images:
            digest = hashlib.sha256()
            for image in images:
                digest.update(hashlib.sha256(image.original).digest())
            image_hash = digest.hexdigest()
        pending = [content for content, value in self.inflight if value == image_hash]
        if not manual and self.history.similarity(context, pending, image_hash) > 0.8:
            await self._notify(client, config, message, "与历史消息高度相似，已忽略")
            return
        self.inflight.append((context, image_hash))
        try:
            request_id = self.history.start_ai(message, context, messages, image_refs)
            try:
                tasks = await Analyzer(self.session, config["ai"]).extract(
                    context,
                    images,
                    with_image_titles=bool(images)
                    and todoist_group(config["todoist"], message.group_id)[
                        "todoist_enabled"
                    ],
                )
            except (TimeoutError, aiohttp.ClientError, RuntimeError) as exc:
                detail = ""
                if images and isinstance(exc, aiohttp.ClientResponseError):
                    detail = f"AI 接口返回 HTTP {exc.status}，请检查模型的图片输入设置"
                elif images and isinstance(exc, AnalysisError):
                    detail = "AI 返回的任务格式或图片信息不正确"
                self.history.finish_ai(
                    request_id, "failed", detail or type(exc).__name__
                )
                log.warning("AI 提取失败: %s", exc)
                await self._notify(
                    client,
                    config,
                    message,
                    f"摘要提取失败：{detail}"
                    if detail
                    else "摘要提取失败，请检查 AI 配置和日志",
                )
                return
            except asyncio.CancelledError:
                self.history.finish_ai(request_id, "interrupted")
                raise
            self.history.remember(context, image_hash)
            result = "\n\n".join(
                format_summary(task, message.message_id, None) for task in tasks
            )
            self.history.finish_ai(request_id, "complete" if tasks else "empty", result)
        finally:
            self.inflight.remove((context, image_hash))
        if not tasks:
            notice = (
                "该消息未包含任务信息，未创建任务"
                if manual
                else "无法解析消息上下文，未能提取到有效任务信息"
            )
            await self._notify(client, config, message, notice)
            return
        image_titles = {
            marker: title
            for task in tasks
            for marker, title in task.image_titles.items()
        }
        todoist = (
            TodoistClient(self.session, config["todoist"])
            if todoist_group(config["todoist"], message.group_id)["todoist_enabled"]
            else None
        )
        for task in tasks:
            success = None
            if todoist:
                try:
                    await todoist.create(
                        task_with_image_titles(task, image_titles),
                        message,
                        replace_image_markers(context, image_titles, in_context=True),
                    )
                    success = True
                except (TimeoutError, aiohttp.ClientError, RuntimeError) as exc:
                    success = False
                    log.warning("Todoist 创建失败: %s", exc)
            summary = format_summary(task, message.message_id, success)
            self.history.save_summary(message.message_id, summary)
            await self._notify(client, config, message, summary, images)
            log.info("已处理任务：%s", task.title)

    async def close(self) -> None:
        pending = list(self.timers.values()) + list(self.jobs)
        if self.connection:
            pending.append(self.connection)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self.images.close()


def image_context(
    messages: list[GroupMessage],
) -> tuple[str, list[tuple[str, int, int, int]]]:
    entries, refs = [], []
    for message in messages:
        parts, offset = [], 0
        for position, image in enumerate(message.images):
            marker = f"【图片{len(refs) + 1}】"
            parts.extend((message.text[offset : image.start], marker))
            refs.append((marker, message.group_id, message.message_id, position))
            offset = image.end
        parts.append(message.text[offset:])
        entries.append("".join(parts))
    return "\n".join(entries), refs


def message_preview(message: GroupMessage) -> str:
    parts, offset = [], 0
    for image in message.images:
        parts.extend((message.text[offset : image.start], "[图片]"))
        offset = image.end
    parts.append(message.text[offset:])
    return "".join(parts)


def replace_image_markers(
    value: str, titles: dict[str, str], in_context: bool = False
) -> str:
    for marker, title in titles.items():
        value = value.replace(marker, f"[图片：{title}]" if in_context else title)
    return value


def task_with_image_titles(task: Task, titles: dict[str, str]) -> Task:
    titles = {**titles, **task.image_titles}

    def convert(value: str) -> str:
        return replace_image_markers(value, titles)

    return replace(
        task,
        title=convert(task.title),
        subject=convert(task.subject),
        attachments=[convert(item) for item in task.attachments],
        related_time=convert(task.related_time),
        earliest_time=convert(task.earliest_time),
    )


def format_summary(task: Task, message_id: int, success: bool | None) -> str:
    parts = [task.title]
    if task.related_time.strip():
        parts.append(f"时间: \n{task.related_time}")
    if task.attachments:
        parts.append(
            "附件: \n"
            + "\n".join(f"{i}. {item}" for i, item in enumerate(task.attachments, 1))
        )
    if task.subject.strip():
        parts.append(task.subject)
    if success is False:
        return "\n\n".join(parts) + f"\n\n#无法插入Todoist\n#任务 #{message_id}"
    return "\n\n".join(parts) + f"\n\n#任务 #{message_id}"
