# Assessment Methodology

## Core Principle: Evidence Hierarchy

The ScrapTrust system maintains a strict hierarchy between what can be **observed**, what can be **inferred**, and what remains **unknown**. This hierarchy is the foundation of the system's trustworthiness.

```
                    CONFIDENCE
                        ▲
                        │
    VERIFIED ───────────┤  ← Human expert confirmation
    (100%)              │     Requires physical testing
                        │
    HIGH CONFIDENCE ────┤  ← Strong visual evidence
    (70-90%)            │     Multiple supporting indicators
                        │
    MODERATE ───────────┤  ← Some visual support
    (40-70%)            │     Limited by image quality
                        │
    LOW ────────────────┤  ← Weak visual support
    (10-40%)            │     Significant uncertainty
                        │
    UNKNOWN ────────────┤  ← Cannot be determined
    (0%)                │     Requires different evidence type
                        │
                        └──────────────────────────►
                         OBSERVED    INFERRED    UNKNOWN
```

## Observation Categories

### 1. OBSERVED — Directly Visible

These are characteristics that can be directly seen in the uploaded photographs. They carry the highest evidentiary weight because they are not subject to interpretation.

**Examples:**
- Surface color and discoloration patterns
- Visible rust, oxidation, or patina
- Physical shape and geometry
- Surface texture (smooth, rough, pitted)
- Visible contamination (dirt, oil, paint)
- Attached non-metallic materials
- Dimensions (if scale reference provided)
- Markings, stamps, or labels

**Rules:**
- Must be supported by specific visual evidence in the image
- Cannot include interpretations or conclusions
- Must describe only what is visible, not what is implied

### 2. INFERRED — Tentative Interpretations

These are interpretations based on observed characteristics. Every inference MUST include:
- A confidence level (0-100%)
- The visual evidence supporting it
- Explicit limitations and what it cannot determine

**Examples:**
- "Material is likely ferrous based on rust pattern" (confidence: 72%)
- "Heavy rust suggests prolonged outdoor exposure" (confidence: 65%)
- "May be structural steel based on visible thickness" (confidence: 40%)

**Rules:**
- Every inference must state its confidence level
- Every inference must cite supporting visual evidence
- Every inference must state its limitations
- No inference can claim certainty
- No inference can determine chemical composition

### 3. UNKNOWN — Cannot Be Determined

These are items of information that the available evidence cannot establish. The system must explicitly identify these rather than leaving gaps that might be filled by assumption.

**Examples:**
- Exact alloy composition (requires XRF/chemical analysis)
- Internal material condition (requires cross-section inspection)
- Precise weight (requires physical measurement)
- Presence of hazardous coatings (requires laboratory testing)
- Market value (requires grade determination + market data)

**Rules:**
- Must be explicitly listed, never omitted
- Must explain WHY it cannot be determined
- Must specify what evidence IS needed
- Must not be filled with guesses or estimates

## Confidence Scoring

### Factors Affecting Confidence

| Factor | Impact | Description |
|--------|--------|-------------|
| Image quality | High | Blurry, dark, or overexposed images reduce confidence |
| Number of angles | Medium | Multiple views increase confidence |
| Scale reference | Medium | Enables size estimation |
| Surface clarity | High | Clean surfaces allow better analysis |
| Material distinctiveness | Medium | Some materials have more distinctive visual signatures |
| Contamination level | Medium | Heavy contamination obscures base material |

### Confidence Levels

- **80-100%**: Strong visual evidence, multiple corroborating indicators, high quality images
- **60-79%**: Good visual evidence with some limitations, acceptable image quality
- **40-59%**: Moderate evidence, significant limitations, or partial image quality issues
- **20-39%**: Weak evidence, major limitations, poor image quality
- **0-19%**: Insufficient evidence — assessment should not be relied upon

### Confidence Reduction Rules

The system automatically reduces confidence when:
1. Image quality is below "sufficient" threshold
2. Only a single viewing angle is available
3. Material is heavily contaminated or obscured
4. Multiple material types are present (mixed scrap)
5. No scale reference is available
6. Lighting conditions are poor

## Material Classification Framework

### Material Families

| Family | Visual Indicators | Verification Required |
|--------|------------------|----------------------|
| Ferrous | Rust (orange-brown), magnetic response, dark metallic | XRF for grade |
| Non-ferrous | Copper (reddish-gold), aluminum (silver-white), zinc (blue-grey) | XRF for alloy |
| Mixed | Multiple distinct materials visible | Physical separation + individual testing |
| Electronic | PCB substrate, IC packages, connectors | Board grading + RoHS testing |
| Plastic | Non-metallic, various colors, lightweight | Polymer identification (FTIR) |
| Hazardous | Cannot be identified visually | ALWAYS requires laboratory testing |

### What Visual Analysis CAN Determine

✅ Material family (broad classification)
✅ General scrap form/shape
✅ Surface condition (rust, oxidation, contamination)
✅ Presence of visible contamination
✅ Approximate size (with scale reference)
✅ Whether material appears homogeneous or mixed

### What Visual Analysis CANNOT Determine

❌ Exact chemical composition
❌ Specific alloy grade
❌ Purity percentage
❌ Internal condition/defects
❌ Weight or density
❌ Market value or price
❌ Presence of hazardous substances
❌ Recovery percentage
❌ Processing requirements

## Human Review Protocol

### Automatic Review Triggers (Qualitative, NOT Numeric)

The system automatically flags assessments for human review based on **qualitative conditions**, not numeric confidence thresholds. Triggers include:

1. **`insufficient_evidence`** — Image quality too poor for reliable analysis
2. **`high_uncertainty`** — Multiple inferences with low confidence (qualitative assessment)
3. **`conflicting_images`** — Uploaded images contradict each other
4. **`consequential_claim`** — Grade/composition hint provided without physical verification
5. **`unsupported_conclusion`** — Inference lacks adequate visual evidence
6. **`hazardous_material`** — Potential safety risk identified
7. **`mixed_material`** — Cannot separate components visually
8. **`electronic_scrap`** — Requires specialized e-waste handling
9. **`low_quality_images`** — Image quality below analysis threshold
10. **`model_refusal`** — AI model refused to analyze (safety/policy)
11. **`schema_validation_failure`** — AI response didn't match expected schema
12. **`processing_error`** — Technical error during analysis

**Important:** A numeric confidence value alone does NOT trigger human review. The system evaluates the qualitative context of the assessment.

### Human Review Process

```
AI Assessment → Flag for Review → Expert Examination → Verified Report
                     │                                      │
                     ├─→ Additional photos requested        ├─→ Corrections recorded
                     ├─→ Physical samples requested         ├─→ Confidence updated
                     └─→ Laboratory tests recommended       └─→ Verification status set
```

### Feedback Storage

Human feedback is stored SEPARATELY from the original AI output:
- Original AI assessment is never modified
- Corrections are stored as a separate feedback record
- Both records are preserved for audit trail
- Feedback can be used for future system improvement (with verification)

## Trust Report Structure

Every trust report includes:

1. **Assessment Identification**
   - Unique assessment ID
   - Timestamp
   - Processing metadata

2. **Evidence Quality Assessment**
   - Quality status and score
   - Specific issues identified
   - Recommendations for improvement

3. **Findings (Three-Category Structure)**
   - OBSERVED — blue section — directly visible
   - INFERRED — amber section — with confidence levels
   - UNKNOWN — red section — explicitly identified gaps

4. **Proposed Assessment (Unverified)**
   - Material family classification
   - Scrap form identification
   - Surface condition assessment
   - Explicit caveats and limitations

5. **Recommended Next Steps**
   - Additional photographs needed
   - Physical tests recommended
   - Laboratory analyses required

6. **Limitations Disclaimer**
   - Always present
   - States what the assessment cannot determine
   - Recommends verification before commercial decisions

## Anti-Hallucination Measures

The system implements multiple layers to prevent AI hallucination:

1. **System Prompt Engineering**
   - Explicit instructions to only describe visible characteristics
   - Prohibition on claiming chemical composition
   - Requirement to state confidence levels
   - Requirement to identify unknowns

2. **Structured Output Validation**
   - Pydantic schema enforcement
   - Controlled vocabulary for classifications
   - Confidence must be numeric 0-1
   - All required fields must be present

3. **Post-Processing Rules**
   - Confidence automatically reduced for low-quality images
   - Human review flag for high-risk categories
   - Caveats automatically added for uncertain findings
   - Unknown items always populated

4. **User Interface Safeguards**
   - Clear visual separation of observation categories
   - Confidence levels prominently displayed
   - Limitations always visible
   - "Unverified" labels on all AI-generated content
