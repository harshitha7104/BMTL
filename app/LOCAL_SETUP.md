# Local Setup Guide - Scrap AI System

Complete setup instructions for running the Scrap AI system on your local Windows machine.

## 📋 Prerequisites

### Required Software

1. **Python 3.11 or higher**
   - Download from: https://www.python.org/downloads/
   - During installation, check "Add Python to PATH"
   - Verify: `python --version` (should show 3.11.x or higher)

2. **Node.js 18 or higher**
   - Download from: https://nodejs.org/
   - Choose LTS version
   - Verify: `node --version` (should show v18.x or higher)
   - Verify: `npm --version`

3. **Git** (optional, for version control)
   - Download from: https://git-scm.com/download/win

### Hardware Requirements

**Minimum:**
- RAM: 8 GB
- Disk Space: 2 GB free
- CPU: Any modern multi-core processor

**Recommended:**
- RAM: 16 GB or more
- Disk Space: 5 GB free
- GPU: Not required (mock provider works without GPU)

---

## 🚀 Quick Start (Automated)

### Option 1: Use the Startup Script

```powershell
# Open PowerShell in the project root directory
.\start_local.ps1
```

This script will:
- Create Python virtual environment
- Install all dependencies
- Start both backend and frontend
- Open your browser automatically

### Option 2: Manual Setup (Step-by-Step)

Follow the detailed instructions below.

---

## 📦 Installation

### Step 1: Clone or Download the Project

If you have the project files, navigate to the project root:

```powershell
cd C:\path\to\scrap-ai-project
```

### Step 2: Backend Setup

#### 2.1 Navigate to Backend Directory

```powershell
cd backend
```

#### 2.2 Create Python Virtual Environment

```powershell
python -m venv venv
```

#### 2.3 Activate Virtual Environment

```powershell
.\venv\Scripts\Activate.ps1
```

**Note:** If you get an execution policy error, run:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then try activating again.

**Alternative:** Use Command Prompt instead:
```cmd
venv\Scripts\activate.bat
```

#### 2.4 Upgrade pip

```powershell
python -m pip install --upgrade pip
```

#### 2.5 Install Python Dependencies

```powershell
pip install -r requirements.txt
```

This installs:
- FastAPI (web framework)
- Uvicorn (ASGI server)
- Pydantic (data validation)
- Pillow (image processing)
- pytest (testing)
- And other dependencies

**Expected output:** Should complete without errors. If you see errors, check the Troubleshooting section.

#### 2.6 Create Environment Configuration File

```powershell
Copy-Item .env.example .env
```

#### 2.7 Verify Environment Configuration

```powershell
Get-Content .env | Select-String "AI_PROVIDER"
```

**Expected output:**
```
AI_PROVIDER=mock
```

This means the system will use the mock AI provider (no API key required).

### Step 3: Frontend Setup

#### 3.1 Navigate to Project Root

```powershell
cd ..
```

You should be back in the project root directory.

#### 3.2 Install Node.js Dependencies

```powershell
npm install
```

This installs:
- React (UI framework)
- Vite (build tool)
- TypeScript
- Tailwind CSS
- And other dependencies

**Expected output:** Should complete without errors.

---

## ▶️ Running the System

### Starting the Backend

#### Option 1: New PowerShell Window

Open a **new PowerShell window** and run:

```powershell
cd C:\path\to\scrap-ai-project\backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx]
INFO:     Starting ScrapTrust Assessment API v1.0.0-mvp
INFO:     AI Provider: mock
INFO:     Application startup complete.
```

**Keep this window open** - the backend must remain running.

#### Option 2: Same Window (Background)

If you want to run both in the same window:

```powershell
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; .\venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
```

### Starting the Frontend

In your **original PowerShell window** (or a new one):

```powershell
# Make sure you're in the project root
cd C:\path\to\scrap-ai-project

# Start the frontend
npm run dev
```

**Expected output:**
```
VITE v6.x.x  ready in xxx ms

➜  Local:   http://localhost:5173/
➜  Network: use --host to expose
```

### Access the Application

Open your browser and go to:

**Frontend:** http://localhost:5173
**Backend API Docs:** http://localhost:8000/docs
**Backend Health Check:** http://localhost:8000/health

---

## 🧪 Testing the System

### Backend Tests

```powershell
cd backend
.\venv\Scripts\Activate.ps1
pytest tests/ -v
```

**Expected output:** Tests should run and show results.

### Frontend Build Test

```powershell
# In project root
npm run build
```

**Expected output:**
```
vite v6.x.x building for production...
✓ xxx modules transformed.
✓ built in x.xx s
```

### Manual Testing

1. **Upload an Image**
   - Go to http://localhost:5173
   - Click "New Assessment"
   - Upload a scrap material image (JPEG, PNG, or WebP)
   - Wait for processing
   - View the assessment results

2. **View Dashboard**
   - Go to http://localhost:5173
   - See your assessment history
   - Click on an assessment to view details

3. **Submit Feedback**
   - View an assessment
   - Click "Submit Feedback"
   - Fill in the feedback form
   - Submit

4. **Generate Trust Report**
   - View an assessment
   - Click "Trust Report"
   - Print or save the report

---

## 🔧 Configuration

### Environment Variables

Edit `backend/.env` to configure the system:

```env
# AI Provider Selection
AI_PROVIDER=mock              # Options: mock, openai, local

# OpenAI Configuration (only if AI_PROVIDER=openai)
# OPENAI_API_KEY=sk-your-key-here
# OPENAI_MODEL=gpt-4o

# Upload Limits
MAX_UPLOAD_SIZE_MB=10
MAX_IMAGES_PER_ASSESSMENT=5

# Storage
STORAGE_TYPE=local
LOCAL_STORAGE_PATH=./data

# Security
CORS_ORIGINS=["http://localhost:5173"]
```

### AI Provider Options

#### Mock Provider (Default)
- **No API key required**
- Returns sample assessment data
- Perfect for development and testing
- Set: `AI_PROVIDER=mock`

#### OpenAI Provider (Optional)
- Requires OpenAI API key
- Uses GPT-4o for real AI analysis
- Incurs API costs
- Set: `AI_PROVIDER=openai` and provide `OPENAI_API_KEY`

#### Local Provider (Future)
- For local model inference
- Requires significant hardware
- Not yet implemented
- Set: `AI_PROVIDER=local`

---

## 📁 Data Storage

### Backend Data

Assessments are stored in:
```
backend/data/
├── assessments/    # Assessment JSON files
└── feedback/       # Feedback JSON files
```

### Frontend Data

The frontend uses the backend API for all data storage. No local data files.

### Data Directory Structure

The `data/` directory in the project root is for future data infrastructure:
```
data/
├── raw/            # Raw uploaded images
├── processed/      # Processed images
├── images/         # Organized collections
├── documents/      # Reports and documents
├── metadata/       # Assessment metadata
├── annotations/    # Human annotations
├── evaluations/    # Model evaluations
├── knowledge/      # Knowledge base
└── manifests/      # Data manifests
```

---

## 🐛 Troubleshooting

### Backend Issues

#### "Python not found"
- Install Python 3.11+ from https://www.python.org/downloads/
- Check "Add Python to PATH" during installation
- Restart PowerShell after installation

#### "Virtual environment activation fails"
```powershell
# Fix execution policy
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Try again
.\venv\Scripts\Activate.ps1
```

#### "Port 8000 already in use"
```powershell
# Use a different port
uvicorn app.main:app --reload --port 8001
```

Or kill the existing process:
```powershell
# Find process using port 8000
netstat -ano | findstr :8000

# Kill the process (replace PID with actual process ID)
taskkill /PID <PID> /F
```

#### "Module not found" errors
```powershell
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

#### "Import errors"
```powershell
# Check Python version (must be 3.11+)
python --version

# Reinstall all dependencies
pip install -r requirements.txt --upgrade
```

### Frontend Issues

#### "npm not found"
- Install Node.js from https://nodejs.org/
- Restart PowerShell after installation

#### "Port 5173 already in use"
```powershell
# Edit vite.config.js and change port
# Or use:
npm run dev -- --port 5174
```

#### "Module not found" errors
```powershell
# Clear node_modules and reinstall
Remove-Item -Recurse -Force node_modules
npm install
```

#### "Build fails"
```powershell
# Check TypeScript errors
npm run typecheck

# Clear cache and rebuild
Remove-Item -Recurse -Force node_modules
npm install
npm run build
```

### General Issues

#### "Cannot connect to backend"
- Make sure backend is running on port 8000
- Check http://localhost:8000/health in browser
- Verify CORS settings in `backend/.env`

#### "Images won't upload"
- Check file size (max 10MB)
- Check file type (JPEG, PNG, WebP only)
- Check backend logs for errors

#### "Assessment not showing"
- Check browser console for errors
- Check backend logs
- Verify backend is running
- Try refreshing the page

---

## 🛑 Stopping the System

### Stop Backend

In the backend PowerShell window, press:
```
CTRL+C
```

### Stop Frontend

In the frontend PowerShell window, press:
```
CTRL+C
```

### Stop Both (if using startup script)

```powershell
# The startup script will handle cleanup
# Or manually stop both processes
```

---

## 📊 System Status

### Check Backend Health

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health"
```

**Expected output:**
```json
{
  "status": "healthy",
  "version": "1.0.0-mvp",
  "ai_provider": "mock",
  "timestamp": "..."
}
```

### Check Frontend

Open http://localhost:5173 in your browser. The application should load without errors.

---

## 🔒 Security Notes

### API Keys
- **Never commit `.env` file to version control**
- `.env.example` is safe to commit (no real keys)
- Keep your API keys private

### CORS
- Backend is configured to accept requests from `http://localhost:5173`
- For production, update `CORS_ORIGINS` in `.env`

### File Uploads
- Maximum file size: 10MB
- Allowed types: JPEG, PNG, WebP
- Files are validated for corruption
- Safe filename generation prevents path traversal

---

## 📝 Known Limitations

### Current MVP

1. **Mock AI Provider**
   - Returns sample data, not real AI analysis
   - For real analysis, configure OpenAI provider (requires API key and budget)

2. **Local Storage**
   - Uses JSON files for storage
   - Not suitable for production (no concurrency, no indexing)
   - For production, use PostgreSQL

3. **No Authentication**
   - API is open (no user accounts)
   - For production, implement JWT authentication

4. **No Rate Limiting**
   - No protection against abuse
   - For production, implement rate limiting with Redis

5. **No Real AI Model**
   - Mock provider demonstrates the workflow
   - Real AI requires OpenAI API or local model (not yet implemented)

### What Works

✅ Complete frontend application
✅ Complete backend API
✅ Image upload and validation
✅ Image quality assessment
✅ Mock AI assessment
✅ Assessment storage and retrieval
✅ Feedback submission
✅ Trust report generation
✅ Error handling
✅ Type safety (TypeScript + Pydantic)

---

## 🚀 Next Steps

After verifying the system runs locally:

1. **Test with Real Images**
   - Upload actual scrap material photos
   - Verify the workflow works end-to-end

2. **Explore the API**
   - Visit http://localhost:8000/docs
   - Try different API endpoints
   - Understand the data structures

3. **Review the Code**
   - Backend: `backend/app/`
   - Frontend: `src/`
   - Understand the architecture

4. **Plan for Production**
   - Database migration (PostgreSQL)
   - Authentication (JWT)
   - Real AI provider (OpenAI or local model)
   - Cloud storage (S3)
   - Monitoring and logging

5. **Data Acquisition** (Separate Workstream)
   - Collect real scrap material images
   - Label with expert assessments
   - Build training dataset
   - Train custom models

---

## 📞 Support

### Documentation

- `README.md` - Project overview
- `PROJECT_STATUS.md` - Current status
- `docs/architecture.md` - System architecture
- `docs/api.md` - API documentation
- `docs/assessment-methodology.md` - Assessment methodology

### Logs

**Backend logs:** Check the PowerShell window where backend is running
**Frontend logs:** Check browser console (F12)

### Common Commands

```powershell
# Backend
cd backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000

# Frontend
npm run dev

# Tests
cd backend
pytest tests/ -v

# Build
npm run build
```

---

## ✅ Verification Checklist

After setup, verify:

- [ ] Python 3.11+ installed
- [ ] Node.js 18+ installed
- [ ] Backend virtual environment created
- [ ] Backend dependencies installed
- [ ] Backend starts without errors
- [ ] Backend health endpoint responds
- [ ] Frontend dependencies installed
- [ ] Frontend starts without errors
- [ ] Frontend loads in browser
- [ ] Can upload an image
- [ ] Can view assessment results
- [ ] Can submit feedback
- [ ] Can view trust report

---

**Last Updated:** Phase 2F Complete
**Status:** Ready for local execution
**AI Provider:** Mock (no API key required)
