"""
Image Quality Assessment Service.

Evaluates image quality before AI analysis to determine if images
are sufficient for reliable assessment.
"""
import io
import logging
from typing import List, Tuple

from PIL import Image, ImageStat

from app.schemas.assessment import EvidenceQuality, EvidenceQualityStatus, QualityIssue, IssueSeverity
from app.utils.image_utils import ImageData

logger = logging.getLogger(__name__)


class ImageQualityService:
    """
    Assesses image quality for scrap material analysis.
    
    Evaluates:
    - Resolution (minimum dimensions)
    - Brightness (not too dark or overexposed)
    - Contrast (sufficient detail visibility)
    - Sharpness (not too blurry)
    
    Returns quality status and recommendations.
    """
    
    # Quality thresholds
    MIN_RESOLUTION = (300, 300)  # pixels
    RECOMMENDED_RESOLUTION = (1024, 1024)
    
    BRIGHTNESS_MIN = 0.15  # Too dark
    BRIGHTNESS_MAX = 0.85  # Too bright
    BRIGHTNESS_IDEAL = (0.3, 0.7)
    
    CONTRAST_MIN = 0.1  # Too low contrast
    CONTRAST_IDEAL = 0.3
    
    def assess_quality(self, images: List[ImageData]) -> EvidenceQuality:
        """
        Assess quality of uploaded images.
        
        Args:
            images: List of validated image data
            
        Returns:
            EvidenceQuality with status, issues, and recommendations
        """
        if not images:
            return EvidenceQuality(
                status=EvidenceQualityStatus.insufficient,
                issues=[
                    QualityIssue(
                        issue="no_images",
                        severity=IssueSeverity.critical,
                        description="No images provided for assessment",
                    )
                ],
                recommended_additional_photos=["Upload at least one clear photograph of the material"],
                human_review_required=True,
                overall_score=0,
            )
        
        all_issues: List[QualityIssue] = []
        total_score = 0
        
        for img_data in images:
            issues, score = self._assess_single_image(img_data)
            all_issues.extend(issues)
            total_score += score
        
        avg_score = total_score / len(images)
        
        # Determine overall status
        if avg_score >= 70:
            status = EvidenceQualityStatus.sufficient
        elif avg_score >= 40:
            status = EvidenceQualityStatus.partially_sufficient
        else:
            status = EvidenceQualityStatus.insufficient
        
        # Generate recommendations
        recommendations = self._generate_recommendations(all_issues)
        
        # Determine if human review is required
        has_critical = any(i.severity == IssueSeverity.critical for i in all_issues)
        human_review_required = has_critical or status == EvidenceQualityStatus.insufficient
        
        return EvidenceQuality(
            status=status,
            issues=all_issues[:10],  # Limit to top 10 issues
            recommended_additional_photos=recommendations,
            human_review_required=human_review_required,
            overall_score=int(avg_score),
        )
    
    def _assess_single_image(self, img_data: ImageData) -> Tuple[List[QualityIssue], int]:
        """
        Assess quality of a single image.
        
        Returns:
            Tuple of (issues, score)
        """
        issues: List[QualityIssue] = []
        score = 100
        
        try:
            with Image.open(io.BytesIO(img_data.content)) as img:
                # Convert to RGB if necessary
                if img.mode != "RGB":
                    img = img.convert("RGB")
                
                # Check resolution
                width, height = img.size
                if width < self.MIN_RESOLUTION[0] or height < self.MIN_RESOLUTION[1]:
                    issues.append(QualityIssue(
                        issue="low_resolution",
                        severity=IssueSeverity.high,
                        description=f"Image resolution {width}x{height} is below minimum {self.MIN_RESOLUTION[0]}x{self.MIN_RESOLUTION[1]}",
                    ))
                    score -= 30
                elif width < self.RECOMMENDED_RESOLUTION[0] or height < self.RECOMMENDED_RESOLUTION[1]:
                    issues.append(QualityIssue(
                        issue="moderate_resolution",
                        severity=IssueSeverity.medium,
                        description=f"Image resolution {width}x{height} is below recommended {self.RECOMMENDED_RESOLUTION[0]}x{self.RECOMMENDED_RESOLUTION[1]}",
                    ))
                    score -= 10
                
                # Check brightness
                stat = ImageStat.Stat(img)
                brightness = sum(stat.mean) / (3 * 255)  # Normalize to 0-1
                
                if brightness < self.BRIGHTNESS_MIN:
                    issues.append(QualityIssue(
                        issue="too_dark",
                        severity=IssueSeverity.high,
                        description="Image is too dark for reliable analysis",
                    ))
                    score -= 25
                elif brightness > self.BRIGHTNESS_MAX:
                    issues.append(QualityIssue(
                        issue="overexposed",
                        severity=IssueSeverity.high,
                        description="Image is overexposed, details may be lost",
                    ))
                    score -= 25
                elif not (self.BRIGHTNESS_IDEAL[0] <= brightness <= self.BRIGHTNESS_IDEAL[1]):
                    issues.append(QualityIssue(
                        issue="suboptimal_brightness",
                        severity=IssueSeverity.low,
                        description="Image brightness is outside ideal range",
                    ))
                    score -= 5
                
                # Check contrast (standard deviation)
                contrast = sum(stat.stddev) / (3 * 128)  # Normalize
                
                if contrast < self.CONTRAST_MIN:
                    issues.append(QualityIssue(
                        issue="low_contrast",
                        severity=IssueSeverity.medium,
                        description="Image has low contrast, details may be hard to distinguish",
                    ))
                    score -= 15
                
                # Check sharpness (simple edge detection)
                sharpness = self._estimate_sharpness(img)
                
                if sharpness < 0.1:
                    issues.append(QualityIssue(
                        issue="blurry",
                        severity=IssueSeverity.high,
                        description="Image appears blurry, fine details may be lost",
                    ))
                    score -= 20
                elif sharpness < 0.3:
                    issues.append(QualityIssue(
                        issue="moderate_blur",
                        severity=IssueSeverity.medium,
                        description="Image shows moderate blur",
                    ))
                    score -= 10
        
        except Exception as e:
            logger.error(f"Error assessing image quality: {e}")
            issues.append(QualityIssue(
                issue="analysis_error",
                severity=IssueSeverity.critical,
                description=f"Failed to analyze image quality: {str(e)}",
            ))
            score = 0
        
        return issues, max(0, score)
    
    def _estimate_sharpness(self, img: Image) -> float:
        """
        Estimate image sharpness using edge detection.
        
        Returns:
            Sharpness score (0-1, higher is sharper)
        """
        # Convert to grayscale
        gray = img.convert("L")
        
        # Simple edge detection using pixel differences
        pixels = list(gray.getdata())
        width, height = gray.size
        
        edge_sum = 0
        count = 0
        
        for y in range(1, height - 1):
            for x in range(1, width - 1):
                idx = y * width + x
                center = pixels[idx]
                top = pixels[idx - width]
                bottom = pixels[idx + width]
                left = pixels[idx - 1]
                right = pixels[idx + 1]
                
                # Laplacian edge detection
                edge = abs(4 * center - top - bottom - left - right)
                edge_sum += edge
                count += 1
        
        if count == 0:
            return 0.0
        
        # Normalize to 0-1 range
        sharpness = (edge_sum / count) / 255.0
        return min(1.0, sharpness * 10)  # Scale up for better sensitivity
    
    def _generate_recommendations(self, issues: List[QualityIssue]) -> List[str]:
        """Generate photo recommendations based on detected issues."""
        recommendations = []
        
        issue_types = {i.issue for i in issues}
        
        if "low_resolution" in issue_types or "moderate_resolution" in issue_types:
            recommendations.append("Use a higher resolution camera or move closer to the material")
        
        if "too_dark" in issue_types:
            recommendations.append("Improve lighting — use even, diffused light without harsh shadows")
        
        if "overexposed" in issue_types:
            recommendations.append("Reduce exposure — avoid direct flash or bright sunlight")
        
        if "low_contrast" in issue_types:
            recommendations.append("Ensure adequate lighting contrast to distinguish material features")
        
        if "blurry" in issue_types or "moderate_blur" in issue_types:
            recommendations.append("Hold camera steady and ensure focus is locked on the material")
        
        # General recommendations
        recommendations.append("Include a scale reference (coin or ruler) for size estimation")
        recommendations.append("Capture multiple angles if the material has complex geometry")
        
        return recommendations


__all__ = ["ImageQualityService"]
