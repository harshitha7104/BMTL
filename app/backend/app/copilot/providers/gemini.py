"""Google Gemini provider (official `google-genai` SDK, manual function-calling loop)."""
from __future__ import annotations

import logging
from typing import Any, List

from app.copilot.providers.base import ChatProvider, CopilotProviderError, render_turn_text, run_tool_calls
from app.copilot.tools import ToolContext, ToolRegistry
from app.copilot.types import Attachment, ChatTurn, ProviderResult, ToolCallRecord

log = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 8192


class GeminiProvider(ChatProvider):
    name = "gemini"
    display_name = "Google Gemini"

    def __init__(self, api_key: str = "", model: str = "gemini-2.5-pro", client: Any = None):
        self._api_key = api_key
        self._model = model
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return bool(self._client or self._api_key)

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

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
        from google.genai import errors, types

        contents: List[Any] = [
            types.Content(role="model" if t.role == "assistant" else "user", parts=[types.Part(text=render_turn_text(t, ctx.attachments))])
            for t in history
            if t.text
        ]
        parts = [types.Part.from_bytes(data=img.read_bytes(), mime_type=img.content_type) for img in images]
        parts.append(types.Part(text=render_turn_text(user_turn, ctx.attachments)))
        contents.append(types.Content(role="user", parts=parts))

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(name=s.name, description=s.description, parameters_json_schema=s.input_schema)
                        for s in tools.specs
                    ]
                )
            ],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        records: List[ToolCallRecord] = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        text, finish = "", None
        for _ in range(max_rounds):
            try:
                response = await self._get_client().aio.models.generate_content(
                    model=self._model, contents=contents, config=config
                )
            except errors.ClientError as exc:
                raise CopilotProviderError(self.name, f"request rejected ({exc.code}): {exc.message}", retryable=exc.code == 429) from exc
            except errors.ServerError as exc:
                raise CopilotProviderError(self.name, f"server error ({exc.code})", retryable=True) from exc

            meta = getattr(response, "usage_metadata", None)
            if meta:
                usage["input_tokens"] += int(meta.prompt_token_count or 0)
                usage["output_tokens"] += int(meta.candidates_token_count or 0)
            candidate = response.candidates[0] if response.candidates else None
            finish = str(candidate.finish_reason) if candidate and candidate.finish_reason else None

            calls = response.function_calls or []
            if not calls:
                text = response.text or ""
                break

            contents.append(candidate.content)
            round_records = await run_tool_calls(tools, [(c.name, dict(c.args or {})) for c in calls], ctx)
            records.extend(round_records)
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=c.name,
                            response={"error": rec.output} if rec.is_error else {"result": rec.output},
                        )
                        for c, rec in zip(calls, round_records)
                    ],
                )
            )
        else:
            log.warning("Gemini tool loop hit max_rounds=%d", max_rounds)

        if not text:
            text = "I ran the analysis tools but could not produce a final answer within the tool-call limit."
        return ProviderResult(text=text, provider=self.name, model=self._model, tool_calls=records, stop_reason=finish, usage=usage)
