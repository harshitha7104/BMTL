# ScrapTrust - one-click launcher
# Sets up on first run, rebuilds the web app when sources change, then serves the
# whole product (web app + API + Copilot) from a single local server.
#
#   .\run_scraptrust.ps1              start and open the browser
#   .\run_scraptrust.ps1 -NoBrowser   start without opening a browser
#   .\run_scraptrust.ps1 -Port 8020   preferred port (next free port is used if busy)

param(
    [int]$Port = 8010,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$py = Join-Path $backend "venv\Scripts\python.exe"

function Step($msg) { Write-Host "-> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "   $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "   $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  ScrapTrust - scrap, waste & mineral Copilot" -ForegroundColor White
Write-Host ""

# 1. Python environment -------------------------------------------------------
if (-Not (Test-Path $py)) {
    Step "First run: creating the Python environment (this takes a few minutes)"
    python -m venv (Join-Path $backend "venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create backend\venv. Install Python 3.11+ first." }
    & $py -m pip install --upgrade pip --quiet
    & $py -m pip install -r (Join-Path $backend "requirements.txt") -r (Join-Path $backend "requirements-copilot.txt") --quiet
    if ($LASTEXITCODE -ne 0) { throw "Dependency install failed." }
    $gpu = $null -ne (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
    Step "Installing torch for photo similarity ($(if ($gpu) {'CUDA'} else {'CPU'}) build)"
    if ($gpu) {
        & $py -m pip install -r (Join-Path $backend "requirements-phase-b.txt") --extra-index-url https://download.pytorch.org/whl/cu128 --quiet
    } else {
        & $py -m pip install -r (Join-Path $backend "requirements-phase-b.txt") --quiet
    }
    if ($LASTEXITCODE -ne 0) { Warn "torch install failed - the Copilot works, but without photo similarity." }
}
Ok "Python environment ready"

# 2. Configuration ------------------------------------------------------------
$envFile = Join-Path $backend ".env"
if (-Not (Test-Path $envFile)) {
    Copy-Item (Join-Path $backend ".env.example") $envFile
    Ok "Created backend\.env (add an API key there to enable Claude / OpenAI / Gemini)"
}
# Security: a random SECRET_KEY (signs sign-in cookies). The server refuses to start without one.
$envText = Get-Content $envFile -Raw
$secretLine = [regex]::Match($envText, '(?m)^\s*SECRET_KEY\s*=\s*(.*)$')
$secretVal = if ($secretLine.Success) { $secretLine.Groups[1].Value.Trim() } else { "" }
if ($secretVal.Length -lt 32 -or $secretVal -match '^change-?me') {
    $newSecret = & $py -c "import secrets; print(secrets.token_urlsafe(48))"
    if ($secretLine.Success) {
        $envText = [regex]::Replace($envText, '(?m)^\s*SECRET_KEY\s*=.*$', "SECRET_KEY=$newSecret")
    } else {
        $envText = $envText.TrimEnd() + "`r`nSECRET_KEY=$newSecret`r`n"
    }
    Set-Content -Path $envFile -Value $envText -Encoding utf8 -NoNewline
    Ok "Generated a random SECRET_KEY in backend\.env"
}
$env:HOST_BINDING = "127.0.0.1"
# First run: create the administrator account (no self-registration; more users via scripts\manage_users.py)
$authOff = Select-String -Path $envFile -Pattern '^\s*AUTH_MODE\s*=\s*disabled_local_dev' -Quiet
Push-Location $backend
$userCount = & $py -c "from app.core.security import user_store; print(user_store().count())" 2>$null
Pop-Location
if (-Not $authOff -and -Not $env:USERS_FILE -and "$userCount".Trim() -eq "0") {
    Step "First run: create the administrator account"
    $adminName = Read-Host "  Admin username (letters, digits, . _ - @)"
    Push-Location $backend
    try { & $py scripts\manage_users.py add $adminName --role admin } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "Could not create the admin account." }
    Ok "Admin '$adminName' created. Add colleagues with: backend\venv\Scripts\python.exe backend\scripts\manage_users.py add <name>"
}

$hasKey = Select-String -Path $envFile -Pattern '^\s*(ANTHROPIC_API_KEY|OPENAI_API_KEY|GEMINI_API_KEY|OPENAI_COMPATIBLE_BASE_URL)\s*=\s*\S' -Quiet
if ($hasKey -or $env:ANTHROPIC_API_KEY -or $env:OPENAI_API_KEY -or $env:GEMINI_API_KEY) {
    Ok "LLM provider configured"
} else {
    Ok "Offline mode: models, agents, reports and voice run on this server; no data is sent to any AI service."
}

# 3. Web app build ------------------------------------------------------------
$dist = Join-Path $root "dist\index.html"
$srcFiles = @(Get-ChildItem (Join-Path $root "src") -Recurse -File) + @(Get-Item (Join-Path $root "index.html"))
$needsBuild = -Not (Test-Path $dist)
if (-Not $needsBuild) {
    $built = (Get-Item $dist).LastWriteTime
    $needsBuild = [bool]($srcFiles | Where-Object { $_.LastWriteTime -gt $built } | Select-Object -First 1)
}
if ($needsBuild) {
    if (-Not (Get-Command npm -ErrorAction SilentlyContinue)) {
        if (Test-Path $dist) { Warn "Node.js not found - using the existing (older) web build." }
        else { throw "The web app is not built and Node.js is not installed. Install Node.js 18+ and run again." }
    } else {
        Push-Location $root
        try {
            if (-Not (Test-Path (Join-Path $root "node_modules"))) {
                Step "Installing web dependencies"
                npm ci --no-audit --no-fund --silent
                if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
            }
            Step "Building the web app"
            npm run build --silent
            if ($LASTEXITCODE -ne 0) { throw "Web build failed." }
        } finally { Pop-Location }
    }
}
Ok "Web app ready"

# 4. Pick a free port ---------------------------------------------------------
$chosen = $null
foreach ($p in $Port..($Port + 20)) {
    if (-Not (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)) { $chosen = $p; break }
}
if (-Not $chosen) { throw "No free port between $Port and $($Port + 20)." }
$url = "http://localhost:$chosen"

# 5. Open the browser once the server answers, then run the server here --------
if (-Not $NoBrowser) {
    Start-Job -ArgumentList $url -ScriptBlock {
        param($u)
        for ($i = 0; $i -lt 120; $i++) {
            try { Invoke-WebRequest "$u/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process $u; return } catch { Start-Sleep -Milliseconds 500 }
        }
    } | Out-Null
}

Write-Host ""
Write-Host "  ScrapTrust is running at $url" -ForegroundColor Green
if ($authOff) {
    Write-Host "  Login is switched off for testing: the app opens directly, on this computer only." -ForegroundColor Yellow
} else {
    Write-Host "  Sign in with your account. (API docs are off; set EXPOSE_API_DOCS=true in backend\.env for development.)" -ForegroundColor Green
}
Write-Host "  Press Ctrl+C (or close this window) to stop." -ForegroundColor DarkGray
Write-Host ""

Push-Location $backend
try {
    & $py -m uvicorn app.main:app --host 127.0.0.1 --port $chosen --no-server-header   # audit I-08
} finally {
    Pop-Location
}
