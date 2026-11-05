from __future__ import annotations

from pathlib import Path

import aiohttp
from aiohttp import web

from .config import ConfigStore
from .snowluma import SnowLumaError
from .todoist import TodoistClient
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

    async def groups_page(request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC / "groups.html")

    async def rules_page(request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC / "rules.html")

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

    async def patch_config(request: web.Request) -> web.Response:
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType()
        try:
            body = await request.json()
            if not isinstance(body, dict) or not body:
                raise TypeError("配置格式不正确")
            result = config.patch(body)
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
            source = body.get("source", "snowluma")
            if source == "notification":
                connection = config.value["notification"]
                if not connection[f"{connection['mode']}_url"]:
                    raise ValueError("请先在设置中填写通知账号的连接地址")
            elif source == "snowluma":
                connection = config.connection_settings(body)
            else:
                raise ValueError("未知的群列表来源")
            refresh = body.get("refresh", False)
            if type(refresh) is not bool:
                raise TypeError("刷新参数必须是开关")
            items = await worker.client(connection).action(
                "get_group_list", {"no_cache": refresh} if source == "snowluma" else {}
            )
            return web.json_response(
                {
                    "groups": [
                        {
                            "id": str(item["group_id"]),
                            "name": item.get("group_remark") or item["group_name"],
                            "member_count": item.get("member_count"),
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

    async def conversations(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "groups": worker.history.conversation_groups(
                    config.value["filter"]["groups"]
                )
            }
        )

    async def conversation(request: web.Request) -> web.Response:
        group_id = request.match_info["group_id"]
        if group_id not in config.value["filter"]["groups"]:
            raise web.HTTPNotFound()
        try:
            values = {}
            for key in ("before", "after", "range_start"):
                if key in request.query:
                    value = int(request.query[key])
                    if not 0 < value < 9223372036854775807:
                        raise ValueError
                    values[key] = value
            if (
                ("before" in values and "after" in values)
                or ("range_start" in values and "after" not in values)
                or ("range_start" in values and values["range_start"] > values["after"])
            ):
                raise ValueError
            return web.json_response(worker.history.conversation(group_id, **values))
        except ValueError:
            return web.json_response({"error": "记录查询参数无效"}, status=400)

    async def todoist_catalog(request: web.Request) -> web.Response:
        if not config.value["todoist"]["token"]:
            return web.json_response({"error": "请先填写 Todoist 令牌"}, status=400)
        try:
            return web.json_response(
                await TodoistClient(worker.session, config.value["todoist"]).catalog()
            )
        except (TimeoutError, aiohttp.ClientError) as exc:
            detail = (
                f"（HTTP {exc.status}）"
                if isinstance(exc, aiohttp.ClientResponseError)
                else ""
            )
            return web.json_response(
                {"error": f"无法读取 Todoist 项目和板块{detail}"}, status=502
            )

    async def todoist_create(request: web.Request) -> web.Response:
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType()
        if not config.value["todoist"]["token"]:
            return web.json_response({"error": "请先填写 Todoist 令牌"}, status=400)
        try:
            body = await request.json()
            if (
                not isinstance(body, dict)
                or not isinstance(body.get("name"), str)
                or not body["name"].strip()
            ):
                raise ValueError("请输入名称")
            name = body["name"].strip()
            client = TodoistClient(worker.session, config.value["todoist"])
            kind = request.match_info["kind"]
            if kind == "projects":
                item = await client.create_project(name)
                result = {"id": str(item["id"]), "name": item["name"]}
            elif kind == "sections":
                project_id = body.get("project_id")
                if not isinstance(project_id, str) or not project_id.strip():
                    raise ValueError("请先选择项目")
                item = await client.create_section(name, project_id.strip())
                result = {
                    "id": str(item["id"]),
                    "name": item["name"],
                    "project_id": str(item["project_id"]),
                }
            else:
                raise ValueError("创建类型无效")
            return web.json_response(result)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except (TimeoutError, aiohttp.ClientError) as exc:
            detail = (
                f"（HTTP {exc.status}）"
                if isinstance(exc, aiohttp.ClientResponseError)
                else ""
            )
            return web.json_response({"error": f"Todoist 创建失败{detail}"}, status=502)

    app = web.Application(middlewares=[local_only], client_max_size=128 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/messages", messages_page)
    app.router.add_get("/groups", groups_page)
    app.router.add_get("/rules", rules_page)
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/config", save_config)
    app.router.add_patch("/api/config", patch_config)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/groups", groups)
    app.router.add_get("/api/messages", history)
    app.router.add_get("/api/conversations", conversations)
    app.router.add_get("/api/conversations/{group_id}", conversation)
    app.router.add_get("/api/todoist/catalog", todoist_catalog)
    app.router.add_post("/api/todoist/{kind}", todoist_create)
    app.router.add_static("/static/", STATIC)
    return app
