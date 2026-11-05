from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import io
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import aiohttp
from PIL import Image, ImageOps, UnidentifiedImageError

from .storage import History

log = logging.getLogger("shisha")
MAX_DOWNLOAD = 32 * 1024 * 1024
MAX_MODEL_IMAGE = 5 * 1024 * 1024
MAX_MODEL_TOTAL = 32 * 1024 * 1024


class ImageError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedImage:
    marker: str
    original: bytes
    model_data: bytes
    model_type: str

    def model_url(self) -> str:
        data = base64.b64encode(self.model_data).decode("ascii")
        return f"data:{self.model_type};base64,{data}"

    def onebot_file(self) -> str:
        return "base64://" + base64.b64encode(self.original).decode("ascii")


class ImageStore:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        history: History,
        refresh_url: Callable[[str], Awaitable[str]],
    ):
        self.session = session
        self.history = history
        self.refresh_url = refresh_url
        self.directory = history.directory / "images"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.tasks: dict[tuple[int, int, int], asyncio.Task] = {}
        self.semaphore = asyncio.Semaphore(4)

    def start(self, group_id: int, message_id: int, position: int) -> asyncio.Task:
        key = (group_id, message_id, position)
        if key not in self.tasks:
            task = asyncio.create_task(self._cache(key))
            self.tasks[key] = task
            task.add_done_callback(lambda finished: self._finished(key, finished))
        return self.tasks[key]

    def _finished(self, key: tuple[int, int, int], task: asyncio.Task) -> None:
        self.tasks.pop(key, None)
        if not task.cancelled() and task.exception():
            log.warning("图片读取失败: %s", task.exception())

    async def _cache(self, key: tuple[int, int, int]) -> tuple[Path, str]:
        row = self.history.get_image(*key)
        if row is None:
            raise ImageError("找不到消息中的图片")
        if row["cached_name"]:
            path = self.directory / row["cached_name"]
            if path.is_file():
                return path, row["media_type"]
        try:
            async with self.semaphore:
                source = row["url"] or row["file"]
                try:
                    data, media_type = await self._load(source)
                except (aiohttp.ClientError, TimeoutError, ImageError) as original:
                    if not row["file"] or source.startswith(
                        ("base64://", "data:image/")
                    ):
                        raise
                    try:
                        fresh = await self.refresh_url(row["file"])
                    except (aiohttp.ClientError, TimeoutError, RuntimeError):
                        raise original
                    if not fresh or fresh == source:
                        raise
                    data, media_type = await self._load(fresh)
                    self.history.update_image_url(*key, fresh)
                name = hashlib.sha256(data).hexdigest()
                path = self.directory / name
                if not path.exists():
                    await asyncio.to_thread(write_image, path, data)
                self.history.update_image(*key, name, media_type, "")
                return path, media_type
        except (
            aiohttp.ClientError,
            TimeoutError,
            OSError,
            ValueError,
            ImageError,
        ) as exc:
            self.history.update_image(*key, "", "", str(exc))
            if isinstance(exc, ImageError):
                raise
            raise ImageError("无法读取图片") from exc

    async def _load(self, source: str) -> tuple[bytes, str]:
        data = await self._download(source)
        return data, await asyncio.to_thread(image_type, data)

    async def _download(self, source: str) -> bytes:
        if source.startswith("base64://"):
            encoded = source.removeprefix("base64://")
        elif source.startswith("data:image/") and ";base64," in source:
            encoded = source.split(";base64,", 1)[1]
        else:
            encoded = None
        if encoded is not None:
            if len(encoded) > (MAX_DOWNLOAD + 2) // 3 * 4:
                raise ImageError("图片超过 32 MiB")
            try:
                return base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ImageError("图片数据无效") from exc
        if not source.startswith(("https://", "http://")):
            raise ImageError("SnowLuma 未提供可访问的图片地址")
        timeout = aiohttp.ClientTimeout(total=30)
        async with self.session.get(source, timeout=timeout) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                data.extend(chunk)
                if len(data) > MAX_DOWNLOAD:
                    raise ImageError("图片超过 32 MiB")
            return bytes(data)

    async def prepare(
        self, marker: str, group_id: int, message_id: int, position: int
    ) -> PreparedImage:
        path, media_type = await asyncio.shield(
            self.start(group_id, message_id, position)
        )
        original = await asyncio.to_thread(path.read_bytes)
        try:
            model_data, model_type = await asyncio.to_thread(
                model_image, original, media_type
            )
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise ImageError("无法转换图片") from exc
        return PreparedImage(marker, original, model_data, model_type)

    async def close(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def write_image(path: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".image-")
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def image_type(data: bytes) -> str:
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 70_000_000:
                raise ImageError("图片尺寸过大")
            media_type = Image.MIME.get(image.format)
            image.verify()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:
        raise ImageError("图片格式无效") from exc
    if not media_type:
        raise ImageError("图片格式无效")
    return media_type


def model_image(data: bytes, media_type: str) -> tuple[bytes, str]:
    with Image.open(io.BytesIO(data)) as image:
        if (
            media_type in {"image/jpeg", "image/png"}
            and len(data) <= MAX_MODEL_IMAGE
            and max(image.size) <= 6000
        ):
            return data, media_type
        image.seek(0)
        image = ImageOps.exif_transpose(image)
        image.thumbnail((6000, 6000))
        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")
        for quality in (90, 80, 70, 60):
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            if output.tell() <= MAX_MODEL_IMAGE:
                return output.getvalue(), "image/jpeg"
        raise ImageError("图片压缩后仍超过 5 MiB")
