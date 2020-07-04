from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from types import TracebackType
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, Optional, Type

import aiohttp
import structlog
import yarl

from . import common as c

from .common import ClientOptions, FormData, JSONData, Timeout, UploadFile  # noqa: F401; Public stuff

logger = structlog.get_logger(__name__)

# Hoisting most common exceptions here to simply
# error handling for simple cases.
# Also renaming them to unify with SyncClient
ConnectionError = aiohttp.ClientConnectionError
HTTPError = aiohttp.ClientResponseError
TimeoutError = asyncio.TimeoutError


@dataclass(frozen=True)
class ResponseHook:
    status: HTTPStatus
    hook: Callable[[], Awaitable[None]]


@dataclass
class AsyncHTTPClient:
    """
    Low-level HTTP client for interacting with REST APIs.
    """

    host: str
    port: int = 80
    scheme: str = "http"
    api_base: str = "/api/v1"
    options: Optional[ClientOptions] = None

    url: yarl.URL = field(init=False, repr=False)
    session: aiohttp.ClientSession = field(init=False, repr=False)
    hook: Optional[ResponseHook] = None

    def __post_init__(self) -> None:
        self.url = yarl.URL.build(host=self.host, port=self.port, scheme=self.scheme, path=self.api_base)
        self.session = aiohttp.ClientSession()

    def set_token(self, token: str) -> None:
        # Using private member, but... otherwise we need
        # to duplicate exactly the same functionality in our code here
        self.session._default_headers["Authorization"] = f"Bearer {token}"

    async def close(self) -> None:
        await self.session.close()

    async def __aenter__(self) -> AsyncHTTPClient:
        return self

    async def __aexit__(
        self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]
    ) -> None:
        await self.close()

    @asynccontextmanager
    async def timeout(self, timeout: Timeout) -> AsyncGenerator[None, None]:
        """
        A handy context manager to temporary set timeout values for the following request.
        Useful when you don't want to expose timeout args to all methods of your high-level client.
        For example::

            @dataclass
            HighLevelClient:
                client: AsyncHTTPClient

                async def ping(self) -> None:
                    await self.client.get("/ping")

            # Now let's use it:
            hl = HighLevelClient(client=AsyncHTTPClient(...))
            async with hl.client.timeout(Timeout(total=10)):
                await hl.ping()
        """

        token = c._timeout_ctx.set(timeout)
        try:
            yield
        finally:
            c._timeout_ctx.reset(token)

    async def get(
        self,
        path: str,
        query_params: Optional[dict] = None,
        response_type: Optional[Type[c.ResponseType]] = None,
        timeout: Optional[Timeout] = None,
    ) -> Optional[c.ResponseType]:
        """
        Issue GET request to the API path with the supplied query_params
        and parse result as requested in response_type.
        """
        url = self.url / path.lstrip("/")
        return await self._request(
            self.session.get, url, query_params=query_params, response_type=response_type, timeout=timeout
        )

    async def post(
        self,
        path: str,
        body: c.OMulti = None,
        query_params: Optional[dict] = None,
        response_type: Optional[Type[c.ResponseType]] = None,
        timeout: Optional[Timeout] = None,
    ) -> Optional[c.ResponseType]:
        """
        Issue POST request to the API path with the supplied body / query_params
        and parse result as requested in response_type.
        """
        url = self.url / path.lstrip("/")
        return await self._request(
            self.session.post, url, body=body, query_params=query_params, response_type=response_type, timeout=timeout
        )

    async def put(
        self,
        path: str,
        body: c.OMulti = None,
        query_params: Optional[dict] = None,
        response_type: Optional[Type[c.ResponseType]] = None,
        timeout: Optional[Timeout] = None,
    ) -> Optional[c.ResponseType]:
        """
        Issue PUT request to the API path with the supplied body / query_params
        and parse result as requested in response_type.
        """
        url = self.url / path.lstrip("/")
        return await self._request(
            self.session.put, url, body=body, query_params=query_params, response_type=response_type, timeout=timeout
        )

    async def delete(
        self,
        path: str,
        body: c.OMulti = None,
        query_params: Optional[dict] = None,
        response_type: Optional[Type[c.ResponseType]] = None,
        timeout: Optional[Timeout] = None,
    ) -> Optional[c.ResponseType]:
        """
        Issue DELETE request to the API path with the supplied body / query_params
        and parse result as requested in response_type.
        """
        url = self.url / path.lstrip("/")
        return await self._request(
            self.session.delete, url, body=body, query_params=query_params, response_type=response_type, timeout=timeout
        )

    async def _request(
        self,
        # The best we can do: https://github.com/python/mypy/issues/5876
        method: Callable[..., aiohttp.client._RequestContextManager],
        url: yarl.URL,
        body: c.OMulti = None,
        query_params: Optional[dict] = None,
        response_type: Optional[Type[c.ResponseType]] = None,
        timeout: Optional[Timeout] = None,
        _from_hook: bool = False,
        **kwargs: Any,
    ) -> Optional[c.ResponseType]:

        logger.debug(
            "Performing request", method=method.__name__, url=url, body=body, query_params=query_params, kwargs=kwargs
        )

        req_kwargs = {}
        req_kwargs.update(kwargs)
        req_kwargs.update(self._convert_options(self.options))
        _timeout = timeout or c._timeout_ctx.get()
        if _timeout:
            req_kwargs.update(self._convert_timeout(_timeout))
        req_kwargs["params"] = query_params

        if isinstance(body, UploadFile):
            req_kwargs["data"] = body.prepare()
        else:
            req_kwargs.update(c.body_to_payload_args(body))

        async with method(url, **req_kwargs) as res:
            # Fetching text as error just in case - raise_for_status() will
            # release the connection so the error body will be lost already
            # text will be cached in the response internally for the use later on
            # so no waste here.
            err_body = await res.text()
            try:
                res.raise_for_status()
            except HTTPError as err:
                logger.error("Request failed", err=err, err_body=err_body)
                raise

            if res.status == HTTPStatus.NO_CONTENT.value:
                data = None
            elif c.json_re.match(res.headers["content-type"]) is not None:
                data = await res.json()
            elif issubclass(response_type, bytes):
                # Special cae for checking response_type for bytes since we can't guess
                # it from the response itself - some data can be treated as both and it
                # really depends on what our caller expects
                data = await res.read()
            else:
                data = await res.text()

            return c.parse_response_data(data, response_type)

    def _convert_options(self, options: Optional[ClientOptions] = None) -> dict:
        kwargs: Dict[str, Any] = {}
        if not options:
            return kwargs

        if options.ssl_verify_cert is False:
            kwargs["ssl"] = False

        if options.timeout:
            kwargs.update(self._convert_timeout(options.timeout))

        return kwargs

    def _convert_timeout(self, timeout: Timeout) -> dict:
        kwargs: Dict[str, Any] = {}
        kwargs["timeout"] = aiohttp.ClientTimeout(total=timeout.total, connect=timeout.connect, sock_read=timeout.read,)
        return kwargs

    # Safeguard against improper use
    # Borrowed from aiohttp.ClientSession
    def __enter__(self) -> None:
        raise TypeError("Use 'async with' instead")

    def __exit__(
        self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]
    ) -> None:
        # __exit__ should exist in pair with __enter__ but never executed
        pass  # pragma: no cover


@dataclass
class AsyncAPIClientBase:
    """
    Base high-level API client.
    Imlements context-manager boilerplate
    """

    client: AsyncHTTPClient

    async def close(self) -> None:
        await self.client.close()

    async def __aenter__(self) -> AsyncAPIClientBase:
        return self

    async def __aexit__(
        self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]
    ) -> None:
        await self.close()

    # Safeguard against improper use
    # Borrowed from aiohttp.ClientSession
    def __enter__(self) -> None:
        raise TypeError("Use 'async with' instead")

    def __exit__(
        self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]
    ) -> None:
        # __exit__ should exist in pair with __enter__ but never executed
        pass  # pragma: no cover
