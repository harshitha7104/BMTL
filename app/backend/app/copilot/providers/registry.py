"""Builds the copilot providers from settings and resolves which one answers a turn."""
from __future__ import annotations

from typing import Dict, List, Optional

from app.copilot.providers.base import ChatProvider
from app.copilot.providers.claude import ClaudeProvider
from app.copilot.providers.gemini import GeminiProvider
from app.copilot.providers.offline import OfflineProvider
from app.copilot.providers.openai_chat import OpenAIChatProvider

AUTO_ORDER = ["claude", "openai", "gemini", "openai_compatible"]


class UnknownProviderError(ValueError):
    pass


class CopilotProviderRegistry:
    def __init__(self, providers: List[ChatProvider], default: str = "auto") -> None:
        self._providers: Dict[str, ChatProvider] = {p.name: p for p in providers}
        if "offline" not in self._providers:
            self._providers["offline"] = OfflineProvider()
        self.default = default

    @classmethod
    def from_settings(cls, settings, knowledge_base=None) -> "CopilotProviderRegistry":
        return cls(
            [
                ClaudeProvider(settings.anthropic_api_key, settings.anthropic_model, settings.anthropic_effort),
                OpenAIChatProvider("openai", "OpenAI", settings.openai_api_key, settings.openai_model),
                GeminiProvider(settings.gemini_api_key, settings.gemini_model),
                OpenAIChatProvider(
                    "openai_compatible",
                    "OpenAI-compatible endpoint",
                    settings.openai_compatible_api_key,
                    settings.openai_compatible_model,
                    base_url=settings.openai_compatible_base_url,
                    require_key=False,
                    supports_vision=settings.openai_compatible_vision,
                ),
                OfflineProvider(knowledge_base),
            ],
            default=settings.copilot_provider,
        )

    def list(self) -> List[dict]:
        return [p.info() for p in self._providers.values()]

    def default_name(self) -> str:
        if self.default and self.default != "auto":
            return self.default
        for name in AUTO_ORDER:
            p = self._providers.get(name)
            if p and p.is_configured():
                return name
        return "offline"

    def resolve(self, name: Optional[str] = None) -> ChatProvider:
        name = name or self.default_name()
        if name == "auto":
            name = self.default_name()
        provider = self._providers.get(name)
        if provider is None:
            raise UnknownProviderError(f"Unknown provider '{name}'. Options: {', '.join(self._providers)}")
        if not provider.is_configured():
            raise UnknownProviderError(f"Provider '{name}' is not configured (missing API key or model)")
        return provider
