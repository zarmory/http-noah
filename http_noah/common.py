import re
from contextvars import ContextVar
from dataclasses import dataclass
from io import BufferedReader
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional, Type, TypeVar, Union

import structlog
from pydantic import BaseModel, ValidationError

ResponseType = TypeVar("ResponseType", BaseModel, Type)  # BaseModel or any other class

logger = structlog.get_logger(__name__)
json_re = re.compile(r"^application/(?:[\w.+-]+?\+)?json")


class _DefaultTimeout(int):
    pass


@dataclass
class FormData:
    data: dict


@dataclass
class JSONData:
    data: Union[list, dict]


@dataclass
class UploadFile:
    name: str
    path: Path

    default_mimetype: ClassVar[str] = "application/octet-stream"

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            self.path = Path(self.path)

    def prepare(self) -> Dict[str, BufferedReader]:
        return {self.name: open(self.path, "rb")}


@dataclass
class Timeout:
    total: Optional[float] = _DefaultTimeout(5 * 60)  # To match aiohttp default
    connect: Optional[float] = None
    read: Optional[float] = None


@dataclass
class ClientOptions:
    ssl_verify_cert: bool = True
    timeout: Timeout = Timeout()


OMulti = Optional[Union[BaseModel, FormData, JSONData, UploadFile, str, bytes]]

_timeout_ctx: ContextVar[Optional[Timeout]] = ContextVar("timeout", default=None)


def body_to_payload_args(body: OMulti) -> dict:
    kwargs: Dict[str, Any] = {}
    if isinstance(body, BaseModel):
        kwargs["data"] = body.json().encode()
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        kwargs["headers"]["Content-Type"] = "application/json"
    elif isinstance(body, JSONData):
        kwargs["json"] = body.data
    elif isinstance(body, FormData):
        kwargs["data"] = body.data
    elif isinstance(body, (str, bytes)):
        kwargs["data"] = body
    elif body is not None:
        raise ValueError(f"Unknown body type {type(body)}")

    return kwargs


def parse_response_data(data: Optional[Any], response_type: Optional[Type[ResponseType]],) -> Optional[ResponseType]:

    if response_type is None:
        if data is not None:
            raise TypeError(f"Expected {response_type} response but got {type(data)}: `{data}'")
        else:
            return None

    if issubclass(response_type, BaseModel):
        try:
            return response_type.parse_obj(data)
        except ValidationError as e:
            logger.error(f"Failed to parse {response_type.__name__}", data=data, error=e)
            raise

    if isinstance(data, response_type):
        return data

    logger.error("Type mismatch", response_type=response_type, data_type=type(data), data=data)
    raise TypeError(f"Expected {response_type} but got {type(data)}")
