<#
.SYNOPSIS
Starts the Hermes Telegram Router bot.

.DESCRIPTION
This script sets up the Python environment (if needed) and starts the telegram_router.py
script. It is designed to be run as a background service or Scheduled Task.
#>

$ErrorActionPreference = "Stop"
$WorkingDir = $PSScriptRoot

Write-Host "Starting Hermes Telegram Router..."

# Change to script directory
Set-Location -Path $WorkingDir

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Warning ".env file not found! Please configure it first."
    exit 1
}

# Start the bot
Write-Host "Launching Telegram bot (Ctrl+C to stop)..."
python skills/pipeline/telegram_router.py

Write-Host "Telegram bot stopped."
