from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict, deque
from copy import deepcopy

import aiohttp

from .analyzer import Analyzer
from .config import ConfigStore
from .models import GroupMessage, Task
from .snowluma import SnowLumaClient, authorization
from .storage import History
from .todoist import TodoistClient

log = logging.getLogger("shisha")


class Worker:
    def __init__(
        self, session: aiohttp.ClientSession, config: ConfigStore, history: History
    ):
        self.session, self.config, self.history = session, config, history
        self.connection: asyncio.Task | None = None
        self.timers: dict[tuple[int, int], asyncio.Task] = {}
        self.jobs: set[asyncio.Task] = set()
        self.buffers: dict[tuple[int, int], deque[GroupMessage]] = {}
        self.recent: dict[int, OrderedDict[int, GroupMessage]] = {}
        self.inflight: list[str] = []
        self.connected = False
        self.last_error = ""

    def apply(self) -> None:
        if self.connection:
            self.connection.cancel()
        self.connected = False
        self.last_error = ""
        if self.config.ready():
            self.connection = asyncio.create_task(
                self._listen(deepcopy(self.config.value))
            )
        else:
            self.connection = None

    def status(self) -> dict:
        return {
            "configured": self.config.ready(),
            "connected": self.connected,
            "error": self.last_error,
        }

    async def _listen(self, config: dict) -> None:
        connection = config["snowluma"]
        while True:
            try:
                async with self.session.ws_connect(
                    connection["ws_url"],
                    headers=authorization(connection["ws_token"]),
                    heartbeat=30,
                ) as ws:
                    self.connected = True
                    self.last_error = ""
                    log.info("SnowLuma WebSocket 已连接")
                    async for message in ws:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            try:
                                event = message.json()
                                await self._on_event(event, config)
                            except (ValueError, TypeError, KeyError) as exc:
                                log.warning("忽略格式不正确的事件: %s", exc)
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            raise ws.exception() or ConnectionError("WebSocket 错误")
                self.last_error = "连接已断开，正在重连"
            except (TimeoutError, aiohttp.ClientError, OSError, ConnectionError) as exc:
                self.last_error = f"连接失败: {type(exc).__name__}"
                log.warning("SnowLuma WebSocket %s", self.last_error)
            finally:
                self.connected = False
            await asyncio.sleep(5)

    async def _on_event(self, event: dict, config: dict) -> None:
        if event.get("post_type") == "message" and event.get("message_type") == "group":
            if str(event.get("group_id")) not in config["filter"]["groups"]:
                return
            msg = await SnowLumaClient(self.session, config["snowluma"]).parse_message(
                event
            )
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
            if msg.at_all or any(
                word in msg.text for word in config["filter"]["keywords"]
            ):
                previous = self.timers.pop(key, None)
                if previous:
                    previous.cancel()
                self.timers[key] = asyncio.create_task(self._debounce(key, msg, config))
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
            if any(
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
        self, key: tuple[int, int], trigger: GroupMessage, config: dict
    ) -> None:
        try:
            await asyncio.sleep(config["filter"]["debounce_seconds"])
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
            text = "\n".join(
                message.text for message in messages[start : end + 1]
            ).strip()
            if text:
                self._spawn(self._process(trigger, text, config, manual=False))
        finally:
            if self.timers.get(key) is asyncio.current_task():
                del self.timers[key]

    async def _manual(self, event: dict, config: dict) -> None:
        client = SnowLumaClient(self.session, config["snowluma"])
        message_id, group_id = int(event["message_id"]), int(event["group_id"])
        message = self.recent.get(group_id, {}).get(message_id)
        if message is None:
            message = await client.get_message(message_id)
        if message.group_id == group_id and message.text.strip():
            await self._process(message, message.text, config, manual=True)

    async def _notify(
        self, client: SnowLumaClient, config: dict, message: GroupMessage, text: str
    ) -> None:
        target = int(config["filter"]["notification_group"])
        if message.group_id == target:
            await client.send(target, text, reply_to=message.message_id)
        else:
            await client.send(
                target,
                f"{text}\n\n来自: {message.group_name or message.group_id} ({message.group_id})\n原文:\n{message.text[:69]}",
            )

    async def _process(
        self, message: GroupMessage, text: str, config: dict, manual: bool
    ) -> None:
        client = SnowLumaClient(self.session, config["snowluma"])
        if message.group_id == int(config["filter"]["notification_group"]):
            try:
                await client.mark(message)
            except (TimeoutError, aiohttp.ClientError, RuntimeError) as exc:
                log.warning("无法添加表情回应: %s", exc)
        if not manual and self.history.similarity(text, self.inflight) > 0.8:
            await self._notify(client, config, message, "与历史消息高度相似，已忽略")
            return
        self.inflight.append(text)
        try:
            try:
                tasks = await Analyzer(self.session, config["ai"]).extract(text)
            except (TimeoutError, aiohttp.ClientError, RuntimeError) as exc:
                log.warning("AI 提取失败: %s", exc)
                await self._notify(
                    client, config, message, "摘要提取失败，请检查 AI 配置和日志"
                )
                return
            self.history.remember(text)
        finally:
            self.inflight.remove(text)
        if not tasks:
            await self._notify(client, config, message, "消息中未提取到任务")
            return
        todoist = TodoistClient(self.session, config["todoist"])
        for task in tasks:
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


def format_summary(task: Task, message_id: int, success: bool) -> str:
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
    if not success:
        parts.append("#无法插入Todoist")
    parts.append(f"#任务 #{message_id}")
    return "\n\n".join(parts)
