# Using aiohttp server part since it already comes as part of aiohttp
import asyncio
import socket
import ssl
import subprocess
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

import structlog
from aiohttp import BasicAuth, web

from .models import Pet, Pets

routes = web.RouteTableDef()
logger = structlog.get_logger(__name__)


@routes.get("/api/v1/str")
async def get_str(request: web.Request):
    return web.Response(text="boo")


@routes.get("/api/v1/bearer_protected_str")
async def get_bearer_protected_str(request: web.Request):
    logger.info(auth=request.headers.get("Authorization"))
    if request.headers.get("authorization", "") != "Bearer let-the-bear-in":
        raise web.HTTPForbidden()
    return web.Response(text="you have made it through")


@routes.get("/api/v1/basic_protected_str")
async def get_basic_protected_str(request: web.Request):
    logger.info(auth=request.headers.get("Authorization"))
    auth_info = request.headers.get("authorization", "")
    if not auth_info:
        raise web.HTTPForbidden()
    try:
        auth = BasicAuth.decode(auth_info)
    except ValueError:
        logger.exception(f"Failed to decode auth data {auth_info}")
        raise web.HTTPBadRequest()
    if auth.login != "emu" and auth.password != "wars":
        raise web.HTTPForbidden()
    return web.Response(text="you have made it through")


@routes.get("/api/v1/bytes")
async def get_bytes(request: web.Request):
    return web.Response(body=b"bin-boo")


@routes.get("/api/v1/int")
async def get_int(request: web.Request):
    return web.Response(text="1")


@routes.get("/api/v1/json_int")
async def get_json_int(request: web.Request):
    return web.json_response(1)


@routes.get("/api/v1/json_str")
async def get_json_str(request: web.Request):
    return web.json_response("boo")


@routes.delete("/api/v1/pets/1")
async def delete_pet(request: web.Request):
    return web.Response(status=HTTPStatus.NO_CONTENT)


@routes.get("/api/v1/pets/1")
async def get_pet(request: web.Request):
    return web.json_response(Pet(name="foo").dict())


@routes.put("/api/v1/pets/1")
async def put_pet(request: web.Request):
    pet_info = await request.json()
    return web.json_response(Pet(name=pet_info["name"]).dict())


@routes.get("/api/v1/pets")
async def get_pets(request: web.Request):
    pets = Pets(__root__=[Pet(name="foo"), Pet(name="bar")])
    return web.json_response(pets.dict()["__root__"])


@routes.post("/api/v1/pets")
async def post_pets(request: web.Request):
    pet_info = await request.json()
    return web.json_response(Pet(name=pet_info["name"]).dict())


@routes.post("/api/v1/pets/_from_form")
async def post_pets_form(request: web.Request):
    pet_form = await request.post()
    return web.json_response(Pet(name=pet_form["name"]).dict())


@routes.get("/api/v1/pets/2")
async def get_missing_pet(request: web.Request):
    raise web.HTTPNotFound(body="No such pet")


@routes.get("/api/v1/pets/slow")
async def get_slow_pet(request: web.Request):
    # At least 1 second since client measures timeouts in multiples of 1 second
    # https://github.com/aio-libs/aiohttp/issues/4850
    await asyncio.sleep(1.1)
    return web.json_response(Pet(name="slow").dict())


@routes.post("/api/v1/pets/slow")
async def post_slow_pet(request: web.Request):
    # At least 1 second since client measures timeouts in multiples of 1 second
    # https://github.com/aio-libs/aiohttp/issues/4850
    await asyncio.sleep(1.1)
    return web.json_response(Pet(name="slow").dict())


@routes.put("/api/v1/pets/slow")
async def put_slow_pet(request: web.Request):
    # At least 1 second since client measures timeouts in multiples of 1 second
    # https://github.com/aio-libs/aiohttp/issues/4850
    await asyncio.sleep(1.1)
    return web.json_response(Pet(name="slow").dict())


@routes.delete("/api/v1/pets/slow")
async def delete_slow_pet(request: web.Request):
    # At least 1 second since client measures timeouts in multiples of 1 second
    # https://github.com/aio-libs/aiohttp/issues/4850
    await asyncio.sleep(1.1)
    return web.json_response(Pet(name="slow").dict())


@routes.post("/api/v1/pets/1/photo")
async def set_pet_photo(request: web.Request):
    data = await request.post()
    return web.Response(text=data["photo"].file.read().decode())


@dataclass
class Server:
    port: int = field(init=False)
    sock: socket.socket = field(init=False)
    site: web.SockSite = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, type=socket.SOCK_STREAM)
        self.sock.bind(("localhost", 0))
        _, self.port = self.sock.getsockname()

    async def start(self, ssl_context: Optional[ssl.SSLContext] = None) -> None:
        app = web.Application()
        app.add_routes(routes)
        runner = web.AppRunner(app)
        await runner.setup()
        self.site = web.SockSite(runner=runner, sock=self.sock, ssl_context=ssl_context)
        await self.site.start()
        logger.info("Server is up", port=self.port)

    async def stop(self) -> None:
        await self.site.stop()
        logger.info("Server stopped")
        self.sock.close()


@dataclass
class SSLServer(Server):
    cert_file: NamedTemporaryFile = field(init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.cert_file = NamedTemporaryFile()
        self._gen_cert(self.cert_file.name)

    def _gen_cert(self, path: Path) -> None:
        subprocess.run(
            f"openssl req -new -x509 -days 365 -nodes -out {path} -keyout {path}"
            + " -subj '/C=AU/ST=VIC/O=ACME/CN=example.com'",
            shell=True,
            check=True,
            capture_output=True,
        )
        logger.info("Generated x509 key/cert", path=path)

    async def start(self) -> None:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(self.cert_file.name)
        return await super().start(ssl_context)

    async def stop(self) -> None:
        self.cert_file.close()
        await super().stop()
