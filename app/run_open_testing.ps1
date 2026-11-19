# ScrapTrust - open testing from this laptop (free, no account, no card)
# Starts the app in open-testing mode (no login: every browser gets its own private guest space, Records view-only for
# everyone) and a free Cloudflare quick link (https://<random>.trycloudflare.com) that works from anywhere while this
# laptop is ON, AWAKE and ONLINE. The link changes every time this script starts; send the new one on WhatsApp.
#
#   .\run_open_testing.ps1          start (link is shown, copied to the clipboard and saved on the Desktop)
#   Ctrl+C or close the window      stop (the link stops working)
#
# Test data is kept apart from your own local data (backend\data\open_testing\): testers never see your earlier chats.

param([int]$Port = 8040)   # outside the normal launcher range 8010-8030

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$py = Join-Path $backend "venv\Scripts\python.exe"
$cloudflared = Join-Path (Split-Path $root -Parent) "tools\cloudflared.exe"
$dataDir = Join-Path $backend "data\open_testing"

function Step($msg) { Write-Host "-> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "   $msg" -ForegroundColor Green }

Write-Host ""
Write-Host "  ScrapTrust - open testing link" -ForegroundColor White
Write-Host ""
if (-Not (Test-Path $py)) { throw "Run ScrapTrust.bat once first (it sets up the Python environment)." }
if (-Not (Test-Path $cloudflared)) { throw "tools\cloudflared.exe is missing." }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is busy: open testing is probably already running in another window."
}

# 1. Web app build (only when the sources changed) -------------------------------
$dist = Join-Path $root "dist\index.html"
$srcFiles = @(Get-ChildItem (Join-Path $root "src") -Recurse -File) + @(Get-Item (Join-Path $root "index.html"))
$needsBuild = -Not (Test-Path $dist)
if (-Not $needsBuild) {
    $built = (Get-Item $dist).LastWriteTime
    $needsBuild = [bool]($srcFiles | Where-Object { $_.LastWriteTime -gt $built } | Select-Object -First 1)
}
if ($needsBuild) {
    Step "Building the web app"
    Push-Location $root
    try { npm run build --silent; if ($LASTEXITCODE -ne 0) { throw "Web build failed." } } finally { Pop-Location }
}
Ok "Web app ready"

# 2. Own secret + own data folders for open testing --------------------------------
New-Item -ItemType Directory -Force $dataDir | Out-Null
$secretFile = Join-Path $dataDir "secret_key.txt"
if (-Not (Test-Path $secretFile)) {
    & $py -c "import secrets; print(secrets.token_urlsafe(48))" | Out-File -FilePath $secretFile -Encoding ascii -NoNewline
}
$secret = (Get-Content $secretFile -Raw).Trim()

# 3. Free Cloudflare quick link -------------------------------------------------------
Step "Opening the public link (Cloudflare)"
$cfLog = Join-Path $dataDir "cloudflared.log"
Remove-Item $cfLog -ErrorAction SilentlyContinue
$cf = Start-Process -FilePath $cloudflared -PassThru -WindowStyle Hidden -RedirectStandardError $cfLog `
      -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$Port"
$link = $null
for ($i = 0; $i -lt 90 -and -Not $link; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $cfLog) {
        $m = Select-String -Path $cfLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
        if ($m) { $link = $m.Matches[0].Value }
    }
    if ($cf.HasExited) { break }
}
if (-Not $link) { Stop-Process -Id $cf.Id -ErrorAction SilentlyContinue; throw "Cloudflare did not give a link (no internet?). Try again in a minute." }
$linkHost = ([uri]$link).Host

# 4. Keep the laptop awake while this window is open (no settings are changed) ------
Add-Type -Namespace Bmtl -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
[Bmtl.Power]::SetThreadExecutionState([uint32]"0x80000001") | Out-Null   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED

# 5. Settings for open testing (environment only; backend\.env is not changed) -------
$env:AUTH_MODE = "public_demo"
$env:PUBLIC_RECORDS = "true"
$env:SECRET_KEY = $secret
$env:TRUSTED_HOSTS = $linkHost
$env:COOKIE_SECURE = "true"
$env:TRUST_PROXY_HEADERS = "true"
$env:CORS_ORIGINS = "[]"
$env:COPILOT_PROVIDER = "offline"
$env:DEBUG = "false"
$env:EXPOSE_API_DOCS = "false"
$env:HOST_BINDING = "127.0.0.1"
$env:LOCAL_STORAGE_PATH = Join-Path $dataDir "app"
$env:USERS_FILE = Join-Path $dataDir "security\users.json"
$env:RECORDS_FILE = Join-Path $dataDir "records\records.db"
$env:GUESTS_PER_IP_PER_HOUR = "60"
$env:GUEST_IP_CHAT_PER_MINUTE = "120"

$desktop = [Environment]::GetFolderPath("Desktop")
"ScrapTrust test link (works while the laptop is on, awake and online):`r`n$link`r`n" |
    Out-File -FilePath (Join-Path $desktop "ScrapTrust test link.txt") -Encoding utf8
try { Set-Clipboard -Value $link } catch { }

Write-Host ""
Write-Host "  PUBLIC LINK:  $link" -ForegroundColor Green
Write-Host "  (copied to the clipboard, and saved on the Desktop as 'ScrapTrust test link.txt')" -ForegroundColor Green
Write-Host "  Keep this window open, the laptop plugged in, the lid OPEN and Wi-Fi on." -ForegroundColor Yellow
Write-Host "  Press Ctrl+C or close this window to stop; the link then stops working." -ForegroundColor DarkGray
Write-Host ""

Push-Location $backend
try {
    & $py -m uvicorn app.main:app --host 127.0.0.1 --port $Port --proxy-headers --forwarded-allow-ips=127.0.0.1 --no-server-header --timeout-keep-alive 5
} finally {
    Pop-Location
    Stop-Process -Id $cf.Id -ErrorAction SilentlyContinue
    [Bmtl.Power]::SetThreadExecutionState([uint32]"0x80000000") | Out-Null
}
