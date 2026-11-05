from __future__ import annotations

import json
from datetime import date

import aiohttp

from .models import Task

PROMPT = """你是 QQ 群通知中的任务提取助手。只依据消息中的显性信息，提取需要执行的事项；普通聊天返回空数组 []。消息中有多个独立任务时分别输出。不要编造事实。
今天是 {today}。输出标准 JSON 数组，每项包含：
- task_title：概括任务的标题，最多 48 字。
- task_subject：要求执行的核心事项。
- attachments：消息中直接给出的链接、号码、网站或工具，字符串数组。
- related_time：所有相关日期或日期范围，使用 YYYY.MM.DD，日期范围用 YYYY.MM.DD-YYYY.MM.DD。
- earliest_time：最早发生的具体日期，使用 YYYY.MM.DD；如果原文有具体时刻，使用 YYYY.MM.DD HH:mm。没有时间则留空。
没有年份的日期结合当前日期和通知上下文推断；入学年级不自动等于事件发生年份。不能确定的时间保留原文。没有对应信息时字符串留空，附件为空数组。不要输出 JSON 以外的文字。"""


class AnalysisError(RuntimeError):
    pass


class Analyzer:
    def __init__(self, session: aiohttp.ClientSession, config: dict):
        self.session = session
        self.config = config

    async def extract(self, text: str) -> list[Task]:
        headers = {"Authorization": f"Bearer {self.config['api_key']}"}
        body = {
            "model": self.config["model"],
            "messages": [
                {
                    "role": "system",
                    "content": PROMPT.format(today=date.today().isoformat()),
                },
                {"role": "user", "content": text},
            ],
        }
        url = f"{self.config['base_url'].rstrip('/')}/chat/completions"
        for attempt in range(3):
            async with self.session.post(
                url,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as response:
                response.raise_for_status()
                payload = await response.json()
            try:
                content = payload["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise TypeError("消息内容不是文本")
                start, end = content.find("["), content.rfind("]")
                if start < 0 or end < start:
                    raise ValueError("缺少 JSON 数组")
                items = json.loads(content[start : end + 1])
                if not isinstance(items, list):
                    raise TypeError("结果不是数组")
                tasks = []
                for item in items:
                    attachments = item["attachments"]
                    values = [
                        item["task_title"],
                        item["task_subject"],
                        item["related_time"],
                        item["earliest_time"],
                    ]
                    if (
                        any(not isinstance(value, str) for value in values)
                        or not isinstance(attachments, list)
                        or any(not isinstance(value, str) for value in attachments)
                    ):
                        raise ValueError("任务字段格式不正确")
                    if values[0].strip():
                        tasks.append(
                            Task(
                                values[0].strip(),
                                values[1].strip(),
                                attachments,
                                values[2].strip(),
                                values[3].strip(),
                            )
                        )
                return tasks
            except (
                KeyError,
                IndexError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                if attempt == 2:
                    raise AnalysisError("AI 返回的任务格式不正确") from exc
        return []
