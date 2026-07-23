# Backlink Agent deploy for Windows (Docker Desktop, no WSL required)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Import-DockerImageGzip {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Missing file: $Path"
    }
    Write-Host "Loading $Path ..."
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "docker"
    $psi.Arguments = "load"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    $fs = [System.IO.File]::OpenRead((Resolve-Path $Path))
    $gzip = New-Object System.IO.Compression.GZipStream(
        $fs,
        [System.IO.Compression.CompressionMode]::Decompress
    )
    $gzip.CopyTo($proc.StandardInput.BaseStream)
    $proc.StandardInput.Close()
    $gzip.Close()
    $fs.Close()
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()
    if ($stdout) { Write-Host $stdout.TrimEnd() }
    if ($stderr) { Write-Host $stderr.TrimEnd() }
    if ($proc.ExitCode -ne 0) {
        throw "docker load failed for $Path (exit $($proc.ExitCode))"
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker not found. Install Docker Desktop and ensure it is running."
    exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker is not running. Start Docker Desktop, wait for it to be ready, then retry."
    exit 1
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ""
    Write-Host "Created .env from .env.example"
    Write-Host "Ensure news-agent Bifrost is running on port 8888, then run deploy.ps1 again."
    exit 1
}

Import-DockerImageGzip "openclaw-backlink-agent-image.tar.gz"

Write-Host "Extracting persistent data..."
tar -xzf backlink-data.tar.gz
if ($LASTEXITCODE -ne 0) {
    throw "Failed to extract backlink-data.tar.gz"
}

Write-Host "Starting Backlink Agent..."
Write-Host "NOTE: news-agent Bifrost must be running on http://localhost:8888"
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed"
}

Write-Host ""
Write-Host "Deploy complete."
Write-Host ""
Write-Host "Backlink UI:  http://localhost:19789"
Write-Host "Bifrost UI:   http://localhost:8888  (from news-agent stack)"
Write-Host ""
Write-Host "View logs:    docker compose logs -f"
