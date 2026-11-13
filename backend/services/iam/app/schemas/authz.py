from __future__ import annotations

from pydantic import BaseModel, Field


class BatchContextsRequest(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=200)
