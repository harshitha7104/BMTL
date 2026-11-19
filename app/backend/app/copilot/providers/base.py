"""Common interface for copilot chat providers."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List

from app.copilot.tools import ToolContext, ToolRegistry
from app.copilot.types import Attachment, ChatTurn, ProviderResult, ToolCallRecord


class CopilotProviderError(RuntimeError):
    """A provider call failed (auth, rate limit, network, bad request)."""

    def __init__(self, provider: str, message: str, retryable: bool = False) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.retryable = retryable


def render_turn_text(turn: ChatTurn, attachments: Dict[str, Attachment]) -> str:
    """Text of a stored turn: attachment ids (so the model can reference them) plus any
    transcripts or document contents, which the model reads as part of the message."""
    if not turn.attachment_ids:
        return turn.text
    atts = [attachments[a] for a in turn.attachment_ids if a in attachments]
    if not atts:
        return turn.text
    parts = [turn.text, "", "[Attached: " + ", ".join(a.describe() for a in atts) + "]"]
    for att in atts:
        block = att.context_block()
        if block:
            parts += ["", block]
    return "\n".join(parts)


async def run_tool_calls(
    tools: ToolRegistry, calls: List[tuple[str, dict]], ctx: ToolContext
) -> List[ToolCallRecord]:
    """Run the model's tool calls for one round concurrently, preserving order."""
    return list(await asyncio.gather(*(tools.execute(name, args, ctx) for name, args in calls)))


class ChatProvider(ABC):
    name: str = "base"
    display_name: str = "Base"
    supports_vision: bool = True

    @property
    @abstractmethod
    def model(self) -> str: ...

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    async def respond(
        self,
        *,
        system: str,
        history: List[ChatTurn],
        user_turn: ChatTurn,
        images: List[Attachment],
        tools: ToolRegistry,
        ctx: ToolContext,
        max_rounds: int,
    ) -> ProviderResult:
        """Answer one user turn, calling tools as needed."""

    def info(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "model": self.model,
            "configured": self.is_configured(),
            "supports_vision": self.supports_vision,
        }
