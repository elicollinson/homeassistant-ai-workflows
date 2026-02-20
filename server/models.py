from __future__ import annotations

from pydantic import BaseModel


class ParsedIntent(BaseModel):
    title: str
    app: str | None = None
    content_type: str = "unknown"  # movie, tv, unknown
    action: str = "play"  # play, search, browse


class StreamingOption(BaseModel):
    service: str
    bundle_id: str | None = None
    deep_link: str | None = None
    type: str = "sub"  # sub, rent, buy
    price: float | None = None


class ContentResult(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    overview: str | None = None
    poster: str | None = None
    content_type: str = "movie"
    streaming_options: list[StreamingOption] = []


class WebhookRequest(BaseModel):
    command: str


class WebhookResponse(BaseModel):
    success: bool
    title: str | None = None
    service: str | None = None
    deep_link: str | None = None
    method_used: str | None = None
    message: str | None = None
