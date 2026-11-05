from __future__ import annotations

from pathlib import Path

import aiohttp
from aiohttp import web

from .config import ConfigStore
from .snowluma import SnowLumaError
from .worker import Worker

STATIC = Path(__file__).parent / "static"


def create_app(config: ConfigStore, worker: Worker) -> web.Application:
    @web.middleware
    async def local_only(request: web.Request, handler):
        host = request.host.rsplit(":", 1)[0].lower()
        if host not in {"127.0.0.1", "localhost"}:
            raise web.HTTPForbidden()
        origin = request.headers.get("Origin")
        if origin and origin != f"http://{request.host}":
            raise web.HTTPForbidden()
        response = await handler(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' https://p.qlogo.cn; base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    async def index(request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC / "index.html")

    async def messages_page(request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC / "messages.html")

    async def get_config(request: web.Request) -> web.Response:
        return web.json_response({"config": config.public(), "status": worker.status()})

    async def save_config(request: web.Request) -> web.Response:
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType()
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise TypeError("配置格式不正确")
            result = config.save(body)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        await worker.apply()
        return web.json_response({"config": result, "status": worker.status()})

    async def status(request: web.Request) -> web.Response:
        return web.json_response(worker.status())

    async def groups(request: web.Request) -> web.Response:
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType()
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise TypeError("连接设置格式不正确")
            connection = config.connection_settings(body)
            items = await worker.client(connection).action("get_group_list", {})
            return web.json_response(
                {
                    "groups": [
                        {
                            "id": str(item["group_id"]),
                            "name": item.get("group_remark") or item["group_name"],
                        }
                        for item in items
                    ]
                }
            )
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except (TimeoutError, aiohttp.ClientError, SnowLumaError):
            return web.json_response(
                {"error": "无法读取群列表，请检查连接地址和令牌"}, status=502
            )

    async def history(request: web.Request) -> web.Response:
        try:
            cursor = int(request.query["before"]) if "before" in request.query else None
            if cursor is not None and not 0 < cursor < 9223372036854775807:
                raise ValueError
            kind = request.query.get("kind", "messages")
            if kind == "messages":
                result = worker.history.list_messages(
                    config.value["filter"]["groups"], cursor
                )
            elif kind == "ai":
                result = worker.history.list_ai(cursor)
            else:
                raise ValueError
            return web.json_response(result)
        except ValueError:
            return web.json_response({"error": "记录查询参数无效"}, status=400)

    app = web.Application(middlewares=[local_only], client_max_size=128 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/messages", messages_page)
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/config", save_config)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/groups", groups)
    app.router.add_get("/api/messages", history)
    app.router.add_static("/static/", STATIC)
    return app
