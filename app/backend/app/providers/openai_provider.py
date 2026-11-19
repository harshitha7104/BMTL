"""
OpenAI AI Provider (OPTIONAL).

This provider integrates with OpenAI's API for multimodal image analysis.
It is OPTIONAL and requires:
1. OPENAI_API_KEY environment variable
2. openai Python package installed

IMPORTANT:
- This provider makes PAID API calls to OpenAI
- Do not enable without proper budget and API key
- Model is configurable via OPENAI_MODEL environment variable
- All responses are validated against Pydantic schemas
- No API keys are logged or exposed to clients

Status: DOCUMENTED BUT NOT TESTED
This implementation follows the OpenAI API specification but has not been
tested with actual API calls. Use at your own risk and verify behavior
before production deployment.
"""
import logging
import time
from typing import List, Optional

from app.core.config import settings
from app.core.exceptions import AIProviderError, SchemaValidationError
from app.providers.base import AIProvider
from app.schemas.assessment import AIAnalysisResponse, ReviewTrigger
from app.utils.image_utils import ImageData

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """
    OpenAI AI provider for multimodal image analysis.
    
    Uses OpenAI's GPT-4o (or configured model) with vision capabilities
    to analyze scrap material images and return structured assessments.
    
    REQUIREMENTS:
    - openai Python package: pip install openai
    - OPENAI_API_KEY environment variable
    - Sufficient API credits for vision API calls
    
    WARNING:
    - This provider makes PAID API calls
    - Costs vary by image size and model
    - Monitor usage to avoid unexpected charges
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        timeout: int = 60,
        max_retries: int = 3,
    ):
        """
        Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key
            model: Model name (default: gpt-4o)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
        """
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = None
    
    @property
    def name(self) -> str:
        return "openai"
    
    @property
    def requires_api_key(self) -> bool:
        return True
    
    def get_display_name(self) -> str:
        """Human-readable display name."""
        return f"OpenAI {self.model} (Vision)"
    
    async def initialize(self) -> None:
        """
        Initialize OpenAI client.
        
        Raises:
            AIProviderError: If openai package not installed or client init fails
        """
        try:
            # Import here to avoid requiring openai package if not used
            from openai import AsyncOpenAI
            
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
            
            logger.info(f"OpenAI client initialized with model: {self.model}")
            
        except ImportError:
            logger.error(
                "OpenAI package not installed. Install with: pip install openai"
            )
            raise AIProviderError(
                "OpenAI package not installed",
                error_type="provider_unavailable"
            )
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise AIProviderError(
                f"Failed to initialize OpenAI client: {str(e)}",
                error_type="provider_unavailable"
            )
    
    async def analyze_images(
        self,
        images: List[ImageData],
        context: str = "",
    ) -> AIAnalysisResponse:
        """
        Analyze images using OpenAI vision API.
        
        Args:
            images: List of validated image data
            context: Additional context (e.g., quality warnings)
            
        Returns:
            AIAnalysisResponse with structured assessment
            
        Raises:
            AIProviderError: If API call fails
            SchemaValidationError: If response doesn't match schema
        """
        if not self._client:
            raise AIProviderError(
                "OpenAI client not initialized",
                error_type="provider_unavailable"
            )
        
        # Build system prompt
        system_prompt = self._build_system_prompt()
        
        # Build user message with images
        user_content = self._build_user_content(images, context)
        
        logger.info(f"Calling OpenAI API with {len(images)} images")
        start_time = time.time()
        
        try:
            # Call OpenAI API
            # NOTE: This implementation uses the Chat Completions API
            # For production, consider using the Responses API with structured outputs
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,  # Lower temperature for consistency
                max_tokens=4000,
            )
            
            processing_time = int((time.time() - start_time) * 1000)
            
            # Extract response content
            content = response.choices[0].message.content
            if not content:
                raise AIProviderError(
                    "Empty response from OpenAI API",
                    error_type="processing_error"
                )
            
            # Parse JSON response
            # NOTE: In production, use response_format={"type": "json_object"}
            # and structured outputs for guaranteed schema compliance
            import json
            try:
                response_data = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse OpenAI response as JSON: {e}")
                raise SchemaValidationError(
                    details={"error": "Invalid JSON response from model"}
                )
            
            # Validate against schema
            try:
                ai_response = AIAnalysisResponse(**response_data)
            except Exception as e:
                logger.error(f"Schema validation failed: {e}")
                raise SchemaValidationError(
                    details={"error": str(e), "raw_response": content[:500]}
                )
            
            logger.info(
                f"OpenAI analysis completed in {processing_time}ms, "
                f"tokens: {response.usage.total_tokens if response.usage else 'unknown'}"
            )
            
            return ai_response
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise AIProviderError(
                f"OpenAI API call failed: {str(e)}",
                error_type="processing_error"
            )
    
    async def is_available(self) -> bool:
        """Check if OpenAI client is initialized."""
        return self._client is not None
    
    def _build_system_prompt(self) -> str:
        """
        Build system prompt for scrap material analysis.
        
        This prompt enforces:
        - Separation of observations, inferences, and unknowns
        - Confidence levels for all inferences
        - No claims about exact composition/grade/purity
        - Explicit identification of limitations
        """
        return """You are a scrap material assessment specialist analyzing photographs of scrap materials.

CRITICAL RULES:
1. You can ONLY describe what is visually observable in the provided images.
2. You MUST separate your analysis into three categories:
   - OBSERVED: Things you can directly see (color, shape, texture, surface condition)
   - INFERRED: Tentative interpretations with explicit confidence levels and limitations
   - UNKNOWN: Things that CANNOT be determined from photographs alone

3. You MUST NEVER:
   - Claim exact chemical composition from appearance
   - State a specific alloy grade without spectroscopic verification
   - Provide pricing or market value estimates
   - Claim to know weight, purity, or internal condition
   - Make definitive statements about material properties

4. Every inference MUST include:
   - A confidence level (0.0 to 1.0)
   - The visual evidence supporting it
   - Explicit limitations of the inference

5. You MUST identify items that are UNKNOWN and explain:
   - What cannot be determined
   - Why it cannot be determined from images
   - What evidence would be needed

6. If the image quality is poor, reduce confidence accordingly and recommend better photographs.

7. Always recommend physical testing (XRF, laboratory analysis) for material identification.

Return your analysis as valid JSON matching this schema:
{
  "visual_observations": [
    {
      "finding": "string",
      "supporting_evidence": "string",
      "category": "surface|shape|color|texture|contamination|other"
    }
  ],
  "inferred": [
    {
      "finding": "string",
      "confidence": 0.0-1.0,
      "supporting_visual_evidence": "string",
      "limitations": "string",
      "category": "material_family|scrap_form|condition|contamination|other"
    }
  ],
  "unknown": [
    {
      "item": "string",
      "reason": "string",
      "required_evidence": "string"
    }
  ],
  "proposed_assessment": {
    "material_family": "ferrous|non_ferrous|mixed|electronic|plastic|organic|hazardous|unidentifiable",
    "scrap_form": "sheet|bar|pipe|wire|turning|casting|forging|machined_part|electronic_component|fragment|irregular|unidentifiable",
    "surface_condition": "clean|lightly_rusted|heavily_rusted|painted|coated|oxidized|contaminated|corroded|unidentifiable",
    "visible_contamination": "none_visible|oil_grease|dirt_soil|paint|rubber|plastic|concrete|organic|chemical_residue|unknown",
    "description": "string",
    "estimated_grade_hint": "string or null",
    "grade_hint_confidence": 0.0-1.0,
    "caveats": ["string"]
  },
  "confidence": 0.0-1.0,
  "missing_evidence": ["string"],
  "recommended_next_steps": ["string"],
  "scanner_xrf_recommended": true/false,
  "review_triggers": ["insufficient_evidence|high_uncertainty|conflicting_images|consequential_claim|unsupported_conclusion|hazardous_material|mixed_material|electronic_scrap|low_quality_images|model_refusal|schema_validation_failure|processing_error"]
}"""
    
    def _build_user_content(
        self,
        images: List[ImageData],
        context: str,
    ) -> List[dict]:
        """
        Build user message content with images.
        
        Args:
            images: List of image data
            context: Additional context
            
        Returns:
            List of content parts for OpenAI API
        """
        import base64
        
        content_parts = []
        
        # Add context if provided
        if context:
            content_parts.append({
                "type": "text",
                "text": f"Image quality context: {context}"
            })
        
        # Add instruction
        content_parts.append({
            "type": "text",
            "text": "Analyze the provided scrap material photograph(s) and return a structured JSON assessment following the schema in the system prompt."
        })
        
        # Add images
        for img_data in images:
            # Convert image to base64
            img_base64 = base64.b64encode(img_data.content).decode("utf-8")
            
            # Determine MIME type
            mime_type = img_data.content_type or "image/jpeg"
            
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{img_base64}",
                    "detail": "high"  # Use high detail for better analysis
                }
            })
        
        return content_parts


__all__ = ["OpenAIProvider"]
