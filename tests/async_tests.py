import logging
import unittest
from tempfile import NamedTemporaryFile

import aiohttp
import structlog

from http_noah.async_client import AsyncAPIClientBase, AsyncHTTPClient, ConnectionError, HTTPError, TimeoutError
from http_noah.common import ClientOptions, FormData, JSONData, Timeout, UploadFile

from .common import TestClientBase, TestSSLClientBase, get_free_port
from .models import Pet, Pets

logger = structlog.get_logger(__name__)


class TestAsyncClient(TestClientBase, unittest.IsolatedAsyncioTestCase):
    async def test_get_str(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            s = await client.get("/str", response_type=str)
            self.assertEqual(s, "boo")

    async def test_get_bytes(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            b = await client.get("/bytes", response_type=bytes)
            self.assertEqual(b, b"bin-boo")

    async def test_get_int(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            with self.assertRaises(TypeError):
                await client.get("/int", response_type=int)

    async def test_get_json_str(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            s = await client.get("/json_str", response_type=str)
            self.assertEqual(s, "boo")

    async def test_get_json_int(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            i = await client.get("/json_int", response_type=int)
            self.assertEqual(i, 1)

    async def test_get_list(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            pets = await client.get("/pets", response_type=list)
            self.assertIsInstance(pets, list)

    async def test_get_dict(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            pet = await client.get("/pets/1", response_type=dict)
            self.assertIsInstance(pet, dict)

    async def test_get_model(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            pet = await client.get("/pets/1", response_type=Pet)
            self.assertIsInstance(pet, Pet)

    async def test_get_model_with_list_root(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            pets = await client.get("/pets", response_type=Pets)
            self.assertIsInstance(pets, Pets)

    async def test_delete(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            self.assertIsNone(await client.delete("/pets/1"))
            self.assertIsNone(await client.delete("/pets/1", response_type=None))

    async def test_post_put_model(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            pet = Pet(name="foo")
            pet = await client.post("/pets", body=pet, response_type=Pet)
            self.assertIsInstance(pet, Pet)
            pet = await client.put("/pets/1", body=pet, response_type=Pet)
            self.assertIsInstance(pet, Pet)

    async def test_post_put_dict_as_json(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            pet = Pet(name="foo")
            jpet = JSONData(data=pet.dict())
            pet = await client.post("/pets", body=jpet, response_type=Pet)
            self.assertIsInstance(pet, Pet)
            pet = await client.put("/pets/1", body=jpet, response_type=Pet)
            self.assertIsInstance(pet, Pet)

    async def test_post_dict_as_form(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            pet = Pet(name="foo")
            fpet = FormData(data=pet.dict())
            pet = await client.post("/pets/_from_form", body=fpet, response_type=Pet)

    async def test_client_error_body(self) -> None:
        with self.assertLogs("http_noah.async_client", level=logging.ERROR) as cm:
            with self.assertRaises(HTTPError):
                async with AsyncHTTPClient("localhost", self.server.port) as client:
                    await client.get("/pets/2")
            # Logging may contain ASCII color escape chars, hence using regex
            self.assertRegex(cm.records[0].context, "err_body.*=.*No such pet")

    async def test_read_timeout_ctx(self) -> None:
        async with AsyncHTTPClient("localhost", self.server.port) as client:
            with self.assertRaises(TimeoutError):
                async with client.timeout(Timeout(total=0.1)):
                    logger.info("calling")
                    try:
                        await client.get("/pets/slow")
                    finally:
                        logger.info("done")

    async def test_read_timeout(self) -> None:
        for timeout in (Timeout(total=0.1), Timeout(read=0.1)):
            options = ClientOptions(timeout=timeout)
            async with AsyncHTTPClient("localhost", self.server.port, options=options) as client:
                with self.assertRaises(TimeoutError):
                    await client.get("/pets/slow")
            async with AsyncHTTPClient("localhost", self.server.port) as client:
                with self.assertRaises(TimeoutError):
                    await client.get("/pets/slow", timeout=timeout)
                with self.assertRaises(TimeoutError):
                    await client.put("/pets/slow", timeout=timeout)
                with self.assertRaises(TimeoutError):
                    await client.post("/pets/slow", timeout=timeout)
                with self.assertRaises(TimeoutError):
                    await client.delete("/pets/slow", timeout=timeout)

    async def test_connect_timeout(self) -> None:
        async with AsyncHTTPClient("www.google.com", 81) as client:
            # This is where requests and aiohttp differ too much - aiohttp raised timeout on connection timeout,
            # but requests raises requests.exceptions.ConnectionError
            with self.assertRaises(TimeoutError):
                await client.get("/", timeout=Timeout(total=0.1))
            with self.assertRaises(TimeoutError):
                await client.get("/", timeout=Timeout(connect=0.1))

    async def test_connection_error(self) -> None:
        sock, port = get_free_port()
        try:
            async with AsyncHTTPClient("localhost", port) as client:
                with self.assertRaises(ConnectionError):
                    await client.get("/")
        finally:
            sock.close()

    async def test_hl_client(self) -> None:
        client = AsyncHTTPClient("localhost", self.server.port)
        logger.info(client.session)
        async with PetClient(client=client) as pets:
            await pets.list()

        self.assertTrue(pets.client.session.closed)

    async def test_file_upload(self) -> None:
        content = b"Hello Noah"
        with NamedTemporaryFile() as tmpfile:
            tmpfile.write(content)
            tmpfile.flush()
            upload = UploadFile(name="photo", path=tmpfile.name)
            async with AsyncHTTPClient("localhost", self.server.port) as client:
                b = await client.post("/pets/1/photo", body=upload, response_type=bytes)
                self.assertEqual(b, content)


class TestAsyncSSLClient(TestSSLClientBase, unittest.IsolatedAsyncioTestCase):
    async def test_disable_ssl_validation(self):
        options = ClientOptions(ssl_verify_cert=False)
        async with AsyncHTTPClient("localhost", self.server.port, scheme="https", options=options) as client:
            s = await client.get("/str", response_type=str)
            self.assertEqual(s, "boo")

    async def test_requires_ssl_validation(self):
        async with AsyncHTTPClient("localhost", self.server.port, scheme="https") as client:
            with self.assertRaises(aiohttp.client_exceptions.ClientConnectorCertificateError):
                await client.get("/str", response_type=str)


class PetClient(AsyncAPIClientBase):
    async def list(self) -> Pets:
        return await self.client.get("/pets", response_type=Pets)
