<#
.SYNOPSIS
Starts the Hermes Nexus Daemon for continuous background processing.

.DESCRIPTION
This script sets up the Python environment (if needed) and starts the nexus_daemon.py
script. It is designed to be run as a background service or Scheduled Task.
#>

$ErrorActionPreference = "Stop"
$WorkingDir = $PSScriptRoot

Write-Host "Starting Hermes Nexus Daemon..."

# Change to script directory
Set-Location -Path $WorkingDir

# Check if .env exists, if not warn
if (-not (Test-Path ".env")) {
    Write-Warning ".env file not found! Copy .env.production.example to .env and configure."
    exit 1
}

# Start the daemon directly (use pythonw.exe if you want it completely hidden, but python is fine for logging)
Write-Host "Launching daemon (Ctrl+C to stop)..."
python skills/pipeline/nexus_daemon.py

Write-Host "Daemon stopped."
