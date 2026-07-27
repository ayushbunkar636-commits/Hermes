Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "       STARTING HERMES ENGINE            " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# ─── Load .env file into current PowerShell session ─────────────────
Write-Host "-> Loading environment variables from .env..." -ForegroundColor Yellow
$envPath = Join-Path $PSScriptRoot ".env"
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line -contains "=") {
            $parts = $line -split "=", 2
            $key = $parts[0].Trim()
            $val = $parts[1].Trim().Trim('"').Trim("'")
            [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
            Write-Host "   Set: $key" -ForegroundColor DarkGray
        }
    }
    Write-Host "   .env loaded successfully." -ForegroundColor Green
} else {
    Write-Host "   WARNING: .env file not found at $envPath" -ForegroundColor Red
}

# ─── Kill existing Python/Node processes (cleanup) ──────────────────
Write-Host "-> Cleaning up old background processes..." -ForegroundColor Yellow
Stop-Process -Name "python" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "python3" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "node" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# ─── Install Python dependencies ─────────────────────────────────────
Write-Host "-> Verifying Python dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "   pip install failed! Continuing anyway..." -ForegroundColor Red
}

# ─── Apply DB fixes ──────────────────────────────────────────────────
Write-Host "-> Applying Database Foreign Key fixes..." -ForegroundColor Yellow
python apply_db_fixes.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "   DB fixes had warnings (may be OK)." -ForegroundColor DarkYellow
}

# ─── Clear Telegram webhook ──────────────────────────────────────────
Write-Host "-> Clearing Telegram webhook/polling session..." -ForegroundColor Yellow
$botToken = [System.Environment]::GetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "Process")
if ($botToken) {
    try {
        $response = Invoke-WebRequest -Uri "https://api.telegram.org/bot${botToken}/deleteWebhook?drop_pending_updates=true" -UseBasicParsing -TimeoutSec 10
        Write-Host "   Telegram session cleared." -ForegroundColor Green
    } catch {
        Write-Host "   Could not clear Telegram webhook (non-fatal)." -ForegroundColor DarkYellow
    }
} else {
    Write-Host "   BOT_TOKEN not set, skipping webhook clear." -ForegroundColor DarkYellow
}

Start-Sleep -Seconds 2

# ─── 1. Start Telegram Router ────────────────────────────────────────
Write-Host "-> Starting Telegram Router (Bot Listener)..." -ForegroundColor Yellow
$routerJob = Start-Process -FilePath "python" `
    -ArgumentList "workspace-bl-orchestrator/skills/pipeline/telegram_router.py" `
    -NoNewWindow -PassThru

# ─── 2. Reset failed leads ───────────────────────────────────────────
Write-Host "-> Resetting any failed leads..." -ForegroundColor Yellow
python reset_leads.py

# ─── 3. Start Nexus Daemon ───────────────────────────────────────────
Write-Host "-> Starting Nexus Daemon (Hunter)..." -ForegroundColor Yellow
$daemonJob = Start-Process -FilePath "python" `
    -ArgumentList "workspace-bl-orchestrator/skills/pipeline/nexus_daemon.py" `
    -NoNewWindow -PassThru

# ─── 4. Start Next.js Dashboard ──────────────────────────────────────
Write-Host "-> Starting Next.js Dashboard..." -ForegroundColor Yellow
Set-Location workspace-dashboard
Write-Host "-> Verifying Dashboard dependencies..." -ForegroundColor Yellow
npm install
$dashboardJob = Start-Process -FilePath "npm" `
    -ArgumentList "run", "dev" `
    -NoNewWindow -PassThru
Set-Location ..

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  Everything is LIVE!" -ForegroundColor Green
Write-Host "  Dashboard:   http://localhost:3000" -ForegroundColor Green
Write-Host "  PIDs: Router=$($routerJob.Id), Daemon=$($daemonJob.Id), Dashboard=$($dashboardJob.Id)" -ForegroundColor DarkGray
Write-Host "  Press Ctrl+C to stop all services." -ForegroundColor Yellow
Write-Host "=========================================" -ForegroundColor Green

# ─── Wait and handle Ctrl+C ──────────────────────────────────────────
try {
    while ($true) {
        Start-Sleep -Seconds 5
        # Check if processes are still running
        if ($routerJob.HasExited) { Write-Host "[WARN] Telegram Router stopped unexpectedly!" -ForegroundColor Red }
        if ($daemonJob.HasExited) { Write-Host "[WARN] Nexus Daemon stopped unexpectedly!" -ForegroundColor Red }
        if ($dashboardJob.HasExited) { Write-Host "[WARN] Next.js Dashboard stopped unexpectedly!" -ForegroundColor Red }
    }
} finally {
    Write-Host ""
    Write-Host "Stopping Hermes Engine..." -ForegroundColor Yellow
    if (-not $routerJob.HasExited) { Stop-Process -Id $routerJob.Id -Force -ErrorAction SilentlyContinue }
    if (-not $daemonJob.HasExited) { Stop-Process -Id $daemonJob.Id -Force -ErrorAction SilentlyContinue }
    if (-not $dashboardJob.HasExited) { Stop-Process -Id $dashboardJob.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "All services stopped." -ForegroundColor Cyan
}
