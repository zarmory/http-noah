from __future__ import annotations

import mimetypes
import warnings
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from types import TracebackType
from typing import Any, Callable, Dict, Generator, Optional, Type, cast

import requests
import structlog
import yarl

from . import common as c

from .common import ClientOptions, FormData, JSONData, Timeout, UploadFile  # noqa: F401; Public stuff

logger = structlog.get_logger(__name__)


# Hoisting most common exceptions here to simplify
# error handling for simple cases.
ConnectionError = requests.exceptions.ConnectionError
HTTPError = requests.exceptions.HTTPError
TimeoutError = requests.exceptions.Timeout


@dataclass(frozen=True)
class ResponseHook:
    status: HTTPStatus
    hook: Callable[[], None]


@dataclass
class SyncHTTPClient:
    """
    Low-level HTTP client for interacting with HS APIs.
    """

    host: str
    port: int = 80
    scheme: str = "http"
    api_base: str = "/api/v1"
    options: ClientOptions = field(default=ClientOptions())

    url: yarl.URL = field(init=False, repr=False)
    session: requests.Session = field(init=False, repr=False)
    hook: Optional[ResponseHook] = None

    def __post_init__(self) -> None:
        self.url = yarl.URL.build(host=self.host, port=self.port, scheme=self.scheme, path=self.api_base)
        self.session = requests.Session()

    def set_token(self, token: str) -> None:
        warnings.warn("set_token() is deprectated in favour of set_auth_token()", DeprecationWarning)
        self.set_auth_token(token)

    def set_auth_token(self, token: str, type: str = "Bearer") -> None:
        self.session.headers["Authorization"] = f"{type} {token}"

    def set_auth_basic(self, username: str, password: str) -> None:
        requests.auth.HTTPBasicAuth(username, password)(self.session)

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> SyncHTTPClient:
        return self

    def __exit__(
        self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]
    ) -> None:
        self.close()

    @contextmanager
    def timeout(self, timeout: Timeout) -> Generator[None, None, None]:
        """
        A handy context manager to temporary set timeout values for the following request.
        Useful when you don't want to expose timeout args to all methods of your high-level client.
        For example::

            @dataclass
            HighLevelClient:
                client: SyncHTTPClient

                def ping(self) -> None:
                    self.client.get("/ping")

            # Now let's use it:
            hl = HighLevelClient(client=SyncHTTPClient(...))
            with hl.client.timeout(Timeout(total=10)):
                hl.ping()
        """

        token = c._timeout_ctx.set(timeout)
        try:
            yield
        finally:
            c._timeout_ctx.reset(token)

    def get(
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
        return self._request(
            self.session.get, url, query_params=query_params, response_type=response_type, timeout=timeout
        )

    def post(
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
        return self._request(
            self.session.post, url, body=body, query_params=query_params, response_type=response_type, timeout=timeout
        )

    def put(
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
        return self._request(
            self.session.put, url, body=body, query_params=query_params, response_type=response_type, timeout=timeout
        )

    def delete(
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
        return self._request(
            self.session.delete, url, body=body, query_params=query_params, response_type=response_type, timeout=timeout
        )

    def _request(
        self,
        # The best we can do: https://github.com/python/mypy/issues/5876
        method: Callable[..., requests.Response],
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

        with ExitStack() as cleanup:

            if isinstance(body, UploadFile):
                req_kwargs.update(cleanup.enter_context(self._body_to_upload_args(cast(UploadFile, body)),),)
            else:
                req_kwargs.update(c.body_to_payload_args(body))

            # Generally with requests once method returns, all of the response data
            # is alreardy fetched. Since this method supports **kwargs, it may happen
            # thas stream=True will be passed in which case the above is not true anymore.
            # Hence the context manager.
            # https://2.python-requests.org/en/master/user/advanced/#body-content-workflow
            with method(url, **req_kwargs) as res:
                try:
                    res.raise_for_status()
                except HTTPError as err:
                    err_body = res.text
                    logger.error("Request failed", err=err, err_body=err_body)
                    raise

                if res.status_code == HTTPStatus.NO_CONTENT.value:
                    data = None
                elif c.json_re.match(res.headers["content-type"]) is not None:
                    data = res.json()
                elif issubclass(response_type, bytes):
                    # Special cae for checking response_type for bytes since we can't guess
                    # it from the response itself - some data can be treated as both and it
                    # really depends on what our caller expects
                    data = res.content
                else:
                    data = res.text

                return c.parse_response_data(data, response_type)

    @contextmanager
    def _body_to_upload_args(self, upload: UploadFile) -> dict:
        # requests doesn't guess content-type for form file elements while
        # aiohttp does. Consequently some servers, e.g. aiohttp, will parse
        # this form field just as a string and not as a file which results
        # in a different behavious between aiohttp and requests file uploads.
        #
        # Retrofiting aiohttp behaviour to requests

        files = upload.prepare()
        fp = files[upload.name]

        mimetype, encoding = mimetypes.guess_type(upload.path)
        mimetype = mimetype or upload.default_mimetype
        if encoding:
            mimetype = "; ".join(mimetype, encoding)

        files[upload.name] = (upload.path.name, fp, mimetype)

        yield {"files": files}

        upload.close()

    def _convert_options(self, options: Optional[ClientOptions] = None) -> dict:
        kwargs: Dict[str, Any] = {}
        if not options:
            return kwargs

        if options.ssl_verify_cert is False:
            kwargs["verify"] = False

        if options.timeout:
            kwargs.update(self._convert_timeout(options.timeout))

        return kwargs

    def _convert_timeout(self, timeout: Timeout) -> dict:
        kwargs: Dict[str, Any] = {}
        if isinstance(timeout.total, c._DefaultTimeout):
            if timeout.connect or timeout.read:
                kwargs["timeout"] = (timeout.connect, timeout.read)
            else:
                # Apply default timeout
                kwargs["timeout"] = timeout.total
        else:
            kwargs["timeout"] = timeout.total
        return kwargs


@dataclass
class SyncAPIClientBase:
    """
    Base high-level API client.
    Imlements context-manager boilerplate
    """

    client: SyncHTTPClient

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> SyncAPIClientBase:
        return self

    def __exit__(
        self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]
    ) -> None:
        self.close()
