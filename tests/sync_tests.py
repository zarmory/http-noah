import logging
from tempfile import NamedTemporaryFile
from unittest.mock import MagicMock

import requests
import structlog
from urllib3.exceptions import InsecureRequestWarning

from http_noah.common import ClientOptions, FormData, JSONData, Timeout, UploadFile
from http_noah.sync_client import ConnectionError, HTTPError, SyncAPIClientBase, SyncHTTPClient, TimeoutError

from .common import TestClientBase, TestSSLClientBase, get_free_port
from .models import Pet, Pets

logger = structlog.get_logger(__name__)


class TestSyncClient(TestClientBase):
    def setUp(self) -> None:
        self.client = SyncHTTPClient("localhost", self.server.port)
        super().setUp()

    def test_get_str(self) -> None:
        s = self.client.get("/str", response_type=str)
        self.assertEqual(s, "boo")

    def test_get_bytes(self) -> None:
        b = self.client.get("/bytes", response_type=bytes)
        self.assertEqual(b, b"bin-boo")

    def test_get_int(self) -> None:
        with self.assertRaises(TypeError):
            self.client.get("/int", response_type=int)

    def test_get_json_str(self) -> None:
        s = self.client.get("/json_str", response_type=str)
        self.assertEqual(s, "boo")

    def test_get_json_int(self) -> None:
        i = self.client.get("/json_int", response_type=int)
        self.assertEqual(i, 1)

    def test_get_list(self) -> None:
        pets = self.client.get("/pets", response_type=list)
        self.assertIsInstance(pets, list)

    def test_get_dict(self) -> None:
        pet = self.client.get("/pets/1", response_type=dict)
        self.assertIsInstance(pet, dict)

    def test_get_model(self) -> None:
        pet = self.client.get("/pets/1", response_type=Pet)
        self.assertIsInstance(pet, Pet)

    def test_get_model_with_list_root(self) -> None:
        pets = self.client.get("/pets", response_type=Pets)
        logger.info(pets=pets)
        self.assertIsInstance(pets, Pets)

    def test_delete(self) -> None:
        self.assertIsNone(self.client.delete("/pets/1"))
        self.assertIsNone(self.client.delete("/pets/1", response_type=None))

    def test_post_put_model(self) -> None:
        pet = Pet(name="foo")
        pet = self.client.post("/pets", body=pet, response_type=Pet)
        self.assertIsInstance(pet, Pet)
        pet = self.client.put("/pets/1", body=pet, response_type=Pet)
        self.assertIsInstance(pet, Pet)

    def test_post_put_dict_as_json(self) -> None:
        pet = Pet(name="foo")
        jpet = JSONData(data=pet.dict())
        pet = self.client.post("/pets", body=jpet, response_type=Pet)
        self.assertIsInstance(pet, Pet)
        pet = self.client.put("/pets/1", body=jpet, response_type=Pet)
        self.assertIsInstance(pet, Pet)

    def test_post_dict_as_form(self) -> None:
        pet = Pet(name="foo")
        fpet = FormData(data=pet.dict())
        pet = self.client.post("/pets/_from_form", body=fpet, response_type=Pet)

    def test_client_error_body(self) -> None:
        with self.assertLogs("http_noah.sync_client", level=logging.ERROR) as cm:
            with self.assertRaises(HTTPError):
                self.client.get("/pets/2")
            # Logging may contain ASCII color escape chars, hence using regex
            self.assertRegex(cm.records[0].context, "err_body.*=.*No such pet")

    def test_read_timeout_ctx(self) -> None:
        with self.assertRaises(TimeoutError):
            with self.client.timeout(Timeout(total=0.1)):
                self.client.get("/pets/slow")

    def test_read_timeout(self) -> None:
        for timeout in (Timeout(total=0.1), Timeout(read=0.1)):
            options = ClientOptions(timeout=timeout)
            client = SyncHTTPClient("localhost", self.server.port, options=options)
            with self.assertRaises(TimeoutError):
                client.get("/pets/slow", response_type=Pet)
            with self.assertRaises(TimeoutError):
                self.client.get("/pets/slow", timeout=timeout)
            with self.assertRaises(TimeoutError):
                self.client.put("/pets/slow", timeout=timeout)
            with self.assertRaises(TimeoutError):
                self.client.post("/pets/slow", timeout=timeout)
            with self.assertRaises(TimeoutError):
                self.client.delete("/pets/slow", timeout=timeout)

    def test_connect_timeout(self) -> None:
        client = SyncHTTPClient("www.google.com", 81)
        # This is where requests and aiohttp differ too much - aiohttp raised timeout on connection timeout,
        # but requests raises requests.exceptions.ConnectionError
        with self.assertRaises(ConnectionError):
            client.get("/", response_type=Pet, timeout=Timeout(connect=0.1))
        with self.assertRaises(ConnectionError):
            client.get("/", response_type=Pet, timeout=Timeout(total=0.1))

    def test_connection_error(self) -> None:
        sock, port = get_free_port()
        try:
            client = SyncHTTPClient("localhost", port)
            with self.assertRaises(ConnectionError):
                client.get("/")
        finally:
            sock.close()

    def test_hl_client(self) -> None:
        with PetClient(client=self.client) as pets:
            pets.client.session.close = MagicMock(side_efect=pets.client.session.close)
            pets.list()

        pets.client.session.close.assert_called()

    def test_file_upload(self) -> None:
        content = b"Hello Noah"
        with NamedTemporaryFile() as tmpfile:
            tmpfile.write(content)
            tmpfile.flush()
            upload = UploadFile(name="photo", path=tmpfile.name)
            b = self.client.post("/pets/1/photo", body=upload, response_type=bytes)
            self.assertEqual(b, content)


class TestSyncSSLClient(TestSSLClientBase):
    def test_disable_ssl_validation(self):
        options = ClientOptions(ssl_verify_cert=False)
        client = SyncHTTPClient("localhost", self.server.port, scheme="https", options=options)
        with self.assertWarns(InsecureRequestWarning):
            s = client.get("/str", response_type=str)
        self.assertEqual(s, "boo")

    def test_requires_ssl_validation(self):
        with SyncHTTPClient("localhost", self.server.port, scheme="https") as client:
            with self.assertRaises(requests.exceptions.SSLError):
                client.get("/str", response_type=str)


class PetClient(SyncAPIClientBase):
    def list(self) -> Pets:
        return self.client.get("/pets", response_type=Pets)
