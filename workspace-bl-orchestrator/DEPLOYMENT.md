# Hermes Production Deployment Guide (Windows Server)

This guide covers deploying the Hermes Backlink Orchestrator on a Windows Server environment.

## 1. Prerequisites
- **Python 3.11+**: Ensure Python is installed and added to your system `PATH`.
- **PostgreSQL**: Install PostgreSQL locally or have connection details for a managed remote database (e.g., Supabase).

## 2. Setup

### Step A: Install Dependencies
Open PowerShell as Administrator, navigate to the `workspace-bl-orchestrator` directory, and run:
```powershell
pip install -r requirements.txt
```

### Step B: Configuration
1. Copy the template `.env.production.example` to `.env`.
   ```powershell
   Copy-Item .env.production.example .env
   ```
2. Open `.env` in a text editor and fill in your actual production values:
   - `TELEGRAM_BOT_TOKEN`: The API token from BotFather.
   - `TELEGRAM_ADMIN_CHAT_ID`: Your personal chat ID or group ID where the bot should send leads.
   - `DB_URL`: The PostgreSQL connection string.

## 3. Running as Background Services

To keep the system running 24/7 even after you log out of the Windows Server, you have two options:

### Option 1: Windows Task Scheduler (Recommended)
1. Open **Task Scheduler**.
2. Click **Create Basic Task**.
3. Name it "Hermes Nexus Daemon", trigger it "When the computer starts".
4. Action: "Start a Program".
5. Program/script: `powershell.exe`
6. Add arguments: `-ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\path\to\workspace-bl-orchestrator\start_nexus.ps1"`
7. Check "Run whether user is logged on or not" in the task properties and save with admin credentials.
8. **Repeat** the exact same process to create a second task named "Hermes Telegram Bot" pointing to `start_telegram_bot.ps1`.

### Option 2: NSSM (Non-Sucking Service Manager)
If you prefer Windows Services:
1. Download and extract NSSM (nssm.cc).
2. Open Command Prompt as Administrator and run:
   ```cmd
   nssm install HermesNexus
   ```
3. In the GUI:
   - Path: `powershell.exe`
   - Arguments: `-ExecutionPolicy Bypass -File "C:\path\to\workspace-bl-orchestrator\start_nexus.ps1"`
   - Click **Install Service**.
4. Repeat for `HermesTelegramBot` using `start_telegram_bot.ps1`.
5. Start both services in `services.msc`.

## 4. Maintenance & Logs
- The daemon outputs logs directly to standard output. If you are using Task Scheduler, you can modify the PowerShell scripts to append `>> C:\var\log\hermes.log` for persistent logging.
- You can monitor the health of the system via Telegram by sending the `/health` command to your bot.
