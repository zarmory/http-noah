import logging
from unittest.mock import MagicMock

import structlog

from http_noah.common import ClientOptions, FormData, JSONData, Timeout
from http_noah.sync_client import ConnectionError, HTTPError, SyncAPIClientBase, SyncHTTPClient, TimeoutError

from .common import TestClientBase, get_free_port
from .models import Pet, Pets

logger = structlog.get_logger(__name__)

# V Get str, int, bytes
# V Get dict, list
# V Get model, custom root
# V Delete / Reponse None (204)
# V Submit model put/post
# V Submit JSON (dict) put/post
# V Submit form (dict) post
# V Client error => check body
# V Read timeout
# V Conn Error
# V Conn timeout
# V timeouts ctxmgr
#
# High level client? (Check ctxmgr warnings, etc.?)


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


class PetClient(SyncAPIClientBase):
    def list(self) -> Pets:
        return self.client.get("/pets", response_type=Pets)
