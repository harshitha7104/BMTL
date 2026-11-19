"""
Local file-based repository implementation.

Stores assessments and feedback as JSON files in a local directory.
Suitable for development and testing.
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.repositories.base import AssessmentRepository
from app.schemas.assessment import Assessment, FeedbackRecord

# Security audit N-07: ids become file and folder names. On Windows "..\x" passed the URL route and read files
# outside the data folder, so only plain ids (letters, digits, - and _) are ever turned into paths.
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _safe_id(value: str) -> bool:
    return bool(SAFE_ID.match(value or ""))

logger = logging.getLogger(__name__)


class LocalRepository:
    """
    Local file-based storage using JSON files.
    
    Directory structure:
    data/
    ├── assessments/
    │   ├── ASM-ABC123.json
    │   └── ASM-DEF456.json
    └── feedback/
        ├── ASM-ABC123/
        │   ├── FB-001.json
        │   └── FB-002.json
        └── ASM-DEF456/
            └── FB-001.json
    """
    
    def __init__(self, base_path: str = "./data"):
        self.base_path = Path(base_path)
        self.assessments_path = self.base_path / "assessments"
        self.feedback_path = self.base_path / "feedback"
    
    async def initialize(self) -> None:
        """Create storage directories if they don't exist."""
        self.assessments_path.mkdir(parents=True, exist_ok=True)
        self.feedback_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Local repository initialized at {self.base_path}")
    
    async def close(self) -> None:
        """No cleanup needed for file-based storage."""
        pass
    
    async def save_assessment(self, assessment: Assessment, overwrite: bool = False) -> None:
        """
        Save assessment as JSON file.
        
        IMMUTABILITY: By default, will not overwrite existing assessments.
        Set overwrite=True only for schema migrations or explicit updates.
        
        Args:
            assessment: Assessment to save
            overwrite: If False (default), raises error if assessment already exists
            
        Raises:
            ValueError: If assessment exists and overwrite=False
        """
        if not _safe_id(assessment.assessment_id):
            raise ValueError("invalid assessment id")
        filename = f"{assessment.assessment_id}.json"
        filepath = self.assessments_path / filename
        
        # Immutability check
        if filepath.exists() and not overwrite:
            raise ValueError(
                f"Assessment {assessment.assessment_id} already exists. "
                "Original AI output must not be modified. "
                "Use feedback records for corrections."
            )
        
        # Convert to dict with proper datetime handling
        data = assessment.model_dump(mode="json")
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.debug(f"Saved assessment {assessment.assessment_id} to {filepath}")
    
    async def get_assessment(self, assessment_id: str) -> Optional[Assessment]:
        """Retrieve assessment by ID."""
        if not _safe_id(assessment_id):
            return None
        filename = f"{assessment_id}.json"
        filepath = self.assessments_path / filename
        
        if not filepath.exists():
            return None
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            return Assessment.model_validate(data)
        except Exception as e:
            logger.error(f"Error loading assessment {assessment_id}: {e}")
            return None
    
    async def list_assessments(
        self,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Assessment]:
        """List assessments with pagination."""
        assessments = []
        
        # Get all JSON files
        files = sorted(
            self.assessments_path.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,  # Most recent first
        )
        
        # Apply pagination
        for filepath in files[skip : skip + limit]:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                assessment = Assessment.model_validate(data)
                assessments.append(assessment)
            except Exception as e:
                logger.warning(f"Error loading assessment from {filepath}: {e}")
                continue
        
        return assessments
    
    async def save_feedback(self, feedback: FeedbackRecord) -> None:
        """Save feedback as JSON file in assessment-specific directory."""
        # Create assessment-specific feedback directory
        if not (_safe_id(feedback.assessment_id) and _safe_id(feedback.feedback_id)):
            raise ValueError("invalid assessment or feedback id")
        feedback_dir = self.feedback_path / feedback.assessment_id
        feedback_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{feedback.feedback_id}.json"
        filepath = feedback_dir / filename
        
        # Convert to dict
        data = feedback.model_dump(mode="json")
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.debug(f"Saved feedback {feedback.feedback_id} to {filepath}")
    
    async def get_feedback(
        self,
        assessment_id: str,
    ) -> List[FeedbackRecord]:
        """Get all feedback for an assessment."""
        if not _safe_id(assessment_id):
            return []
        feedback_dir = self.feedback_path / assessment_id
        
        if not feedback_dir.exists():
            return []
        
        feedbacks = []
        
        for filepath in feedback_dir.glob("*.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                feedback = FeedbackRecord.model_validate(data)
                feedbacks.append(feedback)
            except Exception as e:
                logger.warning(f"Error loading feedback from {filepath}: {e}")
                continue
        
        # Sort by submission time
        feedbacks.sort(key=lambda f: f.submitted_at, reverse=True)
        
        return feedbacks


__all__ = ["LocalRepository"]
