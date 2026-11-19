# Scrap AI - Local Startup Script for Windows
# This script sets up and starts both backend and frontend

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Scrap AI - Local Setup & Start" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is installed
Write-Host "Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    if ($pythonVersion -match "Python 3\.1[1-9]") {
        Write-Host "✓ Python found: $pythonVersion" -ForegroundColor Green
    } else {
        Write-Host "✗ Python 3.11+ required. Found: $pythonVersion" -ForegroundColor Red
        Write-Host "Please install Python 3.11+ from https://www.python.org/downloads/" -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host "✗ Python not found. Please install Python 3.11+" -ForegroundColor Red
    Write-Host "Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# Check if Node.js is installed
Write-Host "Checking Node.js installation..." -ForegroundColor Yellow
try {
    $nodeVersion = node --version 2>&1
    if ($nodeVersion -match "v1[8-9]|v[2-9][0-9]") {
        Write-Host "✓ Node.js found: $nodeVersion" -ForegroundColor Green
    } else {
        Write-Host "✗ Node.js 18+ required. Found: $nodeVersion" -ForegroundColor Red
        Write-Host "Please install Node.js 18+ from https://nodejs.org/" -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host "✗ Node.js not found. Please install Node.js 18+" -ForegroundColor Red
    Write-Host "Download from: https://nodejs.org/" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Setting up Backend" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Navigate to backend directory
Set-Location backend

# Create virtual environment if it doesn't exist
if (-Not (Test-Path "venv")) {
    Write-Host "Creating Python virtual environment..." -ForegroundColor Yellow
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ Virtual environment created" -ForegroundColor Green
} else {
    Write-Host "✓ Virtual environment already exists" -ForegroundColor Green
}

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
try {
    & .\venv\Scripts\Activate.ps1
    Write-Host "✓ Virtual environment activated" -ForegroundColor Green
} catch {
    Write-Host "✗ Failed to activate virtual environment" -ForegroundColor Red
    Write-Host "Try running: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser" -ForegroundColor Yellow
    exit 1
}

# Upgrade pip
Write-Host "Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet

# Install dependencies
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
if (Test-Path "requirements.txt") {
    pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ Failed to install dependencies" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "✗ requirements.txt not found" -ForegroundColor Red
    exit 1
}

# Copilot dependencies (LLM SDKs, waste-image index, mineral engine)
if (Test-Path "requirements-copilot.txt") {
    Write-Host "Installing Copilot dependencies..." -ForegroundColor Yellow
    pip install -r requirements-copilot.txt --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ Failed to install Copilot dependencies" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ Copilot dependencies installed" -ForegroundColor Green
}

# Optional: torch + DINOv2 for dataset similarity on new photos (large download).
# CUDA 12.8 wheels when an NVIDIA GPU is present, CPU wheels otherwise.
if (Test-Path "requirements-phase-b.txt") {
    $hasGpu = $null -ne (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
    python -c "import torch" 2>$null
    $torchInstalled = ($LASTEXITCODE -eq 0)
    if (-Not $torchInstalled) {
        Write-Host "Installing torch for DINOv2 photo similarity (large download)..." -ForegroundColor Yellow
        if ($hasGpu) {
            pip install -r requirements-phase-b.txt --extra-index-url https://download.pytorch.org/whl/cu128 --quiet
        } else {
            pip install -r requirements-phase-b.txt --quiet
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "! torch install failed; the Copilot still works without photo similarity" -ForegroundColor Yellow
        } else {
            Write-Host "✓ torch installed" -ForegroundColor Green
        }
    } else {
        Write-Host "✓ torch already installed" -ForegroundColor Green
    }
}

# Create .env file if it doesn't exist
if (-Not (Test-Path ".env")) {
    Write-Host "Creating .env file from .env.example..." -ForegroundColor Yellow
    if (Test-Path ".env.example") {
        Copy-Item .env.example .env
        Write-Host "✓ .env file created" -ForegroundColor Green
    } else {
        Write-Host "⚠ .env.example not found, creating minimal .env" -ForegroundColor Yellow
        @"
AI_PROVIDER=mock
DEBUG=true
LOG_LEVEL=INFO
MAX_UPLOAD_SIZE_MB=10
MAX_IMAGES_PER_ASSESSMENT=5
STORAGE_TYPE=local
LOCAL_STORAGE_PATH=./data
CORS_ORIGINS=["http://localhost:5173"]
"@ | Out-File -FilePath .env -Encoding UTF8
        Write-Host "✓ Minimal .env file created" -ForegroundColor Green
    }
} else {
    Write-Host "✓ .env file already exists" -ForegroundColor Green
}

# Create data directories
Write-Host "Creating data directories..." -ForegroundColor Yellow
if (-Not (Test-Path "data")) {
    New-Item -ItemType Directory -Path "data" -Force | Out-Null
    New-Item -ItemType Directory -Path "data/assessments" -Force | Out-Null
    New-Item -ItemType Directory -Path "data/feedback" -Force | Out-Null
    Write-Host "✓ Data directories created" -ForegroundColor Green
} else {
    Write-Host "✓ Data directories already exist" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Setting up Frontend" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Navigate back to project root
Set-Location ..

# Install frontend dependencies
Write-Host "Installing frontend dependencies..." -ForegroundColor Yellow
if (Test-Path "package.json") {
    npm install --silent
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ Failed to install frontend dependencies" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ Frontend dependencies installed" -ForegroundColor Green
} else {
    Write-Host "✗ package.json not found" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Starting Services" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Start backend in a new window
Write-Host "Starting backend server..." -ForegroundColor Yellow
$backendScript = @'
Set-Location backend
.\venv\Scripts\Activate.ps1
Write-Host "Backend starting on http://localhost:8000" -ForegroundColor Green
Write-Host "API Docs: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
'@

$backendScript | Out-File -FilePath "start_backend.ps1" -Encoding UTF8
Start-Process powershell -ArgumentList "-NoExit", "-File", "start_backend.ps1"

# Wait a moment for backend to start
Write-Host "Waiting for backend to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

# Start frontend
Write-Host "Starting frontend server..." -ForegroundColor Yellow
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  System Ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Frontend: http://localhost:5173" -ForegroundColor Cyan
Write-Host "Backend:  http://localhost:8000" -ForegroundColor Cyan
Write-Host "API Docs: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press CTRL+C to stop the frontend" -ForegroundColor Yellow
Write-Host "Close the backend window to stop the backend" -ForegroundColor Yellow
Write-Host ""

# Open browser
Start-Process "http://localhost:5173"

# Start frontend (this will keep running)
npm run dev
