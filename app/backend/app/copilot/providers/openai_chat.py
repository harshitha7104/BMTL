"""
OpenAI Chat Completions provider.

Also used for any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, Groq,
OpenRouter, Together, Azure-compatible proxies) by setting a base URL.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, List, Optional

from app.copilot.providers.base import ChatProvider, CopilotProviderError, render_turn_text, run_tool_calls
from app.copilot.tools import ToolContext, ToolRegistry, serialize_tool_output
from app.copilot.types import Attachment, ChatTurn, ProviderResult, ToolCallRecord

log = logging.getLogger(__name__)

# reasoning models served locally (Qwen3, DeepSeek-R1) may put their hidden reasoning inside the answer
THINK = re.compile(r"<think>.*?(</think>|$)", re.S | re.I)


class OpenAIChatProvider(ChatProvider):
    def __init__(
        self,
        name: str = "openai",
        display_name: str = "OpenAI",
        api_key: str = "",
        model: str = "gpt-4o",
        base_url: Optional[str] = None,
        require_key: bool = True,
        client: Any = None,
        supports_vision: bool = True,
    ):
        self.name = name
        self.display_name = display_name
        self._api_key = api_key
        self._model = model
        self._base_url = base_url or None
        self._require_key = require_key
        self._client = client
        self.supports_vision = supports_vision

    @property
    def model(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        if self._client is not None:
            return True
        if not self._model:
            return False
        if self._require_key:
            return bool(self._api_key)
        return bool(self._base_url)

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            # Local servers such as Ollama ignore the key but the SDK requires a value.
            self._client = AsyncOpenAI(api_key=self._api_key or "not-needed", base_url=self._base_url)
        return self._client

    @staticmethod
    def _tool_defs(tools: ToolRegistry) -> List[dict]:
        return [
            {"type": "function", "function": {"name": s.name, "description": s.description, "parameters": s.input_schema}}
            for s in tools.specs
        ]

    @staticmethod
    def _user_content(text: str, images: List[Attachment]) -> Any:
        if not images:
            return text
        parts: List[dict] = [{"type": "text", "text": text}]
        for img in images:
            b64 = base64.standard_b64encode(img.read_bytes()).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": f"data:{img.content_type};base64,{b64}"}})
        return parts

    async def _create(self, **kwargs):
        import openai

        try:
            return await self._get_client().chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise CopilotProviderError(self.name, "invalid or missing API key") from exc
        except openai.NotFoundError as exc:
            raise CopilotProviderError(self.name, f"model or endpoint not found ({self._model})") from exc
        except openai.RateLimitError as exc:
            raise CopilotProviderError(self.name, "rate limited; retry shortly", retryable=True) from exc
        except openai.BadRequestError as exc:
            raise CopilotProviderError(self.name, f"bad request: {exc.message}") from exc
        except openai.APIStatusError as exc:
            raise CopilotProviderError(
                self.name, f"API error {exc.status_code}: {exc.message}", retryable=exc.status_code >= 500
            ) from exc
        except openai.APIConnectionError as exc:
            raise CopilotProviderError(self.name, f"network error reaching {self._base_url or 'OpenAI'}", retryable=True) from exc

    async def revise(self, *, system: str, draft: str, evidence: List[dict], instruction: str) -> Optional[str]:
        """Answer-checker repair pass (no tools): rewrite the draft so every number traces to the evidence."""
        evidence_text = "\n".join(serialize_tool_output(e.get("output"))[:4000] for e in evidence if e.get("output") is not None)[:24000]
        prompt = f"<tool_results>\n{evidence_text}\n</tool_results>\n\n<draft_answer>\n{draft}\n</draft_answer>\n\n{instruction}"
        try:
            response = await self._create(model=self._model, messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ])
        except CopilotProviderError as exc:
            log.warning("answer-checker repair skipped: %s", exc)
            return None
        text = THINK.sub("", response.choices[0].message.content or "").strip()
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
        messages: List[dict] = [{"role": "system", "content": system}]
        messages += [{"role": t.role, "content": render_turn_text(t, ctx.attachments)} for t in history if t.text]
        messages.append({"role": "user", "content": self._user_content(render_turn_text(user_turn, ctx.attachments), images)})
        tool_defs = self._tool_defs(tools)

        records: List[ToolCallRecord] = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        text, finish, model = "", None, self._model
        for _ in range(max_rounds):
            response = await self._create(model=self._model, messages=messages, tools=tool_defs)
            if getattr(response, "usage", None):
                usage["input_tokens"] += int(response.usage.prompt_tokens or 0)
                usage["output_tokens"] += int(response.usage.completion_tokens or 0)
            model = getattr(response, "model", None) or model
            choice = response.choices[0]
            msg = choice.message
            finish = choice.finish_reason
            if not msg.tool_calls:
                text = THINK.sub("", msg.content or (msg.refusal or "")).strip()
                break

            messages.append(msg.model_dump(exclude_none=True))
            calls = []
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {"_invalid_json": tc.function.arguments}
                calls.append((tc.function.name, args if isinstance(args, dict) else {}))
            round_records = await run_tool_calls(tools, calls, ctx)
            records.extend(round_records)
            for tc, rec in zip(msg.tool_calls, round_records):
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": serialize_tool_output(rec.output)})
        else:
            log.warning("%s tool loop hit max_rounds=%d", self.name, max_rounds)

        if not text:
            text = "I ran the analysis tools but could not produce a final answer within the tool-call limit."
        return ProviderResult(text=text, provider=self.name, model=model, tool_calls=records, stop_reason=finish, usage=usage)
