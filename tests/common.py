import asyncio
import logging
import socket
import threading
import unittest
from typing import Tuple

import structlog
import uberlogging

from .server import Server, SSLServer

logger = structlog.get_logger(__name__)
uberlogging.configure(root_level=logging.DEBUG)  # A bit ugly but very convenient


class TestClientBase(unittest.TestCase):
    server_class: Server = Server
    server: Server = None
    should_exit: bool = False
    server_thread: threading.Thread = None
    server_ready: threading.Event = None

    @classmethod
    def setUpClass(cls) -> None:
        logger.info("Class setup")
        cls.server = cls.server_class()
        when_ready = threading.Event()
        cls.server_thread = threading.Thread(target=asyncio.run, args=(cls.run_async_server(when_ready),))
        cls.server_thread.setDaemon(True)
        cls.server_thread.start()
        when_ready.wait()

    @classmethod
    async def run_async_server(cls, when_ready: threading.Event) -> None:
        await cls.server.start()
        when_ready.set()
        while not cls.should_exit:
            await asyncio.sleep(0.2)
        await cls.server.stop()

    @classmethod
    def tearDownClass(cls):
        cls.should_exit = True
        cls.server_thread.join()

    def run(self, result=None):
        logger.info("Testing %s", self.id())
        return super().run(result=result)

    async def asyncSetUp(self) -> None:
        # IsolatedAsyncioTestCase sets set the loop to debug
        # which creates too much noise and is unconfigurable
        asyncio.get_running_loop().set_debug(False)


class TestSSLClientBase(TestClientBase):
    server_class: Server = SSLServer


def get_free_port() -> Tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, type=socket.SOCK_STREAM)
    sock.bind(("localhost", 0))
    _, port = sock.getsockname()
    return sock, port
