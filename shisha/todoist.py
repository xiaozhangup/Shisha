from __future__ import annotations

from datetime import datetime

import aiohttp

from .models import GroupMessage, Task


class TodoistError(RuntimeError):
    pass


class TodoistClient:
    def __init__(self, session: aiohttp.ClientSession, config: dict):
        self.session = session
        self.config = config
        self.base_url = "https://api.todoist.com/api/v1"
        self.headers = {"Authorization": f"Bearer {config['token']}"}
        self._section_id: str | None = None

    async def _all(self, path: str) -> list[dict]:
        items, cursor = [], None
        while True:
            params = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            async with self.session.get(
                f"{self.base_url}/{path}",
                headers=self.headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                response.raise_for_status()
                data = await response.json()
            items.extend(data["results"])
            cursor = data.get("next_cursor")
            if not cursor:
                return items

    async def _section(self) -> str | None:
        section = self.config["section"]
        if not section:
            return None
        if self._section_id is None:
            projects = {p["id"]: p["name"] for p in await self._all("projects")}
            sections = await self._all("sections")
            matches = [
                s["id"]
                for s in sections
                if f"{projects.get(s['project_id'], '')}.{s['name']}" == section
            ]
            if len(matches) != 1:
                raise TodoistError("找不到唯一的 Todoist 项目和板块，请检查设置")
            self._section_id = matches[0]
        return self._section_id

    async def create(self, task: Task, message: GroupMessage, raw: str) -> None:
        description = task.subject
        if task.attachments:
            description += "\n\n附件:\n" + "\n".join(
                f"{i}. {item}" for i, item in enumerate(task.attachments, 1)
            )
        if task.related_time:
            description += f"\n\n时间: {task.related_time}"
        description += f"\n\n来自: {message.group_name or message.group_id} ({message.group_id})\n原始消息上下文:\n{raw}"
        data = {"content": task.title, "description": description.strip()}
        section_id = await self._section()
        if section_id:
            data["section_id"] = section_id
        if task.earliest_time:
            for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d"):
                try:
                    due = datetime.strptime(task.earliest_time, fmt)
                except ValueError:
                    continue
                if fmt.endswith("%H:%M"):
                    data["due_string"] = due.strftime("%Y-%m-%d %H:%M")
                else:
                    data["due_date"] = due.strftime("%Y-%m-%d")
                break
        async with self.session.post(
            f"{self.base_url}/tasks",
            json=data,
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            response.raise_for_status()
