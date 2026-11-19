"""Anthropic Claude provider (official `anthropic` SDK, manual tool-use loop)."""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, List, Optional

from app.copilot.providers.base import ChatProvider, CopilotProviderError, render_turn_text, run_tool_calls
from app.copilot.tools import ToolContext, ToolRegistry, serialize_tool_output
from app.copilot.types import Attachment, ChatTurn, ProviderResult, ToolCallRecord

log = logging.getLogger(__name__)

MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeProvider(ChatProvider):
    name = "claude"
    display_name = "Anthropic Claude"

    def __init__(self, api_key: str = "", model: str = "claude-opus-5-5", effort: str = "medium", client: Any = None):
        self._api_key = api_key
        self._model = model
        self._effort = effort
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return bool(
            self._client
            or self._api_key
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )

    def _get_client(self):
        if self._client is None:
            import anthropic

            # No key -> the SDK resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / `ant auth login` profile.
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key or None)
        return self._client

    @staticmethod
    def _tool_defs(tools: ToolRegistry) -> List[dict]:
        return [{"name": s.name, "description": s.description, "input_schema": s.input_schema} for s in tools.specs]

    @staticmethod
    def _user_content(text: str, images: List[Attachment]) -> List[dict]:
        content: List[dict] = []
        for img in images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.content_type,
                        "data": base64.standard_b64encode(img.read_bytes()).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": text})
        return content

    async def _create(self, **kwargs):
        import anthropic

        try:
            return await self._get_client().beta.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise CopilotProviderError(self.name, "invalid or missing Anthropic API key") from exc
        except anthropic.PermissionDeniedError as exc:
            raise CopilotProviderError(self.name, f"permission denied: {exc.message}") from exc
        except anthropic.NotFoundError as exc:
            raise CopilotProviderError(self.name, f"model or endpoint not found ({self._model})") from exc
        except anthropic.RateLimitError as exc:
            raise CopilotProviderError(self.name, "rate limited; retry shortly", retryable=True) from exc
        except anthropic.BadRequestError as exc:
            raise CopilotProviderError(self.name, f"bad request: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise CopilotProviderError(
                self.name, f"API error {exc.status_code}: {exc.message}", retryable=exc.status_code >= 500
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise CopilotProviderError(self.name, "network error reaching the Anthropic API", retryable=True) from exc

    async def revise(self, *, system: str, draft: str, evidence: List[dict], instruction: str) -> Optional[str]:
        """Answer-checker repair pass: rewrite a draft so every number is traceable to the evidence. No tools."""
        evidence_text = "\n".join(serialize_tool_output(e.get("output"))[:4000] for e in evidence if e.get("output") is not None)[:40000]
        try:
            response = await self._create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                output_config={"effort": self._effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
                messages=[{"role": "user", "content": f"<tool_results>\n{evidence_text}\n</tool_results>\n\n<draft_answer>\n{draft}\n</draft_answer>\n\n{instruction}"}],
            )
        except CopilotProviderError as exc:
            log.warning("answer-checker repair skipped: %s", exc)
            return None
        if response.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        return text or None

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
        messages: List[dict] = [
            {"role": t.role, "content": render_turn_text(t, ctx.attachments)} for t in history if t.text
        ]
        messages.append({"role": "user", "content": self._user_content(render_turn_text(user_turn, ctx.attachments), images)})

        request = dict(
            model=self._model,
            max_tokens=MAX_TOKENS,
            # Frozen system prompt + stable tool list -> cacheable prefix.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=self._tool_defs(tools),
            output_config={"effort": self._effort},
            # On a safety decline the API re-runs the request on a fallback model chosen by refusal category.
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )

        records: List[ToolCallRecord] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
        response = None
        for _ in range(max_rounds):
            response = await self._create(messages=messages, **request)
            for key in usage:
                usage[key] += int(getattr(response.usage, key, 0) or 0)

            if response.stop_reason == "refusal":
                return ProviderResult(
                    text="I can't help with that request.",
                    provider=self.name, model=response.model, tool_calls=records,
                    stop_reason="refusal", usage=usage,
                )

            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                break

            round_records = await run_tool_calls(tools, [(b.name, dict(b.input or {})) for b in tool_uses], ctx)
            records.extend(round_records)
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": serialize_tool_output(rec.output),
                            "is_error": rec.is_error,
                        }
                        for block, rec in zip(tool_uses, round_records)
                    ],
                }
            )
        else:
            log.warning("Claude tool loop hit max_rounds=%d", max_rounds)

        text = "\n\n".join(b.text for b in (response.content if response else []) if b.type == "text").strip()
        stop = response.stop_reason if response else None
        if stop == "max_tokens":
            text += "\n\n_(Response truncated at the output limit.)_"
        if not text:
            text = "I ran the analysis tools but could not produce a final answer within the tool-call limit."
        return ProviderResult(
            text=text,
            provider=self.name,
            model=getattr(response, "model", self._model),
            tool_calls=records,
            stop_reason=stop,
            usage=usage,
        )
