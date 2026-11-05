from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict, deque
from copy import deepcopy

import aiohttp

from .analyzer import Analyzer
from .config import ConfigStore
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
        self.connection: asyncio.Task | None = None
        self.apply_lock = asyncio.Lock()
        self.connection_config: dict | None = None
        self.transport: WebSocketTransport | None = None
        self.sse_cursor: str | None = None
        self.timers: dict[tuple[int, int], asyncio.Task] = {}
        self.jobs: set[asyncio.Task] = set()
        self.buffers: dict[tuple[int, int], deque[GroupMessage]] = {}
        self.recent: dict[int, OrderedDict[int, GroupMessage]] = {}
        self.inflight: list[str] = []
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
            "error": self.last_error,
            "mode": self.config.value["snowluma"]["mode"],
        }

    def client(self, config: dict) -> SnowLumaClient:
        transport = self.transport
        if transport and connection_key(config) != connection_key(transport.config):
            transport = None
        return SnowLumaClient(self.session, config, transport)

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
            if self.config.ready() and (
                msg.at_all
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
                str(event.get("group_id")) != config["filter"]["notification_group"]
                or event.get("sub_type") != "add"
            ):
                return
            if event.get("user_id") == event.get("self_id"):
                return
            if self.config.ready() and any(
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
            if (
                str(trigger.group_id) not in config["filter"]["groups"]
                or not self.config.ready()
            ):
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
            text = "\n".join(message.text for message in relevant).strip()
            if text:
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
            await self._process(message, message.text, [message], config, manual=True)

    async def _notify(
        self, client: SnowLumaClient, config: dict, message: GroupMessage, text: str
    ) -> None:
        if not config["filter"]["notify_enabled"]:
            return
        target = int(config["filter"]["notification_group"])
        if message.group_id == target:
            await client.send(target, text, reply_to=message.message_id)
        else:
            await client.send(
                target,
                f"{text}\n\n来自: {message.group_name or message.group_id} ({message.group_id})\n原文:\n{message.text[:69]}",
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
            config["filter"]["notification_group"]
        ):
            try:
                await client.mark(message)
            except (TimeoutError, aiohttp.ClientError, RuntimeError) as exc:
                log.warning("无法添加表情回应: %s", exc)
        if not manual and self.history.similarity(text, self.inflight) > 0.8:
            await self._notify(client, config, message, "与历史消息高度相似，已忽略")
            return
        self.inflight.append(text)
        try:
            request_id = self.history.start_ai(message, text, messages)
            try:
                tasks = await Analyzer(self.session, config["ai"]).extract(text)
            except (TimeoutError, aiohttp.ClientError, RuntimeError) as exc:
                self.history.finish_ai(request_id, "failed", type(exc).__name__)
                log.warning("AI 提取失败: %s", exc)
                await self._notify(
                    client, config, message, "摘要提取失败，请检查 AI 配置和日志"
                )
                return
            except asyncio.CancelledError:
                self.history.finish_ai(request_id, "interrupted")
                raise
            self.history.remember(text)
            result = "\n\n".join(
                format_summary(task, message.message_id, None) for task in tasks
            )
            self.history.finish_ai(request_id, "complete" if tasks else "empty", result)
        finally:
            self.inflight.remove(text)
        if not tasks:
            await self._notify(client, config, message, "消息中未提取到任务")
            return
        todoist = (
            TodoistClient(self.session, config["todoist"])
            if config["todoist"]["enabled"]
            else None
        )
        for task in tasks:
            success = None
            if todoist:
                try:
                    await todoist.create(task, message, text)
                    success = True
                except (TimeoutError, aiohttp.ClientError, RuntimeError) as exc:
                    success = False
                    log.warning("Todoist 创建失败: %s", exc)
            summary = format_summary(task, message.message_id, success)
            self.history.save_summary(message.message_id, summary)
            await self._notify(client, config, message, summary)
            log.info("已处理任务：%s", task.title)

    async def close(self) -> None:
        pending = list(self.timers.values()) + list(self.jobs)
        if self.connection:
            pending.append(self.connection)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


def format_summary(task: Task, message_id: int, success: bool | None) -> str:
    parts = [task.title]
    if task.related_time:
        parts.append(f"时间:\n{task.related_time}")
    if task.attachments:
        parts.append(
            "附件:\n"
            + "\n".join(f"{i}. {item}" for i, item in enumerate(task.attachments, 1))
        )
    if task.subject:
        parts.append(task.subject)
    if success is False:
        parts.append("#无法插入Todoist")
    parts.append(f"#任务 #{message_id}")
    return "\n\n".join(parts)
