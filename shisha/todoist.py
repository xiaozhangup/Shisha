from __future__ import annotations

import asyncio

import aiohttp

from .config import todoist_group
from .models import GroupMessage, Task


class TodoistError(RuntimeError):
    pass


class TodoistClient:
    def __init__(self, session: aiohttp.ClientSession, config: dict):
        self.session = session
        self.config = config
        self.base_url = "https://api.todoist.com/api/v1"
        self.headers = {"Authorization": f"Bearer {config['token']}"}

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

    async def catalog(self) -> dict:
        projects, sections = await asyncio.gather(
            self._all("projects"), self._all("sections")
        )
        return {
            "projects": [
                {"id": str(p["id"]), "name": p["name"]}
                for p in projects
                if not p.get("is_archived") and not p.get("is_deleted")
            ],
            "sections": [
                {
                    "id": str(s["id"]),
                    "name": s["name"],
                    "project_id": str(s["project_id"]),
                }
                for s in sections
                if not s.get("is_archived") and not s.get("is_deleted")
            ],
        }

    async def create_project(self, name: str) -> dict:
        return await self._post("projects", {"name": name})

    async def create_section(self, name: str, project_id: str) -> dict:
        return await self._post("sections", {"name": name, "project_id": project_id})

    async def _post(self, path: str, data: dict) -> dict:
        async with self.session.post(
            f"{self.base_url}/{path}",
            json=data,
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            response.raise_for_status()
            return await response.json()

    async def _destination(self, group_id: int) -> tuple[str, str]:
        selected = todoist_group(self.config, group_id)
        if not selected["legacy_section"]:
            return selected["project_id"], selected["section_id"]
        catalog = await self.catalog()
        projects = {p["id"]: p["name"] for p in catalog["projects"]}
        matches = [
            s
            for s in catalog["sections"]
            if f"{projects.get(s['project_id'], '')}.{s['name']}"
            == selected["legacy_section"]
        ]
        if len(matches) != 1:
            raise TodoistError("找不到唯一的 Todoist 项目和板块，请检查设置")
        return matches[0]["project_id"], matches[0]["id"]

    async def create(self, task: Task, message: GroupMessage, raw: str) -> None:
        description = task.subject if task.subject.strip() else ""
        if task.attachments:
            description += "\n\n附件: \n" + "\n".join(
                f"{i}. {item}" for i, item in enumerate(task.attachments, 1)
            )
        if task.related_time.strip():
            description += f"\n\n时间: {task.related_time}"
        description += f"\n\n来自: {message.group_name or message.group_id} ({message.group_id})\n原始消息上下文:\n{raw}"
        data = {"content": task.title, "description": description}
        project_id, section_id = await self._destination(message.group_id)
        if project_id:
            data["project_id"] = project_id
        if section_id:
            data["section_id"] = section_id
        if task.earliest_time.strip():
            data["due_string"] = task.earliest_time
            data["due_lang"] = "en"
        async with self.session.post(
            f"{self.base_url}/tasks",
            json=data,
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            response.raise_for_status()
