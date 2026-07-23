#!/usr/bin/env bash
# Package Backlink Agent for boss PC (no Bifrost — shares news-agent Bifrost).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKLINK_IMAGE="openclaw-backlink-agent:2026.4.24"
OUT="${SCRIPT_DIR}/backlink-agent-deploy"
BOSS_DEPLOY_ROOT='C:\Users\TheOne\Downloads\backlink-agent-deploy\backlink-agent-deploy'

echo "Packaging Backlink Agent for boss PC..."
mkdir -p "$OUT"

if ! docker image inspect "$BACKLINK_IMAGE" >/dev/null 2>&1; then
  echo "ERROR: ${BACKLINK_IMAGE} not found — run: docker compose build backlink-agent"
  exit 1
fi

echo "Saving Docker image (this may take a few minutes)..."
docker save "$BACKLINK_IMAGE" | gzip > "${OUT}/openclaw-backlink-agent-image.tar.gz"

echo "Archiving persistent data..."
tar czf "${OUT}/backlink-data.tar.gz" -C "$SCRIPT_DIR" backlink-data

cat > "${OUT}/docker-compose.yml" <<'YAML'
services:
  backlink-agent:
    image: openclaw-backlink-agent:2026.4.24
    container_name: openclaw-backlink-agent
    restart: unless-stopped
    env_file:
      - .env
    environment:
      TZ: ${TZ:-Asia/Kolkata}
      HOME: /home/openclaw
      XDG_CONFIG_HOME: /home/openclaw/.config
      OPENCLAW_STATE_DIR: /home/openclaw/.openclaw-backlink
      BIFROST_BASE_URL: ${BIFROST_BASE_URL:-http://host.docker.internal:8888/v1}
      BL_DELIVERY_INTERVAL_MIN: ${BL_DELIVERY_INTERVAL_MIN:-60}
      BL_SITES_PER_TICK: ${BL_SITES_PER_TICK:-5}
      BL_SCAN_MAX_PER_SITE: ${BL_SCAN_MAX_PER_SITE:-20}
      IMAGE_MODEL: ${IMAGE_MODEL:-vertex/gemini-3.1-flash-lite-image}
      IMAGE_MODEL_FALLBACK: ${IMAGE_MODEL_FALLBACK:-huggingface/hf-inference/black-forest-labs/FLUX.1-schnell}
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./backlink-data/data:/home/openclaw/.openclaw-backlink/data
      - ./backlink-data/telegram:/home/openclaw/.openclaw-backlink/telegram
      - ./backlink-data/identity:/home/openclaw/.openclaw-backlink/identity
      - ./backlink-data/devices:/home/openclaw/.openclaw-backlink/devices
      - ./backlink-data/logs:/home/openclaw/.openclaw-backlink/logs
      - ./backlink-data/backups:/home/openclaw/.openclaw-backlink/.backups
      - ./backlink-data/workspace-bl-orchestrator/config:/home/openclaw/.openclaw-backlink/workspace-bl-orchestrator/config
      - ./backlink-data/assets:/home/openclaw/.openclaw-backlink/assets
      - ./backlink-data/exec-approvals.json:/home/openclaw/.openclaw-backlink/exec-approvals.json
    ports:
      - "${GATEWAY_PORT:-19789}:19789"
YAML

cp "${SCRIPT_DIR}/.env.example" "${OUT}/.env.example"
cp "${SCRIPT_DIR}/deploy.ps1.template" "${OUT}/deploy.ps1"
cp "${SCRIPT_DIR}/start.ps1.template" "${OUT}/start.ps1"
cp "${SCRIPT_DIR}/Start Backlink Agent.bat" "${OUT}/Start Backlink Agent.bat"

cat > "${OUT}/deploy.bat" <<'BAT'
@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1"
if errorlevel 1 pause
BAT

cat > "${OUT}/start.bat" <<'BAT'
@echo off
title Backlink Agent Start
cd /d "%~dp0"
echo.
echo === Backlink Agent ===
echo Folder: %CD%
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
    echo.
    echo FAILED - read the error above, then press any key to close.
    pause >nul
    exit /b 1
)
echo.
echo OK - window closes in 15 seconds, or press any key now.
pause >nul
BAT

cat > "${OUT}/README-WINDOWS.txt" <<README
Backlink Agent — Windows deploy (Docker Desktop)
================================================

Deploy folder (after extract):
  ${BOSS_DEPLOY_ROOT}

Prerequisite: news-agent Bifrost must be running on port 8888.
  Start "Start News Agent.bat" on desktop FIRST, then Backlink.

First install:
  1. Extract zip to Downloads\backlink-agent-deploy\
  2. Copy .env.example to .env
  3. Double-click deploy.bat ONCE
  4. Copy "Start Backlink Agent.bat" to Desktop

Daily use (after reboot):
  1. Start News Agent.bat  (Bifrost + news)
  2. Start Backlink Agent.bat

URLs:
  Backlink UI:  http://localhost:19789
  Bifrost UI:   http://localhost:8888  (from news-agent)

Do NOT run deploy.bat again on a live machine.
README

echo ""
echo "Bundle ready at: ${OUT}/"
ls -lh "${OUT}/"
