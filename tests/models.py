from typing import List

from pydantic import BaseModel


class Pet(BaseModel):
    name: str


class Pets(BaseModel):
    __root__: List[Pet]
