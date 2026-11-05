from __future__ import annotations

import json
from datetime import date

import aiohttp

from .models import Task

PROMPT = """我将向你发送一条或多条合并后的QQ消息，该消息通常为学校发布的通知类内容。请你严格按照以下要求执行任务：

### 核心目标
**100%精准匹配原文信息**，提取通知中的**任务主体**、**附件信息**、**相关时间**三类关键内容，并以指定JSON数组格式输出，确保无遗漏、无冗余、格式完全合规。
任何时间字段的输出，必须经过明确的语义推理，禁止机械按消息内年份填充。

### 任务拆解与执行规则
1. **信息提取范围**：**仅提取我发送的QQ通知消息原文中的显性信息**，禁止添加任何原文未提及的内容（包括推测、补充说明等）。
2. **分类提取规则（精准约束）**：
   - **任务标题**：简短概括通知的核心任务内容，48字以内，禁止使用泛泛描述（如“通知”、“安排”等），必须具体指向任务主体；若消息本身不是通知类型，该项为""。
   - **任务主体**：仅提取通知中**明确要求执行的核心动作事项**，为纯文本（可保留原文换行逻辑，但需剔除无关铺垫/背景）；若通知无明确任务要求，该项为""。
   - **附件信息**：仅提取通知中**直接呈现的附加内容**（链接、号码、网站、工具名称等），以文本列表形式呈现，每条格式固定为「类型: 内容」（类型需严格匹配内容属性，如链接、号码、工具、网站等，禁止自定义模糊类型）；若无附件，该项为[]。
   - **相关时间**：仅提取通知中**明确标注的日期/时间段/相对时间词信息**；若无时间信息，该项为""。
   - **最早时间**：从“相关时间”中筛选出的最早日期，仅包含单一日期或日期及具体时刻；若无时间信息，该项为""。

### 时间格式化规则
- 现在的时间是: {today}
- 日期使用 Todoist 支持的表达方式，如 2026-02-03。related_time 用于展示所有相关日期和时间段，日期区间用自然语言说明，例如“2026-02-03 至 2026-03-01”；仅有开始日期或结束日期时分别写“从 2026-02-03 起”或“截至 2026-02-03”，不要在日期后添加加号或减号。
- earliest_time 会直接作为 Todoist 的日期输入，必须是一个可由 Todoist 识别的英文自然语言日期表达式，例如 "2026-02-03"、"tomorrow"、"tomorrow at 16:00"；不要添加解释文字或日期区间。
- 若时间无年份，需根据通知上下文（如当前学年/学期）默认填充对应年份；若无法判断则保留原文时间信息，并在 earliest_time 中留空。
- 若有多个时间信息，均需提取并按上述格式规范化后，以逗号分隔呈现（如有时间段与单日时间混合出现，取时间段为准）。
- 若为相对时间词或者没有提供例如年份/月份等足够的时间信息，必须根据“现在的时间”进行解析，并在 related_time 中转化为明确的日期或日期范围。earliest_time 也可使用 Todoist 可识别的相对表达，但必须与推断后的日期一致。

### 年级 / 届别 / 学年时间推理规则（强制执行）
- 当通知中出现“XX级学生 / XX届学生 / 入学年份”等表述时：
  - “XX级”默认指 **XX年入学**，而非事件发生年份。
  - 若任务发生在入学后的某一阶段（如“第二年”“下一学期”“毕业前”“实习期间”等），必须以入学年份为基准进行年份推算。
- 禁止将“XX级”中的年份数字直接当作任务发生年份，除非通知中明确说明。
- 若同时出现“当前时间”与“级 / 届”信息，**以级 / 届语义优先于当前年份**。
- 示例：当前时间为 2025-08-15，文本为“2025级学生需于次年5月完成体测”，相关时间为 2026-05-01。

### 最早时间（earliest_time）精度规则（强制执行）
- earliest_time 用于表示通知中**最早发生的具体时间点**，应在不违反原文信息的前提下尽量提高精度。
- 若通知中明确给出了“具体时刻”（如“13:30”“下午2点”“18:00前”等），earliest_time 必须包含日期与时间，使用 Todoist 可识别的英文自然语言表达。
- 若通知中仅给出日期、时间段或相对日期，**未出现具体点钟信息**，earliest_time 仅输出日期。
- 禁止在原文未给出具体时刻的情况下，擅自补充或推测时间点（如默认08:00、00:00等）。
- 若多个时间信息中，只有部分包含具体时刻，earliest_time 应选择**时间上最早且精度最高的那一项**。

### 输出格式要求（严格合规）
输出必须为**标准JSON数组格式**（无语法错误，键名/引号/逗号完全符合JSON规范）。
即使合并的消息上下文中只有一个任务，也必须使用数组包裹。
若合并的消息中包含**多个不同且独立的任务/通知**，请将其拆分为数组中的多个JSON对象。
若消息本身不是通知类型，则返回空数组 `[]`。

每个任务对象的键名固定为英文：
{
  "task_title": "提取的任务标题（简短概括任务主体，48字以内）",
  "task_subject": "提取的任务主体纯文本（仅核心动作，无冗余）",
  "attachments": ["类型1: 内容1", "类型2: 内容2"],
  "related_time": "按规则格式化后的时间字符串；此处不包含时刻信息，仅填写日期或日期范围",
  "earliest_time": "最早的一个时间；使用 Todoist 可识别的英文自然语言日期，原文包含具体时刻时也要包含时刻"
}
不要输出 JSON 以外的文字。"""


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
                    "content": PROMPT.replace("{today}", date.today().isoformat()),
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
                                values[0],
                                values[1],
                                attachments,
                                values[2],
                                values[3],
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
