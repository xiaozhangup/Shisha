from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MessageImage:
    file: str
    url: str
    start: int
    end: int


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
    images: tuple[MessageImage, ...] = ()


@dataclass(frozen=True, slots=True)
class Task:
    title: str
    subject: str
    attachments: list[str]
    related_time: str
    earliest_time: str
    image_titles: dict[str, str] = field(default_factory=dict)
