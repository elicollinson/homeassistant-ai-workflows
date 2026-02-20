from __future__ import annotations

from typing import Protocol

from server.models import ParsedIntent


class IntentParserProtocol(Protocol):
    """Interface for intent parsers. Implementations can use any LLM backend."""

    def init(self) -> None: ...

    async def parse(self, command: str) -> ParsedIntent: ...


class DeviceControllerProtocol(Protocol):
    """Interface for device controllers. Implementations can target any media device."""

    async def launch(self, bundle_id: str, deep_link: str | None = None) -> str: ...

    async def check_connectivity(self) -> bool: ...
