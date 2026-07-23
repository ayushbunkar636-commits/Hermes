#!/bin/bash
echo "========================================="
echo "       STARTING HERMES ENGINE            "
echo "========================================="

echo "-> Cleaning up old background processes..."
# Use kill -9 to force-terminate ALL python and node instances (Codespace cleanup)
pkill -9 python 2>/dev/null || true
pkill -9 node 2>/dev/null || true
sleep 5

echo "-> Verifying Python dependencies..."
pip install -r requirements.txt > /dev/null 2>&1

# Run database foreign key constraints fix
echo "-> Applying Database Foreign Key fixes..."
python apply_db_fixes.py

# Force-clear Telegram's polling session (avoids 409 Conflict)
echo "-> Clearing Telegram webhook/polling session..."
BOT_TOKEN=$(python3 -c "import os,sys; sys.path.insert(0,'workspace-bl-orchestrator/skills/pipeline'); import config; print(config.TELEGRAM_BOT_TOKEN)" 2>/dev/null)
if [ -n "$BOT_TOKEN" ]; then
    curl -s "https://api.telegram.org/bot${BOT_TOKEN}/deleteWebhook?drop_pending_updates=true" > /dev/null
    echo "   Telegram session cleared."
else
    echo "   Could not read BOT_TOKEN, skipping webhook clear."
fi

sleep 2

# 1. Start the Telegram Bot Router in the background
echo "-> Starting Telegram Router (Bot Listener)..."
python workspace-bl-orchestrator/skills/pipeline/telegram_router.py &
ROUTER_PID=$!

# 2. Reset any failed leads and Start the Nexus Daemon (Hunter) in the background
echo "-> Resetting any failed leads..."
python reset_leads.py

echo "-> Starting Nexus Daemon (Hunter)..."
python workspace-bl-orchestrator/skills/pipeline/nexus_daemon.py &
DAEMON_PID=$!

# 3. Start the Next.js Dashboard
echo "-> Starting Next.js Dashboard..."
cd workspace-dashboard
if [ ! -d "node_modules" ]; then
    echo "-> Installing Dashboard dependencies (this will only happen once)..."
    npm install
fi
npm run dev -- -H 0.0.0.0 &
cd ..
DASHBOARD_PID=$!

echo "========================================="
echo "Everything is LIVE! Press Ctrl+C to stop."
echo "========================================="

# Trap Ctrl+C (SIGINT) so it cleanly kills all background processes when you exit
trap "echo 'Stopping Hermes...'; kill $ROUTER_PID $DAEMON_PID $DASHBOARD_PID 2>/dev/null; exit" INT

# Wait keeps the script running and printing logs to this terminal
wait
