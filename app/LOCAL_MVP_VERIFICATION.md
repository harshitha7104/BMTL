# Local MVP Verification Checklist

**Purpose:** Step-by-step verification of the ScrapTrust backend in a local Python environment.

**Instructions:** Execute each step in order. Record the actual result (PASS/FAIL/BLOCKED/NOT TESTED) for each item. Do not skip steps. Do not claim a test passed unless you have actually executed it and verified the output.

**Status Legend:**
- ✅ PASS — Test executed successfully with expected output
- ❌ FAIL — Test executed but produced unexpected output or error
- ⚠️ BLOCKED — Test could not be executed due to dependency or environment issue
- ⬜ NOT TESTED — Test has not been executed yet

---

## 1. Python Environment Verification

### 1.1 Python Version Check

**Command (Windows PowerShell):**
```powershell
python --version
```

**Expected Output:**
```
Python 3.11.x or higher
```

**Actual Result:** ⬜ NOT TESTED

**Notes:**
- Minimum required: Python 3.11
- If Python not found, install from https://www.python.org/downloads/
- Ensure "Add Python to PATH" is checked during installation

---

### 1.2 Navigate to Backend Directory

**Command:**
```powershell
cd backend
```

**Expected Output:**
```
(no output, directory changes)
```

**Actual Result:** ⬜ NOT TESTED

---

### 1.3 Create Virtual Environment

**Command:**
```powershell
python -m venv venv
```

**Expected Output:**
```
(no output, creates venv/ directory)
```

**Actual Result:** ⬜ NOT TESTED

**Verification:**
```powershell
Test-Path venv
```
Expected: `True`

---

### 1.4 Activate Virtual Environment

**Command (Windows PowerShell):**
```powershell
.\venv\Scripts\Activate.ps1
```

**Expected Output:**
```
(venv) PS C:\path\to\backend>
```

**Actual Result:** ⬜ NOT TESTED

**Troubleshooting:**
- If execution policy error: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
- Alternative: `.\venv\Scripts\activate.bat`

---

### 1.5 Verify Python in Virtual Environment

**Command:**
```powershell
python --version
```

**Expected Output:**
```
Python 3.11.x (same as system Python)
```

**Actual Result:** ⬜ NOT TESTED

---

### 1.6 Upgrade pip

**Command:**
```powershell
python -m pip install --upgrade pip
```

**Expected Output:**
```
Successfully installed pip-24.x.x
```

**Actual Result:** ⬜ NOT TESTED

---

### 1.7 Install Backend Dependencies

**Command:**
```powershell
pip install -r requirements.txt
```

**Expected Output:**
```
Collecting fastapi==0.115.6
  Downloading fastapi-0.115.6-...
Collecting uvicorn[standard]==0.34.0
  ...
Successfully installed fastapi-0.115.6 uvicorn-0.34.0 pydantic-2.10.4 ...
```

**Actual Result:** ⬜ NOT TESTED

**Verification:**
```powershell
pip list
```

**Expected packages (partial list):**
```
fastapi              0.115.6
uvicorn              0.34.0
pydantic             2.10.4
pydantic-settings    2.7.1
python-multipart     0.0.20
Pillow               11.1.0
python-dotenv        1.0.1
pytest               8.3.4
pytest-asyncio       0.25.0
httpx                0.28.1
```

**Actual Result:** ⬜ NOT TESTED

---

### 1.8 Missing Dependency Detection

**Command:**
```powershell
python -c "import fastapi; import uvicorn; import pydantic; import PIL; print('All dependencies OK')"
```

**Expected Output:**
```
All dependencies OK
```

**Actual Result:** ⬜ NOT TESTED

**If FAIL:**
- Missing package: `pip install <package-name>`
- Version mismatch: Check `requirements.txt` and reinstall

---

## 2. Backend Startup

### 2.1 Create Environment File

**Command:**
```powershell
Copy-Item .env.example .env
```

**Expected Output:**
```
(no output, creates .env file)
```

**Actual Result:** ⬜ NOT TESTED

**Verification:**
```powershell
Test-Path .env
```
Expected: `True`

---

### 2.2 Verify Environment Configuration

**Command:**
```powershell
Get-Content .env | Select-String "AI_PROVIDER"
```

**Expected Output:**
```
AI_PROVIDER=mock
```

**Actual Result:** ⬜ NOT TESTED

**Note:** Default should be `mock` (no API key required)

---

### 2.3 Python Syntax Verification

**Command:**
```powershell
python -m py_compile app/main.py
python -m py_compile app/core/config.py
python -m py_compile app/schemas/assessment.py
python -m py_compile app/services/assessment_service.py
python -m py_compile app/providers/mock_provider.py
```

**Expected Output:**
```
(no output for each command if syntax is correct)
```

**Actual Result:** ⬜ NOT TESTED

**If FAIL:**
- Syntax error in file — check line number in error message
- Import error — verify all imports are present

---

### 2.4 Import Verification

**Command:**
```powershell
python -c "from app.main import app; print('FastAPI app imported successfully')"
```

**Expected Output:**
```
FastAPI app imported successfully
```

**Actual Result:** ⬜ NOT TESTED

**If FAIL:**
- Check import errors in output
- Verify all dependencies installed
- Check for circular imports

---

### 2.5 Start Backend Server

**Command:**
```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Expected Output:**
```
INFO:     Will watch for changes in these directories: C:\path\to\backend
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx]
INFO:     Starting ScrapTrust Assessment API v1.0.0-mvp
INFO:     AI Provider: mock
INFO:     Storage: local
INFO:     Active AI provider: Mock Provider (Development/Test Data)
INFO:     Local repository initialized at ./data
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**Actual Result:** ⬜ NOT TESTED

**Keep this terminal open** — server must remain running for API tests.

**If FAIL:**
- Port 8000 in use: `--port 8001`
- Import error: Check previous step
- Missing dependency: Reinstall requirements.txt

---

### 2.6 Health Endpoint Verification

**Open new PowerShell terminal** (keep server running in first terminal)

**Command:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health" -Method GET
```

**Expected Output:**
```
status      : healthy
version     : 1.0.0-mvp
ai_provider : mock
timestamp   : 2024-01-15T10:30:00.000000
```

**Alternative (curl):**
```powershell
curl http://localhost:8000/health
```

**Expected Output:**
```json
{
  "status": "healthy",
  "version": "1.0.0-mvp",
  "ai_provider": "mock",
  "timestamp": "2024-01-15T10:30:00.000000"
}
```

**Actual Result:** ⬜ NOT TESTED

**If FAIL:**
- Server not running: Check previous step
- Connection refused: Verify port 8000
- Wrong response: Check server logs

---

### 2.7 API Documentation Access

**Command:**
Open browser: `http://localhost:8000/docs`

**Expected Output:**
```
Swagger UI page loads with all endpoints listed:
- GET /health
- POST /api/v1/assessments
- GET /api/v1/assessments/{assessment_id}
- GET /api/v1/assessments
- POST /api/v1/assessments/{assessment_id}/feedback
- GET /api/v1/assessments/{assessment_id}/feedback
```

**Actual Result:** ⬜ NOT TESTED

---

## 3. API Testing

### 3.1 Prepare Test Image

**Create a simple test JPEG image:**

**Command (PowerShell):**
```powershell
# Create a minimal valid JPEG (1x1 white pixel)
$jpegBytes = [byte[]]@(
    0xFF, 0xD8, 0xFF, 0xE0,  # SOI + APP0 marker
    0x00, 0x10,              # APP0 length
    0x4A, 0x46, 0x49, 0x46, 0x00,  # JFIF identifier
    0x01, 0x01,              # Version
    0x00,                    # Aspect ratio units
    0x00, 0x01, 0x00, 0x01,  # X/Y density
    0x00, 0x00,              # Thumbnail dimensions
    0xFF, 0xD9               # EOI
)
[System.IO.File]::WriteAllBytes("test.jpg", $jpegBytes)
```

**Expected Output:**
```
(no output, creates test.jpg)
```

**Verification:**
```powershell
Test-Path test.jpg
```
Expected: `True`

**Actual Result:** ⬜ NOT TESTED

**Note:** This is a minimal JPEG that may be rejected by PIL for being too small. If rejected, use a real JPEG image from your system.

---

### 3.2 Image Upload - Valid Image

**Command:**
```powershell
$form = @{
    images = Get-Item -Path "test.jpg"
}
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/assessments" -Method POST -Form $form
```

**Expected Output:**
```json
{
  "success": true,
  "data": {
    "assessment_id": "ASM-XXXXXXXX",
    "schema_version": "1.0.0",
    "evidence_quality": {
      "status": "sufficient" | "partially_sufficient" | "insufficient",
      "overall_score": <0-100>,
      ...
    },
    "material_family": "ferrous" | "non_ferrous" | "mixed" | "electronic" | ...,
    "confidence": <0.0-1.0>,
    "human_review_required": true | false,
    "human_review_reasons": [...],
    "status": "completed" | "requires_review",
    ...
  },
  "message": "Assessment created successfully"
}
```

**Actual Result:** ⬜ NOT TESTED

**Record:**
- Assessment ID: _______________
- Status: _______________
- Confidence: _______________

---

### 3.3 File Type Validation - Invalid Type

**Create invalid file:**
```powershell
"not an image" | Out-File -FilePath "test.txt" -Encoding ASCII
```

**Command:**
```powershell
$form = @{
    images = Get-Item -Path "test.txt"
}
try {
    Invoke-RestMethod -Uri "http://localhost:8000/api/v1/assessments" -Method POST -Form $form
} catch {
    $_.Exception.Response.StatusCode
    $_.ErrorDetails.Message
}
```

**Expected Output:**
```
StatusCode: 400 (Bad Request)
Error: UNSUPPORTED_FORMAT or CORRUPTED_FILE
Message: File 'test.txt' has unsupported type...
```

**Actual Result:** ⬜ NOT TESTED

---

### 3.4 File Size Validation - Oversized File

**Create oversized file (>10MB):**
```powershell
# Create 11MB file
$fileSize = 11 * 1024 * 1024
$bytes = New-Object byte[] $fileSize
[System.IO.File]::WriteAllBytes("large.jpg", $bytes)
```

**Command:**
```powershell
$form = @{
    images = Get-Item -Path "large.jpg"
}
try {
    Invoke-RestMethod -Uri "http://localhost:8000/api/v1/assessments" -Method POST -Form $form
} catch {
    $_.Exception.Response.StatusCode
    $_.ErrorDetails.Message
}
```

**Expected Output:**
```
StatusCode: 413 (Payload Too Large)
Error: FILE_TOO_LARGE
Message: File 'large.jpg' (...) exceeds maximum size of ... bytes
```

**Actual Result:** ⬜ NOT TESTED

---

### 3.5 Corrupt Image Handling

**Create corrupt file:**
```powershell
[byte[]]@(0xFF, 0xD8, 0xFF, 0x00, 0x00) | Set-Content -Path "corrupt.jpg" -Encoding Byte
```

**Command:**
```powershell
$form = @{
    images = Get-Item -Path "corrupt.jpg"
}
try {
    Invoke-RestMethod -Uri "http://localhost:8000/api/v1/assessments" -Method POST -Form $form
} catch {
    $_.Exception.Response.StatusCode
    $_.ErrorDetails.Message
}
```

**Expected Output:**
```
StatusCode: 400 (Bad Request)
Error: CORRUPTED_FILE
Message: File 'corrupt.jpg' is corrupted or unreadable...
```

**Actual Result:** ⬜ NOT TESTED

---

### 3.6 Mock AI Assessment Verification

**Using assessment from step 3.2:**

**Verify response contains:**
- ✅ `assessment_id` (format: ASM-XXXXXXXX)
- ✅ `schema_version` (value: "1.0.0")
- ✅ `evidence_quality` (object with status, score)
- ✅ `visual_observations` (array)
- ✅ `inferred` (array with confidence, limitations)
- ✅ `unknown` (array with item, reason, required_evidence)
- ✅ `confidence` (0.0-1.0)
- ✅ `human_review_reasons` (array of ReviewTrigger enums)
- ✅ `status` (completed | requires_review)

**Check:**
```powershell
$assessment.assessment_id -match "^ASM-[A-Z0-9]{8}$"
```
Expected: `True`

```powershell
$assessment.confidence -ge 0.0 -and $assessment.confidence -le 1.0
```
Expected: `True`

**Actual Result:** ⬜ NOT TESTED

---

### 3.7 Assessment Schema Validation

**Verify all required fields present:**

**Command:**
```powershell
$requiredFields = @(
    "assessment_id", "schema_version", "evidence_quality",
    "evidence_items", "material_family", "scrap_form",
    "visual_observations", "observed", "inferred", "unknown",
    "confidence", "human_review_required", "human_review_reasons",
    "processing_metadata", "status", "created_at", "updated_at"
)

$missingFields = $requiredFields | Where-Object { $_ -notin $assessment.PSObject.Properties.Name }

if ($missingFields.Count -eq 0) {
    "All required fields present"
} else {
    "Missing fields: $($missingFields -join ', ')"
}
```

**Expected Output:**
```
All required fields present
```

**Actual Result:** ⬜ NOT TESTED

---

### 3.8 Assessment Retrieval

**Command:**
```powershell
$assessmentId = "ASM-XXXXXXXX"  # Use ID from step 3.2
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/assessments/$assessmentId" -Method GET
```

**Expected Output:**
```json
{
  "success": true,
  "data": {
    "assessment_id": "ASM-XXXXXXXX",
    ...
  }
}
```

**Verify:** Response matches original assessment from step 3.2

**Actual Result:** ⬜ NOT TESTED

---

### 3.9 Invalid Assessment ID

**Command:**
```powershell
try {
    Invoke-RestMethod -Uri "http://localhost:8000/api/v1/assessments/ASM-INVALID" -Method GET
} catch {
    $_.Exception.Response.StatusCode
    $_.ErrorDetails.Message
}
```

**Expected Output:**
```
StatusCode: 404 (Not Found)
Error: NOT_FOUND
Message: Assessment 'ASM-INVALID' not found
```

**Actual Result:** ⬜ NOT TESTED

---

### 3.10 Feedback Submission

**Command:**
```powershell
$assessmentId = "ASM-XXXXXXXX"  # Use ID from step 3.2
$body = @{
    reviewer_name = "Test Reviewer"
    feedback_category = "correction"
    corrections = @{
        material_family = "non_ferrous"
        additional_notes = "Actually aluminum, not steel"
    }
    verified = $false
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/v1/assessments/$assessmentId/feedback" -Method POST -Body $body -ContentType "application/json"
```

**Expected Output:**
```json
{
  "success": true,
  "data": {
    "feedback_id": "FB-XXXXXX",
    "assessment_id": "ASM-XXXXXXXX",
    "reviewer_name": "Test Reviewer",
    "feedback_category": "correction",
    "corrections": {
      "material_family": "non_ferrous",
      "additional_notes": "Actually aluminum, not steel"
    },
    "verified": false,
    "verification_status": "unverified",
    "submitted_at": "2024-01-15T10:35:00.000000"
  },
  "message": "Feedback recorded successfully. Original AI output preserved."
}
```

**Record:**
- Feedback ID: _______________

**Actual Result:** ⬜ NOT TESTED

---

### 3.11 Retrieve Feedback

**Command:**
```powershell
$assessmentId = "ASM-XXXXXXXX"
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/assessments/$assessmentId/feedback" -Method GET
```

**Expected Output:**
```json
{
  "success": true,
  "data": [
    {
      "feedback_id": "FB-XXXXXX",
      "assessment_id": "ASM-XXXXXXXX",
      ...
    }
  ],
  "count": 1
}
```

**Actual Result:** ⬜ NOT TESTED

---

## 4. End-to-End Workflow

### 4.1 Complete Workflow Test

**Execute steps in order:**

1. ⬜ Upload image (step 3.2)
   - Assessment ID: _______________
   - Status: _______________

2. ⬜ Validate evidence quality
   - Quality status: _______________
   - Quality score: _______________

3. ⬜ Generate mock assessment
   - Material family: _______________
   - Confidence: _______________

4. ⬜ Validate AI output schema
   - All required fields: _______________

5. ⬜ Store assessment
   - File created: `data/assessments/ASM-XXXXXXXX.json`
   - Verification: `Test-Path data/assessments/ASM-XXXXXXXX.json`

6. ⬜ Retrieve assessment
   - Matches original: _______________

7. ⬜ Display in frontend
   - Start frontend: `npm run dev` (in separate terminal)
   - Open: `http://localhost:5173`
   - Navigate to assessment
   - Displays correctly: _______________

8. ⬜ Submit feedback (step 3.10)
   - Feedback ID: _______________

9. ⬜ Confirm original assessment unchanged
   - Retrieve assessment again
   - Compare with original
   - Unchanged: _______________

10. ⬜ Confirm feedback stored separately
    - Retrieve feedback
    - Feedback exists: _______________
    - Original assessment not modified: _______________

**Actual Result:** ⬜ NOT TESTED

---

## 5. Security Checks

### 5.1 Path Traversal Protection

**Test:** Attempt to access files outside storage directory

**Command:**
```powershell
try {
    Invoke-RestMethod -Uri "http://localhost:8000/api/v1/assessments/..\..\etc\passwd" -Method GET
} catch {
    $_.Exception.Response.StatusCode
}
```

**Expected Output:**
```
StatusCode: 404 (Not Found)
(Should not access system files)
```

**Actual Result:** ⬜ NOT TESTED

---

### 5.2 Safe File Names

**Verify:** Uploaded files are stored with hash-based names

**Command:**
```powershell
Get-ChildItem data/assessments/ | Select-Object Name
```

**Expected Output:**
```
ASM-XXXXXXXX.json
(Format: ASM-[A-Z0-9]{8}.json)
```

**Actual Result:** ⬜ NOT TESTED

---

### 5.3 File Size Limits

**Already tested in step 3.4**

**Verify:** Files >10MB rejected

**Actual Result:** ⬜ NOT TESTED (see step 3.4)

---

### 5.4 CORS Configuration

**Test:** Cross-origin request from different origin

**Command (Browser Console):**
```javascript
fetch('http://localhost:8000/health', {
  method: 'GET',
  headers: {
    'Origin': 'http://evil.com'
  }
})
```

**Expected Output:**
```
Request blocked by CORS policy
OR
Response does not include Access-Control-Allow-Origin header for evil.com
```

**Actual Result:** ⬜ NOT TESTED

---

### 5.5 No Exposed API Keys

**Verify:** No API keys in frontend code

**Command:**
```powershell
# Search for API keys in frontend
Get-ChildItem -Path ..\src -Recurse -Include *.ts,*.tsx | Select-String -Pattern "sk-[a-zA-Z0-9]{20,}"
```

**Expected Output:**
```
(no matches)
```

**Actual Result:** ⬜ NOT TESTED

---

### 5.6 Proper Error Responses

**Verify:** Error messages don't expose stack traces

**Test:** Send invalid request

**Command:**
```powershell
try {
    Invoke-RestMethod -Uri "http://localhost:8000/api/v1/assessments" -Method POST
} catch {
    $_.ErrorDetails.Message
}
```

**Expected Output:**
```json
{
  "success": false,
  "error": "VALIDATION_ERROR",
  "message": "At least one image is required"
}
```

**Verify:** No stack trace, no internal paths, no sensitive data

**Actual Result:** ⬜ NOT TESTED

---

## 6. Test Summary

### Results Table

| Test Category | Total Tests | PASS | FAIL | BLOCKED | NOT TESTED |
|---------------|-------------|------|------|---------|------------|
| Python Environment | 8 | 0 | 0 | 0 | 8 |
| Backend Startup | 7 | 0 | 0 | 0 | 7 |
| API Testing | 11 | 0 | 0 | 0 | 11 |
| End-to-End Workflow | 10 | 0 | 0 | 0 | 10 |
| Security Checks | 6 | 0 | 0 | 0 | 6 |
| **TOTAL** | **42** | **0** | **0** | **0** | **42** |

### Critical Path Tests

These tests must PASS for the system to be considered functional:

1. ⬜ Python environment setup (1.1-1.8)
2. ⬜ Backend startup (2.5)
3. ⬜ Health endpoint (2.6)
4. ⬜ Image upload (3.2)
5. ⬜ Assessment retrieval (3.8)
6. ⬜ Feedback submission (3.10)

**If any critical test FAILS:** System is not functional. Fix before proceeding.

---

## 7. Troubleshooting

### Common Issues

**Issue: Python not found**
- Solution: Install Python 3.11+ from https://www.python.org/downloads/
- Ensure "Add Python to PATH" is checked

**Issue: Virtual environment activation fails**
- Solution: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
- Alternative: Use `activate.bat` instead of `Activate.ps1`

**Issue: Dependencies fail to install**
- Solution: Upgrade pip: `python -m pip install --upgrade pip`
- Check Python version: Must be 3.11+

**Issue: Port 8000 already in use**
- Solution: Use different port: `--port 8001`
- Or kill existing process: `netstat -ano | findstr :8000` then `taskkill /PID <pid> /F`

**Issue: Import errors on startup**
- Solution: Reinstall dependencies: `pip install -r requirements.txt --force-reinstall`

**Issue: CORS errors in frontend**
- Solution: Check `.env` file has correct `CORS_ORIGINS`
- Default: `["http://localhost:3000","http://localhost:5173"]`

**Issue: Assessment not found**
- Solution: Verify assessment ID format: `ASM-[A-Z0-9]{8}`
- Check `data/assessments/` directory for JSON files

---

## 8. Final Verification

### System Status

After completing all tests:

**Backend:**
- ⬜ Starts successfully
- ⬜ Health endpoint responds
- ⬜ Accepts image uploads
- ⬜ Returns valid assessments
- ⬜ Stores assessments
- ⬜ Accepts feedback
- ⬜ Preserves immutability

**Security:**
- ⬜ Path traversal protected
- ⬜ Safe file names
- ⬜ File size limits enforced
- ⬜ CORS configured correctly
- ⬜ No exposed secrets
- ⬜ Safe error messages

**Integration:**
- ⬜ Frontend can connect to backend
- ⬜ End-to-end workflow functional
- ⬜ Mock provider works
- ⬜ Assessment display correct
- ⬜ Feedback submission works

### Overall Status

- ✅ PASS — All critical tests passed
- ❌ FAIL — One or more critical tests failed
- ⚠️ PARTIAL — Some tests passed, others failed or blocked
- ⬜ NOT TESTED — Tests not yet executed

**Final Status:** ⬜ NOT TESTED

---

## 9. Next Steps

### If All Tests PASS

1. ✅ Backend is functional
2. ✅ Proceed to production hardening (authentication, rate limiting, production storage)
3. ✅ Consider OpenAI integration testing (requires budget)
4. ✅ Begin dataset preparation (separate workstream)

### If Tests FAIL

1. ❌ Review failed test output
2. ❌ Check troubleshooting section (section 7)
3. ❌ Fix issues and re-run failed tests
4. ❌ Do not proceed until all critical tests PASS

### If Tests BLOCKED

1. ⚠️ Identify blocking dependency or environment issue
2. ⚠️ Resolve blocker (install missing dependency, fix environment)
3. ⚠️ Re-run blocked tests
4. ⚠️ Do not proceed until all critical tests PASS or are explicitly marked as not required

---

## 10. Sign-Off

**Tester Name:** _______________________________

**Date:** _______________________________

**Environment:**
- OS: _______________________________
- Python Version: _______________________________
- Backend Directory: _______________________________

**Results:**
- Total Tests: 42
- PASS: _____
- FAIL: _____
- BLOCKED: _____
- NOT TESTED: _____

**Overall Status:** ⬜ NOT TESTED

**Notes:**
_______________________________________________
_______________________________________________
_______________________________________________

**Signature:** _______________________________

---

**Document Version:** 1.0
**Last Updated:** Phase 2F Complete
**Status:** Ready for execution
