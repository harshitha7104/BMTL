"""
AI Provider Abstraction Layer.

This module defines the interface for AI providers, allowing the system
to work with different backends (mock, OpenAI, local models) without
changing the core assessment logic.
"""
from typing import List, Protocol
from pathlib import Path

from app.schemas.assessment import AIAnalysisResponse, ReviewTrigger
from app.utils.image_utils import ImageData


class AIProvider(Protocol):
    """
    Interface for AI providers.
    
    All providers must implement this protocol to be used by the system.
    """
    
    @property
    def name(self) -> str:
        """Provider name for logging and display."""
        ...
    
    @property
    def requires_api_key(self) -> bool:
        """Whether this provider requires an API key."""
        ...
    
    async def initialize(self) -> None:
        """Initialize the provider (load models, verify credentials, etc.)."""
        ...
    
    async def analyze_images(
        self,
        images: List[ImageData],
        context: str = "",
    ) -> AIAnalysisResponse:
        """
        Analyze images and return structured assessment.
        
        Args:
            images: List of validated image data
            context: Additional context (e.g., quality warnings)
            
        Returns:
            AIAnalysisResponse with observations, inferences, unknowns
            
        Raises:
            AIProviderError: If analysis fails
            SchemaValidationError: If response doesn't match schema
        """
        ...
    
    async def is_available(self) -> bool:
        """Check if the provider is available and ready."""
        ...
    
    def get_display_name(self) -> str:
        """Human-readable display name for the provider."""
        ...


__all__ = ["AIProvider"]
