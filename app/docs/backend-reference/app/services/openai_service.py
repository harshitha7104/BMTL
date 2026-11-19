"""
OpenAI Service — Multimodal Image Analysis
Handles communication with OpenAI API for visual assessment.
"""
import json
import logging
import time
from typing import List, Optional

import openai
from openai import OpenAI

from app.core.config import settings
from app.schemas.assessment import (
    AIAnalysisResponse,
    Inference,
    Observation,
    Unknown,
    ProposedAssessment,
)

logger = logging.getLogger(__name__)

# System prompt that enforces strict evidence-based analysis
SYSTEM_PROMPT = """You are a scrap material assessment specialist analyzing photographs of scrap materials.

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

Return your analysis as valid JSON matching the required schema exactly."""


class OpenAIService:
    """Service for OpenAI multimodal image analysis."""

    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        self.max_retries = 3
        self.timeout = 60  # seconds

    async def analyze_images(
        self,
        image_base64: List[str],
        quality_context: Optional[str] = None,
    ) -> AIAnalysisResponse:
        """
        Analyze images using OpenAI's multimodal capabilities.
        
        Args:
            image_base64: List of base64-encoded images
            quality_context: Additional context from quality analysis
            
        Returns:
            Validated AIAnalysisResponse
            
        Raises:
            OpenAIServiceError: If analysis fails after retries
        """
        # Build user message with images
        content_parts = [
            {
                "type": "text",
                "text": self._build_analysis_prompt(quality_context)
            }
        ]

        for img_b64 in image_base64:
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}",
                    "detail": "high"
                }
            })

        # Retry logic
        last_error = None
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()
                
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": content_parts}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,  # Low temperature for consistency
                    max_tokens=4000,
                    timeout=self.timeout,
                )

                processing_time = int((time.time() - start_time) * 1000)
                
                # Parse response
                raw_content = response.choices[0].message.content
                if not raw_content:
                    raise ValueError("Empty response from model")

                # Validate against schema
                parsed = json.loads(raw_content)
                validated = AIAnalysisResponse(**parsed)

                logger.info(
                    f"AI analysis completed in {processing_time}ms, "
                    f"tokens: {response.usage.total_tokens if response.usage else 'unknown'}"
                )

                return validated

            except openai.APIError as e:
                last_error = e
                logger.warning(
                    f"OpenAI API error (attempt {attempt + 1}/{self.max_retries}): {str(e)}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue

            except openai.APITimeoutError as e:
                last_error = e
                logger.warning(
                    f"OpenAI timeout (attempt {attempt + 1}/{self.max_retries})"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue

            except json.JSONDecodeError as e:
                last_error = e
                logger.error(f"Failed to parse AI response as JSON: {str(e)}")
                # Don't retry JSON parse errors
                break

            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error in AI analysis: {str(e)}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue

        raise OpenAIServiceError(
            f"AI analysis failed after {self.max_retries} attempts: {str(last_error)}"
        )

    def _build_analysis_prompt(self, quality_context: Optional[str] = None) -> str:
        """Build the analysis prompt with optional quality context."""
        prompt = """Analyze the provided scrap material photograph(s) and return a structured JSON assessment.

Your JSON response must include:
{
    "visual_observations": [...],  // Directly visible characteristics
    "inferred": [...],             // Tentative interpretations with confidence
    "unknown": [...],              // Cannot be determined from images
    "proposed_assessment": {...},  // Overall classification
    "missing_evidence": [...],     // What additional evidence is needed
    "recommended_next_steps": [...] // Recommended actions
}
"""
        if quality_context:
            prompt += f"\n\nImage quality context: {quality_context}"

        return prompt


class OpenAIServiceError(Exception):
    """Raised when OpenAI service encounters an unrecoverable error."""
    pass
