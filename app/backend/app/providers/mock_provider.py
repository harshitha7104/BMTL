"""
Mock AI Provider.

Returns realistic, schema-valid sample assessment data.
Used for development, testing, and demonstration.
Does NOT require any API key or external service.
"""
import random
from typing import List

from app.providers.base import AIProvider
from app.schemas.assessment import (
    AIAnalysisResponse,
    Inference,
    InferenceCategory,
    MaterialFamily,
    Observation,
    ObservationCategory,
    ProposedAssessment,
    ReviewTrigger,
    ScrapForm,
    SurfaceCondition,
    Unknown,
    VisibleContamination,
)
from app.utils.image_utils import ImageData


class MockProvider:
    """
    Mock AI provider for development and testing.
    
    Returns realistic sample data that exercises all schema fields
    and demonstrates the separation of observations/inferences/unknowns.
    
    For deterministic testing, set `force_scenario` to one of:
    - "ferrous_rusted"
    - "non_ferrous_copper"
    - "mixed_material"
    - "electronic_scrap"
    - "low_quality"
    """
    
    # Class-level override for deterministic testing
    force_scenario: str | None = None
    
    @property
    def name(self) -> str:
        return "mock"
    
    @property
    def requires_api_key(self) -> bool:
        return False
    
    async def initialize(self) -> None:
        """No initialization needed for mock provider."""
        pass
    
    async def analyze_images(
        self,
        images: List[ImageData],
        context: str = "",
    ) -> AIAnalysisResponse:
        """
        Generate mock assessment based on image count and context.
        
        Returns realistic sample data that demonstrates:
        - Clear separation of observed/inferred/unknown
        - Appropriate confidence levels
        - Review triggers for edge cases
        - XRF recommendations
        """
        # Select a scenario based on image characteristics
        scenario = self._select_scenario(images, context)
        return scenario
    
    async def is_available(self) -> bool:
        """Mock provider is always available."""
        return True
    
    def get_display_name(self) -> str:
        """Human-readable display name."""
        return "Mock Provider (Development/Test Data)"
    
    def _select_scenario(
        self,
        images: List[ImageData],
        context: str,
    ) -> AIAnalysisResponse:
        """Select a realistic scenario based on inputs."""
        # Check for quality warnings in context
        if "insufficient" in context.lower():
            return self._low_quality_scenario()
        
        # Use forced scenario for deterministic testing
        if MockProvider.force_scenario:
            scenario_type = MockProvider.force_scenario
        else:
            # Vary scenarios for demonstration
            scenario_type = random.choice([
                "ferrous_rusted",
                "non_ferrous_copper",
                "mixed_material",
                "electronic_scrap",
            ])
        
        if scenario_type == "ferrous_rusted":
            return self._ferrous_rusted_scenario()
        elif scenario_type == "non_ferrous_copper":
            return self._non_ferrous_copper_scenario()
        elif scenario_type == "mixed_material":
            return self._mixed_material_scenario()
        elif scenario_type == "low_quality":
            return self._low_quality_scenario()
        else:
            return self._electronic_scrap_scenario()
    
    def _ferrous_rusted_scenario(self) -> AIAnalysisResponse:
        """Scenario: Rusted ferrous material."""
        return AIAnalysisResponse(
            visual_observations=[
                Observation(
                    finding="Dark brown-orange surface discoloration consistent with iron oxide formation",
                    supporting_evidence="Uniform rust coloring visible across approximately 80% of visible surface area",
                    category=ObservationCategory.surface,
                ),
                Observation(
                    finding="Irregular, non-uniform geometry with visible edges and corners",
                    supporting_evidence="Angular shapes visible suggesting cut or broken structural material",
                    category=ObservationCategory.shape,
                ),
                Observation(
                    finding="Dark particulate matter visible in surface crevices",
                    supporting_evidence="Darker deposits in textured areas consistent with soil or environmental contamination",
                    category=ObservationCategory.contamination,
                ),
            ],
            inferred=[
                Inference(
                    finding="Material is likely a ferrous (iron-based) alloy",
                    confidence=0.72,
                    supporting_visual_evidence="Rust pattern and color are characteristic of iron oxidation. Metallic substrate visible in disturbed areas.",
                    limitations="Visual appearance alone cannot distinguish between carbon steel, cast iron, or specific steel alloys. XRF analysis required for grade identification.",
                    category=InferenceCategory.material_family,
                ),
                Inference(
                    finding="Heavy surface rust suggests prolonged outdoor exposure",
                    confidence=0.65,
                    supporting_visual_evidence="Thick, flaking rust pattern with deep orange-brown coloration",
                    limitations="Rust thickness does not directly correlate with exposure duration. Internal material condition cannot be assessed visually.",
                    category=InferenceCategory.condition,
                ),
            ],
            unknown=[
                Unknown(
                    item="Exact alloy composition and grade",
                    reason="Chemical composition cannot be determined from visual inspection",
                    required_evidence="XRF spectroscopy or laboratory chemical analysis",
                ),
                Unknown(
                    item="Internal material condition",
                    reason="Surface rust may mask internal corrosion, cracking, or contamination",
                    required_evidence="Cross-section inspection or ultrasonic testing",
                ),
                Unknown(
                    item="Exact weight and dimensions",
                    reason="Scale reference not provided in image",
                    required_evidence="Physical measurement with calibrated scale",
                ),
            ],
            proposed_assessment=ProposedAssessment(
                material_family=MaterialFamily.ferrous,
                scrap_form=ScrapForm.irregular,
                surface_condition=SurfaceCondition.heavily_rusted,
                visible_contamination=VisibleContamination.dirt_soil,
                description="Ferrous scrap material with heavy surface oxidation. Irregular geometry suggests cut or broken structural component. Visible surface contamination includes soil/dirt deposits.",
                estimated_grade_hint="Possibly carbon steel (unverified)",
                grade_hint_confidence=0.35,
                caveats=[
                    "Material grade cannot be confirmed without spectroscopic analysis",
                    "Surface rust may significantly reduce visible metal recovery",
                    "Contamination level requires physical assessment",
                ],
            ),
            confidence=0.72,
            missing_evidence=[
                "Close-up photograph of material cross-section or edge",
                "Photograph with scale reference (ruler or coin)",
                "Multiple angle photographs showing full geometry",
            ],
            recommended_next_steps=[
                "Perform XRF analysis to determine alloy composition",
                "Conduct physical inspection for internal corrosion",
                "Test for hazardous coatings before processing",
                "Weigh and measure material for volume estimation",
            ],
            scanner_xrf_recommended=True,
            review_triggers=[
                ReviewTrigger.consequential_claim,  # Grade hint provided
            ],
        )
    
    def _non_ferrous_copper_scenario(self) -> AIAnalysisResponse:
        """Scenario: Copper or copper alloy."""
        return AIAnalysisResponse(
            visual_observations=[
                Observation(
                    finding="Yellowish-golden metallic surface with green patina in recessed areas",
                    supporting_evidence="Color characteristics visible across the majority of the surface",
                    category=ObservationCategory.color,
                ),
                Observation(
                    finding="Green-blue discoloration in crevices and joints",
                    supporting_evidence="Characteristic verdigris pattern visible in sheltered areas",
                    category=ObservationCategory.surface,
                ),
            ],
            inferred=[
                Inference(
                    finding="Material is likely a copper or copper alloy (brass/bronze)",
                    confidence=0.68,
                    supporting_visual_evidence="Golden-yellow base color with green patina is characteristic of copper alloys",
                    limitations="Cannot distinguish between pure copper, brass (copper-zinc), or bronze (copper-tin) from appearance alone. Specific alloy grade requires spectroscopic analysis.",
                    category=InferenceCategory.material_family,
                ),
            ],
            unknown=[
                Unknown(
                    item="Specific copper alloy type (pure copper vs brass vs bronze)",
                    reason="Visual color alone cannot reliably distinguish copper alloys",
                    required_evidence="XRF analysis or density measurement",
                ),
                Unknown(
                    item="Alloy grade and purity percentage",
                    reason="Composition cannot be determined visually",
                    required_evidence="Spectroscopic analysis (XRF or OES)",
                ),
            ],
            proposed_assessment=ProposedAssessment(
                material_family=MaterialFamily.non_ferrous,
                scrap_form=ScrapForm.irregular,
                surface_condition=SurfaceCondition.oxidized,
                visible_contamination=VisibleContamination.none_visible,
                description="Non-ferrous metallic scrap with characteristics consistent with copper or copper alloy. Surface shows oxidation with green patina in recessed areas.",
                estimated_grade_hint="Possibly copper alloy (unverified)",
                grade_hint_confidence=0.30,
                caveats=[
                    "Cannot distinguish between copper, brass, and bronze visually",
                    "Alloy composition requires spectroscopic verification",
                ],
            ),
            confidence=0.68,
            missing_evidence=[
                "Close-up photograph showing surface color under neutral lighting",
                "Photograph with scale reference",
            ],
            recommended_next_steps=[
                "Perform XRF analysis to determine exact alloy composition",
                "Conduct density test as preliminary alloy indicator",
            ],
            scanner_xrf_recommended=True,
            review_triggers=[
                ReviewTrigger.consequential_claim,
            ],
        )
    
    def _mixed_material_scenario(self) -> AIAnalysisResponse:
        """Scenario: Mixed material requiring separation."""
        return AIAnalysisResponse(
            visual_observations=[
                Observation(
                    finding="Multiple distinct material types visible in the image",
                    supporting_evidence="Areas of different color, texture, and reflectivity suggest heterogeneous composition",
                    category=ObservationCategory.other,
                ),
                Observation(
                    finding="Possible plastic or rubber components attached to metal",
                    supporting_evidence="Dark flexible-looking material visible at edges and connections",
                    category=ObservationCategory.contamination,
                ),
            ],
            inferred=[
                Inference(
                    finding="Material is a mixed/composite scrap containing multiple material types",
                    confidence=0.55,
                    supporting_visual_evidence="Visual heterogeneity with distinct metallic and non-metallic zones",
                    limitations="Cannot identify all material components or their proportions from visual inspection. Each component requires separate assessment.",
                    category=InferenceCategory.material_family,
                ),
            ],
            unknown=[
                Unknown(
                    item="Exact material composition and proportions",
                    reason="Multiple materials present; cannot quantify from image",
                    required_evidence="Physical separation and individual material identification",
                ),
                Unknown(
                    item="Presence of hazardous materials",
                    reason="Mixed scrap may contain hazardous components not visually identifiable",
                    required_evidence="Laboratory testing of each material component",
                ),
            ],
            proposed_assessment=ProposedAssessment(
                material_family=MaterialFamily.mixed,
                scrap_form=ScrapForm.irregular,
                surface_condition=SurfaceCondition.contaminated,
                visible_contamination=VisibleContamination.plastic,
                description="Mixed material scrap containing both metallic and non-metallic components. Visible plastic/rubber attachments to metal surfaces.",
                estimated_grade_hint=None,
                grade_hint_confidence=0.0,
                caveats=[
                    "Mixed scrap has significantly lower value than sorted materials",
                    "Cannot determine material proportions visually",
                    "Hazardous material presence cannot be ruled out",
                ],
            ),
            confidence=0.55,
            missing_evidence=[
                "Individual close-up photographs of each distinct material type",
                "Photograph showing overall composition and proportions",
            ],
            recommended_next_steps=[
                "Physically separate material types for individual assessment",
                "Screen for hazardous materials before processing",
                "Assess each separated component individually",
            ],
            scanner_xrf_recommended=True,
            review_triggers=[
                ReviewTrigger.mixed_material,
                ReviewTrigger.high_uncertainty,
            ],
        )
    
    def _electronic_scrap_scenario(self) -> AIAnalysisResponse:
        """Scenario: Electronic waste (e-waste)."""
        return AIAnalysisResponse(
            visual_observations=[
                Observation(
                    finding="Green circuit board substrate visible",
                    supporting_evidence="Characteristic FR-4 green PCB material visible in multiple areas",
                    category=ObservationCategory.color,
                ),
                Observation(
                    finding="Metallic components and connectors visible on board",
                    supporting_evidence="Silver and gold-colored components visible on substrate",
                    category=ObservationCategory.surface,
                ),
            ],
            inferred=[
                Inference(
                    finding="Material is electronic scrap (e-waste) containing a printed circuit board",
                    confidence=0.60,
                    supporting_visual_evidence="Green PCB substrate with mounted electronic components is distinctive",
                    limitations="Cannot determine board classification (consumer, industrial, telecommunications) or precious metal content from visual inspection alone.",
                    category=InferenceCategory.material_family,
                ),
            ],
            unknown=[
                Unknown(
                    item="Precious metal content (gold, silver, palladium)",
                    reason="Cannot quantify metal content from visual inspection",
                    required_evidence="Assay or certified e-waste recycling analysis",
                ),
                Unknown(
                    item="Presence of hazardous substances (lead solder, cadmium, beryllium)",
                    reason="Cannot identify hazardous materials visually",
                    required_evidence="XRF testing for RoHS compliance",
                ),
            ],
            proposed_assessment=ProposedAssessment(
                material_family=MaterialFamily.electronic,
                scrap_form=ScrapForm.electronic_component,
                surface_condition=SurfaceCondition.clean,
                visible_contamination=VisibleContamination.none_visible,
                description="Electronic scrap containing printed circuit board with mounted components. Visible IC packages, passive components, and metallic connectors.",
                estimated_grade_hint=None,
                grade_hint_confidence=0.0,
                caveats=[
                    "Precious metal content cannot be estimated from appearance",
                    "Hazardous material testing required before processing",
                    "Data security assessment needed for memory components",
                ],
            ),
            confidence=0.60,
            missing_evidence=[
                "Close-up photograph of connectors and edge fingers",
                "Photograph showing board markings and manufacturer codes",
            ],
            recommended_next_steps=[
                "Classify board grade with e-waste specialist",
                "Test for hazardous substances (RoHS screening)",
                "Assess data security requirements for memory components",
            ],
            scanner_xrf_recommended=True,
            review_triggers=[
                ReviewTrigger.electronic_scrap,
                ReviewTrigger.hazardous_material,
            ],
        )
    
    def _low_quality_scenario(self) -> AIAnalysisResponse:
        """Scenario: Low quality images with limited analysis."""
        return AIAnalysisResponse(
            visual_observations=[
                Observation(
                    finding="Limited visual detail due to image quality constraints",
                    supporting_evidence="Image quality issues prevent detailed surface analysis",
                    category=ObservationCategory.other,
                ),
            ],
            inferred=[
                Inference(
                    finding="Material classification is highly uncertain due to image quality",
                    confidence=0.25,
                    supporting_visual_evidence="Poor image quality limits reliable visual analysis",
                    limitations="Low resolution, poor lighting, or blur prevent accurate material identification. Higher quality images required.",
                    category=InferenceCategory.material_family,
                ),
            ],
            unknown=[
                Unknown(
                    item="Material family",
                    reason="Image quality insufficient for reliable classification",
                    required_evidence="Higher quality photographs with better lighting and focus",
                ),
                Unknown(
                    item="Surface condition",
                    reason="Cannot assess surface details in low quality image",
                    required_evidence="Clear, well-lit photograph of material surface",
                ),
            ],
            proposed_assessment=None,
            confidence=0.25,
            missing_evidence=[
                "Higher resolution photograph",
                "Better lighting conditions",
                "Multiple angles of the material",
                "Close-up of surface details",
            ],
            recommended_next_steps=[
                "Retake photographs with better lighting",
                "Ensure camera is in focus and steady",
                "Include scale reference for size estimation",
            ],
            scanner_xrf_recommended=True,
            review_triggers=[
                ReviewTrigger.low_quality_images,
                ReviewTrigger.insufficient_evidence,
                ReviewTrigger.high_uncertainty,
            ],
        )


__all__ = ["MockProvider"]
