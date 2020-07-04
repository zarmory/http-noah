import logging
from contextlib import contextmanager
from typing import Any, Generator, Union

import structlog
from pydantic import ValidationError

logger = structlog.get_logger(__name__)


@contextmanager
def validation_error_ctx(
    obj: Any, obj_type: str = "", logger: Union[logging.Logger, structlog.BoundLogger] = logger
) -> Generator[None, None, None]:
    """
    Helper context manager to reduce amount of code like:

    user_info = requests.get(...).json()
    try:
        user = User(**user_info)
    except pydantic.ValidationError:
        logger.error("Failed to parse user info", user_info=user_info)
        raise

    Pydantic produces very nice validation errors, but they do not show the
    original data that failed the validation. Hence we can use this context manager as

    user_info = requests.get(...).json()
    with validation_error_ctx(user_info, "user info"):
        user = User(**user_info)
    """
    try:
        yield
    except ValidationError:
        logger.error(f"Failed to parse {obj_type}", obj=obj)
        raise
