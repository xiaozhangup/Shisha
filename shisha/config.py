from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

DEFAULTS = {
    "snowluma": {
        "mode": "ws",
        "http_url": "http://127.0.0.1:3000/",
        "ws_url": "ws://127.0.0.1:3001/",
        "http_token": "",
        "ws_token": "",
    },
    "filter": {
        "groups": [],
        "keywords": [],
        "notification_group": "",
        "notify_enabled": True,
        "debounce_seconds": 30,
    },
    "ai": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "model": "glm-4.1v-thinking-flash",
        "api_key": "",
    },
    "todoist": {"enabled": True, "token": "", "section": ""},
}

SECRETS = {
    ("snowluma", "http_token"),
    ("snowluma", "ws_token"),
    ("ai", "api_key"),
    ("todoist", "token"),
}


def data_directory() -> Path:
    return Path(
        os.environ.get("SHISHA_DATA_DIR", Path.home() / ".local" / "share" / "shisha")
    ).expanduser()


class ConfigStore:
    def __init__(self, directory: Path):
        self.path = directory / "config.json"
        self.value = deepcopy(DEFAULTS)
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            for section in DEFAULTS:
                self.value[section].update(loaded.get(section, {}))
            self._validate(self.value)

    def public(self) -> dict:
        result = deepcopy(self.value)
        for section, name in SECRETS:
            result[section][f"{name}_saved"] = bool(result[section][name])
            result[section][name] = ""
        return result

    def save(self, submitted: dict) -> dict:
        updated = deepcopy(self.value)
        cleared = submitted.get("clear_secrets", [])
        if not isinstance(cleared, list):
            raise TypeError("密钥操作格式不正确")
        for section, defaults in DEFAULTS.items():
            values = submitted.get(section)
            if not isinstance(values, dict):
                raise TypeError(f"缺少配置：{section}")
            for name in defaults:
                value = values.get(name)
                if (section, name) in SECRETS:
                    if f"{section}.{name}" in cleared:
                        updated[section][name] = ""
                    elif value:
                        updated[section][name] = value
                else:
                    updated[section][name] = value
        self._validate(updated)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp_name = tempfile.mkstemp(
            dir=self.path.parent, prefix=".config-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(updated, file, ensure_ascii=False, indent=2)
                file.write("\n")
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        self.value = updated
        return self.public()

    @staticmethod
    def _validate(config: dict) -> None:
        for section, defaults in DEFAULTS.items():
            for name, default in defaults.items():
                value = config[section][name]
                if isinstance(default, list):
                    if not isinstance(value, list) or any(
                        not isinstance(item, str) for item in value
                    ):
                        raise ValueError(f"{section}.{name} 必须是文本列表")
                    config[section][name] = list(
                        dict.fromkeys(item.strip() for item in value if item.strip())
                    )
                elif isinstance(default, bool):
                    if type(value) is not bool:
                        raise TypeError(f"{section}.{name} 必须是开关")
                elif isinstance(default, int):
                    if type(value) is not int or not 1 <= value <= 300:
                        raise ValueError("合并等待时间应为 1–300 秒")
                elif not isinstance(value, str):
                    raise TypeError(f"{section}.{name} 必须是文本")
                else:
                    config[section][name] = value.strip()
        connection = config["snowluma"]
        mode = connection["mode"]
        if mode not in {"http", "ws"}:
            raise ValueError("请选择 HTTP 或 WebSocket")
        key, schemes = (
            ("http_url", {"http", "https"})
            if mode == "http"
            else ("ws_url", {"ws", "wss"})
        )
        parsed = urlsplit(connection[key])
        if (
            parsed.scheme not in schemes
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or (mode == "http" and parsed.query)
        ):
            raise ValueError(f"SnowLuma {key} 地址无效")
        parsed = urlsplit(config["ai"]["base_url"])
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("AI 地址无效")
        groups = config["filter"]["groups"]
        target = config["filter"]["notification_group"]
        if any(
            not group.isascii() or not group.isdigit() or int(group) <= 0
            for group in groups
        ):
            raise ValueError("监听群号必须为正整数")
        if target and (
            not target.isascii() or not target.isdigit() or int(target) <= 0
        ):
            raise ValueError("通知群号必须为正整数")

    def ready(self) -> bool:
        c = self.value
        return bool(
            c["filter"]["groups"]
            and c["ai"]["model"]
            and c["ai"]["api_key"]
            and (not c["filter"]["notify_enabled"] or c["filter"]["notification_group"])
            and (not c["todoist"]["enabled"] or c["todoist"]["token"])
        )

    def connection_settings(self, submitted: dict) -> dict:
        candidate = deepcopy(self.value)
        mode = submitted.get("mode")
        if mode not in {"http", "ws"}:
            raise ValueError("请选择 HTTP 或 WebSocket")
        candidate["snowluma"]["mode"] = mode
        candidate["snowluma"][f"{mode}_url"] = submitted.get("url")
        token = submitted.get("token")
        if submitted.get("clear_token") is True:
            candidate["snowluma"][f"{mode}_token"] = ""
        elif token:
            candidate["snowluma"][f"{mode}_token"] = token
        self._validate(candidate)
        return candidate["snowluma"]
