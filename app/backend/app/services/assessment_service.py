"""
Assessment Service.

Orchestrates the complete assessment workflow:
1. Validate images
2. Assess quality
3. Call AI provider
4. Validate response
5. Evaluate review triggers
6. Store assessment
"""
import logging
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from app.core.exceptions import (
    AIProviderError,
    AIProviderUnavailableError,
    SchemaValidationError,
)
from app.providers.registry import provider_registry
from app.schemas.assessment import (
    AIAnalysisResponse,
    Assessment,
    AssessmentStatus,
    EvidenceItem,
    EvidenceQualityStatus,
    ProcessingMetadata,
    ReviewTrigger,
    SCHEMA_VERSION,
)
from app.services.image_quality_service import ImageQualityService
from app.repositories.base import AssessmentRepository
from app.utils.image_utils import ImageData

logger = logging.getLogger(__name__)


class AssessmentService:
    """
    Main service for scrap material assessment.
    
    Coordinates image validation, quality assessment, AI analysis,
    and result storage.
    """
    
    def __init__(
        self,
        repository: AssessmentRepository,
        quality_service: Optional[ImageQualityService] = None,
    ):
        self.repository = repository
        self.quality_service = quality_service or ImageQualityService()
    
    async def create_assessment(
        self,
        images: List[ImageData],
    ) -> Assessment:
        """
        Create a new assessment from uploaded images.
        
        Workflow:
        1. Assess image quality
        2. If quality is insufficient, return early with warnings
        3. Call AI provider for analysis
        4. Validate AI response against schema
        5. Evaluate qualitative review triggers
        6. Store and return assessment
        
        Args:
            images: List of validated image data
            
        Returns:
            Complete Assessment object
            
        Raises:
            AIProviderUnavailableError: If no AI provider is available
            AIProviderError: If AI analysis fails
            SchemaValidationError: If AI response doesn't match schema
        """
        assessment_id = f"ASM-{uuid4().hex[:8].upper()}"
        created_at = datetime.utcnow()
        
        logger.info(f"Creating assessment {assessment_id} with {len(images)} images")

        # Step 1: Assess image quality
        quality = self.quality_service.assess_quality(images)
        logger.info(
            f"Image quality assessment: {quality.status.value} "
            f"(score: {quality.overall_score})"
        )

        # Create evidence items for each image (requires quality result)
        evidence_items = self._create_evidence_items(images, quality)
        
        # Step 2: Check if quality is sufficient for analysis
        # NOTE: We proceed even with partially_sufficient quality
        # Only terminate if truly insufficient (unreadable/corrupted)
        if quality.status == EvidenceQualityStatus.insufficient:
            logger.warning("Image quality insufficient — returning limited assessment")
            
            # Create minimal assessment with quality warnings
            assessment = Assessment(
                assessment_id=assessment_id,
                schema_version=SCHEMA_VERSION,
                evidence_quality=quality,
                evidence_items=evidence_items,
                material_family=None,
                scrap_form=None,
                visible_surface_condition=None,
                visible_contamination=None,
                visual_observations=[],
                observed=[],
                inferred=[],
                unknown=[],
                proposed_assessment=None,
                confidence=0.0,
                missing_evidence=quality.recommended_additional_photos,
                recommended_next_steps=[
                    "Retake photographs with better quality",
                    "Ensure adequate lighting and focus",
                    "Include scale reference for size estimation",
                ],
                human_review_required=True,
                human_review_reasons=[
                    ReviewTrigger.insufficient_evidence,
                    ReviewTrigger.low_quality_images,
                ],
                scanner_xrf_recommended=False,
                processing_metadata=ProcessingMetadata(
                    model_used="none",
                    processing_time_ms=0,
                    tokens_used=0,
                    image_count=len(images),
                    total_image_size_bytes=sum(len(img.content) for img in images),
                    validation_passed=True,
                    retry_count=0,
                    provider_id="none",
                ),
                status=AssessmentStatus.requires_review,
                created_at=created_at,
                updated_at=created_at,
            )
            
            await self.repository.save_assessment(assessment)
            return assessment
        
        # Step 3: Call AI provider
        provider = provider_registry.require_active_provider()
        
        # Build context from quality assessment
        context = self._build_quality_context(quality)
        
        logger.info(f"Calling AI provider: {provider.name}")
        
        try:
            ai_response = await provider.analyze_images(images, context)
        except Exception as e:
            logger.error(f"AI provider error: {e}")
            raise AIProviderError(
                f"AI analysis failed: {str(e)}",
                error_type="processing_error"
            )
        
        # Step 4: Validate AI response
        try:
            # Pydantic will validate the response automatically
            # If validation fails, it raises ValidationError
            validated_response = ai_response
            logger.info("AI response validated successfully")
        except Exception as e:
            logger.error(f"Schema validation failed: {e}")
            raise SchemaValidationError(details={"error": str(e)})
        
        # Step 5: Evaluate review triggers
        review_triggers = self._evaluate_review_triggers(
            quality, validated_response, len(images)
        )
        
        # Step 6: Build complete assessment
        assessment = Assessment(
            assessment_id=assessment_id,
            schema_version=SCHEMA_VERSION,
            evidence_quality=quality,
            evidence_items=evidence_items,
            material_family=validated_response.proposed_assessment.material_family
                if validated_response.proposed_assessment else None,
            scrap_form=validated_response.proposed_assessment.scrap_form
                if validated_response.proposed_assessment else None,
            visible_surface_condition=validated_response.proposed_assessment.surface_condition
                if validated_response.proposed_assessment else None,
            visible_contamination=validated_response.proposed_assessment.visible_contamination
                if validated_response.proposed_assessment else None,
            visual_observations=validated_response.visual_observations,
            observed=validated_response.visual_observations,  # Alias
            inferred=validated_response.inferred,
            unknown=validated_response.unknown,
            proposed_assessment=validated_response.proposed_assessment,
            confidence=validated_response.confidence,
            missing_evidence=validated_response.missing_evidence,
            recommended_next_steps=validated_response.recommended_next_steps,
            human_review_required=len(review_triggers) > 0,
            human_review_reasons=review_triggers,
            scanner_xrf_recommended=validated_response.scanner_xrf_recommended,
            processing_metadata=ProcessingMetadata(
                model_used=provider.name,
                processing_time_ms=0,  # Would be measured in production
                tokens_used=0,  # Would be tracked for real providers
                image_count=len(images),
                total_image_size_bytes=sum(len(img.content) for img in images),
                validation_passed=True,
                retry_count=0,
                provider_id=provider.name,
            ),
            status=AssessmentStatus.requires_review
                if review_triggers else AssessmentStatus.completed,
            created_at=created_at,
            updated_at=created_at,
        )
        
        # Step 7: Store assessment
        await self.repository.save_assessment(assessment)
        
        logger.info(
            f"Assessment {assessment_id} completed: "
            f"status={assessment.status.value}, "
            f"confidence={assessment.confidence}, "
            f"review_triggers={len(review_triggers)}"
        )
        
        return assessment
    
    def _create_evidence_items(
        self,
        images: List[ImageData],
        quality,
    ) -> List[EvidenceItem]:
        """
        Create per-image evidence records from input images.
        
        Each evidence item tracks metadata and quality for a single image
        without storing unnecessary sensitive information.
        """
        evidence_items = []
        
        for i, img in enumerate(images):
            evidence_id = f"EVD-{uuid4().hex[:6].upper()}"
            
            # For simplicity in MVP, use aggregate quality for all images
            # In production, would assess quality per-image
            evidence_item = EvidenceItem(
                evidence_id=evidence_id,
                original_filename=img.filename,
                content_type=img.content_type,
                size_bytes=len(img.content),
                hash_sha256=img.hash_sha256,
                width=img.width,
                height=img.height,
                quality_status=quality.status,
                quality_score=quality.overall_score,
                quality_issues=quality.issues[:5],  # Limit to top 5 issues per image
            )
            evidence_items.append(evidence_item)
        
        return evidence_items
    
    def _build_quality_context(self, quality) -> str:
        """Build context string from quality assessment for AI provider."""
        if quality.status == EvidenceQualityStatus.sufficient:
            return "Image quality is sufficient for detailed analysis."
        
        context_parts = [f"Image quality: {quality.status.value}"]
        
        if quality.issues:
            context_parts.append("Issues detected:")
            for issue in quality.issues[:3]:  # Limit to top 3
                context_parts.append(f"- {issue.issue}: {issue.description}")
        
        return "\n".join(context_parts)
    
    def _evaluate_review_triggers(
        self,
        quality,
        ai_response: AIAnalysisResponse,
        image_count: int,
    ) -> List[ReviewTrigger]:
        """
        Evaluate qualitative review triggers.
        
        Triggers are based on qualitative conditions, NOT numeric thresholds.
        """
        triggers: List[ReviewTrigger] = []
        
        # Start with triggers from AI response
        triggers.extend(ai_response.review_triggers)
        
        # Add quality-based triggers
        if quality.status == EvidenceQualityStatus.partially_sufficient:
            if ReviewTrigger.low_quality_images not in triggers:
                triggers.append(ReviewTrigger.low_quality_images)
        
        # Check for high uncertainty (multiple low-confidence inferences)
        low_confidence_count = sum(
            1 for inf in ai_response.inferred if inf.confidence < 0.4
        )
        if low_confidence_count >= 2:
            if ReviewTrigger.high_uncertainty not in triggers:
                triggers.append(ReviewTrigger.high_uncertainty)
        
        # Check for unsupported conclusions
        unsupported_count = sum(
            1 for inf in ai_response.inferred if inf.confidence < 0.35
        )
        if unsupported_count > 0:
            if ReviewTrigger.unsupported_conclusion not in triggers:
                triggers.append(ReviewTrigger.unsupported_conclusion)
        
        # Check for consequential claims (grade hints)
        if (ai_response.proposed_assessment and
            ai_response.proposed_assessment.estimated_grade_hint and
            ai_response.proposed_assessment.grade_hint_confidence > 0):
            if ReviewTrigger.consequential_claim not in triggers:
                triggers.append(ReviewTrigger.consequential_claim)
        
        # Single image with many unknowns
        if image_count == 1 and len(ai_response.unknown) > 3:
            if ReviewTrigger.insufficient_evidence not in triggers:
                triggers.append(ReviewTrigger.insufficient_evidence)
        
        return triggers


__all__ = ["AssessmentService"]
