from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GroupMessage:
    group_id: int
    user_id: int
    message_id: int
    text: str
    at_all: bool
    received_at: float
    group_name: str = ""
    sender_name: str = ""
    event_time: int = 0


@dataclass(frozen=True, slots=True)
class Task:
    title: str
    subject: str
    attachments: list[str]
    related_time: str
    earliest_time: str
