from __future__ import annotations

import argparse
import asyncio
import logging
import signal

import aiohttp
from aiohttp import web

from .config import ConfigStore, data_directory
from .storage import History
from .web import create_app
from .worker import Worker


def port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("端口必须是 0 到 65535 之间的整数") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须是 0 到 65535 之间的整数")
    return port


async def main(port: int = 0) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    directory = data_directory()
    config = ConfigStore(directory)
    history = History(directory)
    async with aiohttp.ClientSession() as session:
        worker = Worker(session, config, history)
        runner = web.AppRunner(create_app(config, worker), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
        port = runner.addresses[0][1]
        logging.getLogger("shisha").info("配置页面：http://127.0.0.1:%s", port)
        await worker.apply()
        stopped = asyncio.Event()
        loop = asyncio.get_running_loop()
        for name in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(name, stopped.set)
            except NotImplementedError:
                pass
        try:
            await stopped.wait()
        finally:
            await runner.cleanup()
            await worker.close()
            history.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="启动 Shisha")
    parser.add_argument(
        "-p", "--port", type=port_number, default=0, help="配置页面端口，默认为随机端口"
    )
    args = parser.parse_args()
    asyncio.run(main(args.port))
