"""
AI Provider Registry.

Manages available AI providers and selects the active one based on configuration.
"""
import logging
from typing import Optional

from app.core.config import settings
from app.core.exceptions import AIProviderError, AIProviderUnavailableError
from app.providers.base import AIProvider
from app.providers.mock_provider import MockProvider

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """
    Registry for AI providers.
    
    Manages initialization and selection of the active provider.
    """
    
    def __init__(self):
        self._providers: dict[str, AIProvider] = {}
        self._active_provider: Optional[AIProvider] = None
    
    async def initialize(self, provider_name: str) -> None:
        """
        Initialize the specified provider.
        
        Args:
            provider_name: Name of provider to initialize ("mock", "openai", "local")
            
        Raises:
            AIProviderError: If provider initialization fails
        """
        logger.info(f"Initializing AI provider: {provider_name}")
        
        if provider_name == "mock":
            provider = MockProvider()
            await provider.initialize()
            self._active_provider = provider
            logger.info("Mock provider initialized successfully")
            
        elif provider_name == "openai":
            # OpenAI provider is optional and requires API key
            if not settings.openai_api_key:
                logger.warning(
                    "OpenAI provider requested but no API key configured. "
                    "Falling back to mock provider."
                )
                await self.initialize("mock")
                return
            
            try:
                # Import here to avoid requiring openai package if not used
                from app.providers.openai_provider import OpenAIProvider
                provider = OpenAIProvider(
                    api_key=settings.openai_api_key,
                    model=settings.openai_model,
                )
                await provider.initialize()
                self._active_provider = provider
                logger.info(f"OpenAI provider initialized with model: {settings.openai_model}")
            except ImportError:
                logger.error(
                    "OpenAI package not installed. Install with: pip install openai"
                )
                raise AIProviderError(
                    "OpenAI provider requested but package not installed",
                    error_type="provider_unavailable"
                )
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI provider: {e}")
                raise AIProviderError(
                    f"Failed to initialize OpenAI provider: {str(e)}",
                    error_type="provider_unavailable"
                )
                
        elif provider_name == "local":
            # Local provider requires model files and hardware
            # NOT YET IMPLEMENTED — raise clear error
            raise AIProviderError(
                "Local vision model provider is not yet implemented. "
                "Use AI_PROVIDER=mock or AI_PROVIDER=openai instead.",
                error_type="provider_unavailable"
            )
            
        else:
            # Unknown provider — raise clear error
            raise AIProviderError(
                f"Unknown AI provider '{provider_name}'. "
                f"Supported providers: mock, openai. "
                f"Local provider is not yet implemented.",
                error_type="invalid_configuration"
            )
    
    def get_active_provider(self) -> Optional[AIProvider]:
        """Get the currently active AI provider."""
        return self._active_provider
    
    def require_active_provider(self) -> AIProvider:
        """
        Get the active provider or raise an error.
        
        Raises:
            AIProviderUnavailableError: If no provider is available
        """
        if self._active_provider is None:
            raise AIProviderUnavailableError()
        return self._active_provider


# Global registry instance
provider_registry = ProviderRegistry()


__all__ = ["ProviderRegistry", "provider_registry"]
