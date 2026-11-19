# Data Directory Structure

This directory contains all data for the Scrap AI system.

## Structure

```
data/
├── raw/              # Raw uploaded images (before processing)
├── processed/        # Processed images (after quality gate)
├── images/           # Organized image collections
├── documents/        # Supporting documents, reports
├── metadata/         # Assessment metadata, logs
├── annotations/      # Human annotations, corrections
├── evaluations/      # Model evaluation results
├── knowledge/        # Knowledge base, reference data
└── manifests/        # Data manifests, indexes
```

## Usage

- **raw/**: Temporary storage for uploaded images
- **processed/**: Images that passed quality gate
- **images/**: Organized collections by material type
- **documents/**: Generated reports, trust reports
- **metadata/**: Assessment metadata, processing logs
- **annotations/**: Human expert corrections (separate from AI output)
- **evaluations/**: Model performance metrics
- **knowledge/**: Reference data for RAG/knowledge retrieval
- **manifests/**: Data indexes and catalogs

## Important Notes

- This directory is for infrastructure only
- No fake training data is included
- No labels are invented
- Real data acquisition is a separate workstream
- All assessments are stored in backend/data/assessments/
