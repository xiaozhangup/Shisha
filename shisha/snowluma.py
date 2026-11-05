from __future__ import annotations

import html
import logging
import re
import time

import aiohttp

from .models import GroupMessage

log = logging.getLogger("shisha")


class SnowLumaError(RuntimeError):
    pass


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def parse_cq(message: str) -> list[dict]:
    segments = []
    position = 0
    for match in re.finditer(r"\[CQ:([^,\]]+)((?:,[^\]]*)?)\]", message):
        if match.start() > position:
            segments.append(
                {
                    "type": "text",
                    "data": {"text": html.unescape(message[position : match.start()])},
                }
            )
        data = {}
        for item in match.group(2).split(","):
            if "=" in item:
                key, value = item.split("=", 1)
                data[key] = html.unescape(value)
        segments.append({"type": match.group(1), "data": data})
        position = match.end()
    if position < len(message):
        segments.append(
            {"type": "text", "data": {"text": html.unescape(message[position:])}}
        )
    return segments


class SnowLumaClient:
    def __init__(self, session: aiohttp.ClientSession, config: dict):
        self.session = session
        self.config = config

    async def action(self, name: str, params: dict) -> object:
        url = f"{self.config['http_url'].rstrip('/')}/{name}"
        async with self.session.post(
            url,
            json=params,
            headers=authorization(self.config["http_token"]),
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        if payload.get("status") != "ok" or payload.get("retcode") != 0:
            raise SnowLumaError(
                f"{name} 失败: {payload.get('wording') or payload.get('retcode')}"
            )
        return payload.get("data")

    async def parse_message(self, event: dict) -> GroupMessage:
        text, at_all = await self._render(event.get("message", ""), set(), 0)
        return GroupMessage(
            group_id=int(event["group_id"]),
            user_id=int(event["user_id"]),
            message_id=int(event["message_id"]),
            text=text,
            at_all=at_all,
            received_at=time.monotonic(),
            group_name=str(event.get("group_name") or ""),
        )

    async def _render(
        self, value: str | list, seen: set[str], depth: int
    ) -> tuple[str, bool]:
        segments = parse_cq(value) if isinstance(value, str) else value
        parts, at_all = [], False
        for segment in segments:
            kind, data = segment.get("type"), segment.get("data", {})
            if kind == "text":
                parts.append(str(data.get("text", "")))
            elif kind == "at":
                target = str(data.get("qq", ""))
                if target == "all":
                    at_all = True
                    parts.append("@全体成员")
                else:
                    parts.append(f"@{target}")
            elif kind == "file":
                parts.append(f"[文件: {data.get('name') or data.get('file', '')}]")
            elif kind == "image":
                parts.append(str(data.get("url") or "[图片]"))
            elif kind == "markdown":
                parts.append(str(data.get("content", "")))
            elif kind == "forward" and depth < 5:
                forward_id = str(data.get("id") or "")
                if not forward_id or forward_id in seen:
                    continue
                seen.add(forward_id)
                try:
                    result = await self.action("get_forward_msg", {"id": forward_id})
                    nodes = []
                    for item in result["messages"]:
                        text, nested_at_all = await self._render(
                            item.get("message", ""), seen, depth + 1
                        )
                        if text:
                            nodes.append(text)
                        at_all = at_all or nested_at_all
                    parts.append("\n".join(nodes))
                except (TimeoutError, aiohttp.ClientError, SnowLumaError) as exc:
                    log.warning("读取合并转发失败: %s", type(exc).__name__)
                    parts.append("[合并转发读取失败]")
        return "".join(parts), at_all

    async def send(self, group_id: int, text: str, reply_to: int | None = None) -> None:
        segments = []
        if reply_to is not None:
            segments.append({"type": "reply", "data": {"id": str(reply_to)}})
        segments.append({"type": "text", "data": {"text": text}})
        await self.action("send_group_msg", {"group_id": group_id, "message": segments})

    async def mark(self, message: GroupMessage) -> None:
        await self.action(
            "set_group_reaction",
            {
                "group_id": message.group_id,
                "message_id": message.message_id,
                "code": "10024",
                "is_set": True,
            },
        )

    async def get_message(self, message_id: int) -> GroupMessage:
        event = await self.action("get_msg", {"message_id": message_id})
        return await self.parse_message(event)
