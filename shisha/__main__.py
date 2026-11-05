from __future__ import annotations

import asyncio
import logging
import signal

import aiohttp
from aiohttp import web

from .config import ConfigStore, data_directory
from .storage import History
from .web import create_app
from .worker import Worker


async def main() -> None:
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
        site = web.TCPSite(runner, "127.0.0.1", 0)
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
    asyncio.run(main())
