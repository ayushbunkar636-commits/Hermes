import os
import sys
import config
import logging
import whitelist_db as wdb
import backlink_db as bdb

# V2.0 Relevancy Engine imports
try:
    _SEARCH_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'search'))
    if _SEARCH_DIR not in sys.path:
        sys.path.insert(0, _SEARCH_DIR)
    from trend_ingestion import ingest_trends
    from sitemap_scanner import scan_project_sitemap
    from relevancy_engine import generate_relevancy_map, get_project_sitemap, get_latest_trend
    _V2_ENABLED = True
except ImportError:
    _V2_ENABLED = False

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
except ImportError:
    pass

import config
BOT_TOKEN = config.TELEGRAM_BOT_TOKEN

logger = logging.getLogger("telegram_router")
logging.basicConfig(level=logging.INFO)

async def onboard_command(update, context):
    """Handles /onboard (Replaces backlink-onboarder)."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    conn = config.get_db_connection()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS onboard_sessions (chat_id TEXT, user_id TEXT, step TEXT, PRIMARY KEY(chat_id, user_id))")
    try:
        c.execute("INSERT INTO onboard_sessions (chat_id, user_id, step) VALUES (%s, %s, %s)", (str(chat_id), str(user_id), "start"))
    except Exception:
        # If session exists, rollback the failed insert and update it instead
        conn.rollback()
        c.execute("UPDATE onboard_sessions SET step=%s WHERE chat_id=%s AND user_id=%s", ("start", str(chat_id), str(user_id)))
    conn.commit()
    conn.close()
    
    await update.message.reply_text("Welcome to Hermes Onboarding! What is your project URL%s")

async def handle_message(update, context):
    """Handles text messages for state progression."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    conn = config.get_db_connection()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS onboard_sessions (chat_id TEXT, user_id TEXT, step TEXT, PRIMARY KEY(chat_id, user_id))")
    c.execute("SELECT step FROM onboard_sessions WHERE chat_id=%s AND user_id=%s LIMIT 1", (str(chat_id), str(user_id)))
    row = c.fetchone()
    
    if row:
        step = row["step"]
        if step == "start":
            project_url = update.message.text
            c.execute("UPDATE onboard_sessions SET step=%s WHERE chat_id=%s", ("complete", str(chat_id)))
            keyboard = [[InlineKeyboardButton("Confirm", callback_data=f"confirm_{project_url}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(f"Project URL set to {project_url}.", reply_markup=reply_markup)
        
        elif step == "wait_add":
            c.execute("DELETE FROM onboard_sessions WHERE chat_id=%s AND user_id=%s", (str(chat_id), str(user_id)))
            parts = update.message.text.split()
            if len(parts) < 2:
                await update.message.reply_text("Invalid format. Please use: <url> <niche>")
            else:
                url, niche = parts[0], " ".join(parts[1:])
                context.args = [url, niche]
                await add_command(update, context)
                
        elif step == "wait_delete":
            c.execute("DELETE FROM onboard_sessions WHERE chat_id=%s AND user_id=%s", (str(chat_id), str(user_id)))
            context.args = [update.message.text.strip()]
            await delete_command(update, context)
            
        elif step == "wait_angle":
            c.execute("DELETE FROM onboard_sessions WHERE chat_id=%s AND user_id=%s", (str(chat_id), str(user_id)))
            context.args = [update.message.text.strip()]
            await angle_command(update, context)
            
        elif step == "wait_sitemap":
            c.execute("DELETE FROM onboard_sessions WHERE chat_id=%s AND user_id=%s", (str(chat_id), str(user_id)))
            context.args = [update.message.text.strip()]
            await sitemap_command(update, context)
            
        conn.commit()
    else:
        import subprocess
        import sys
        import os
        script_path = os.path.join(os.path.dirname(__file__), "handle_card_feedback.py")
        subprocess.Popen([
            sys.executable,
            script_path,
            "--message-text", update.message.text,
            "--chat-id", str(chat_id),
            "--user-id", str(user_id),
            "--username", update.effective_user.username or "",
            "--reply-to-message-id", str(update.message.message_id)
        ])
    conn.close()

async def handle_callback(update, context):
    """Handles inline keyboard button clicks."""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("confirm_"):
        project = query.data.split("confirm_")[1]
        
        wdb.init_whitelist_db(config.BL_DB_PATH)
        name = project.split("://")[-1] if "://" in project else project
        pid = wdb.upsert_project(project, niche="auto", name=name)
        
        # Seed default whitelist domains so the daemon actually has sites to scan
        default_sites = ["reddit.com", "news.ycombinator.com", "bitcointalk.org"]
        for site in default_sites:
            wdb.upsert_whitelist_site(pid, site, added_by="seed", db_path=config.BL_DB_PATH)
        
        if project.startswith("pdf://"):
            conn = config.get_db_connection()
            c = conn.cursor()
            c.execute("SELECT content FROM pdf_cache WHERE project_url=%s", (project,))
            row = c.fetchone()
            if row:
                pdf_text = row["content"]
                wdb.update_project_config(project, {"pdf_context": pdf_text}, db_path=config.BL_DB_PATH)
                c.execute("SELECT id FROM projects WHERE project_url=%s", (project,))
                pid_row = c.fetchone()
                if pid_row:
                    import vocab_miner
                    vocab_miner.seed_pdf_vocab_with_ai(pid_row["id"], pdf_text, db_path=config.BL_DB_PATH)
            conn.close()
            
        await query.edit_message_text(text=f"Project {project} formally confirmed and initialized via Hermes!")
        
    elif query.data == "cmd_trends":
        await trends_command(update, context)
    elif query.data == "cmd_projects":
        await projects_command(update, context)
    elif query.data == "cmd_stats":
        await stats_command(update, context)
    elif query.data == "cmd_health":
        await health_command(update, context)
    elif query.data == "cmd_help":
        await help_callback(update, context)
        
    # State-based Button Handlers
    elif query.data in ["cmd_add", "cmd_delete", "cmd_angle", "cmd_sitemap"]:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        state_map = {
            "cmd_add": ("wait_add", "Please reply with the new project URL and Niche (e.g. `https://example.com Tech`)"),
            "cmd_delete": ("wait_delete", "Please reply with the Project URL you want to delete."),
            "cmd_angle": ("wait_angle", "Please reply with the Project URL to generate a live Trend-Jacking angle."),
            "cmd_sitemap": ("wait_sitemap", "Please reply with the Project URL to view its sitemap status.")
        }
        step, prompt = state_map[query.data]
        
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS onboard_sessions (chat_id TEXT, user_id TEXT, step TEXT, PRIMARY KEY(chat_id, user_id))")
        
        c.execute("""
            INSERT INTO onboard_sessions (chat_id, user_id, step) 
            VALUES (%s, %s, %s)
            ON CONFLICT (chat_id, user_id) 
            DO UPDATE SET step = EXCLUDED.step
        """, (str(chat_id), str(user_id), step))
        
        conn.commit()
        conn.close()
        
        await query.message.reply_text(prompt, parse_mode="Markdown")
        
    elif query.data.startswith("bl_"):
        import subprocess
        import sys
        import os
        script_path = os.path.join(os.path.dirname(__file__), "handle_card_feedback.py")
        subprocess.Popen([
            sys.executable,
            script_path,
            "--payload", query.data,
            "--chat-id", str(update.effective_chat.id),
            "--user-id", str(update.effective_user.id),
            "--username", update.effective_user.username or "",
            "--reply-to-message-id", str(query.message.message_id)
        ])

async def handle_document(update, context):
    """Handles file uploads (e.g., config jsons, PDFs)."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    conn = config.get_db_connection()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS onboard_sessions (chat_id TEXT, user_id TEXT, step TEXT, PRIMARY KEY(chat_id, user_id))")
    c.execute("SELECT step FROM onboard_sessions WHERE chat_id=%s AND user_id=%s LIMIT 1", (str(chat_id), str(user_id)))
    row = c.fetchone()
    
    if row and row["step"] == "start":
        doc = update.message.document
        if not doc.file_name.lower().endswith(".pdf"):
            await update.message.reply_text("Please send a valid PDF file.")
            conn.close()
            return
            
        await update.message.reply_text("Downloading and reading PDF... Please wait.")
        
        file = await context.bot.get_file(doc.file_id)
        file_path = f"/tmp/{doc.file_name}"
        await file.download_to_drive(file_path)
        
        import PyPDF2
        text = ""
        try:
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for i in range(min(10, len(reader.pages))):
                    page_text = reader.pages[i].extract_text()
                    if page_text:
                        text += page_text + "\\n"
        except Exception as e:
            logger.error(f"Failed to parse PDF: {e}")
            await update.message.reply_text("Could not read this PDF. Please send a valid file or a URL.")
            conn.close()
            return
            
        c.execute("UPDATE onboard_sessions SET step=%s WHERE chat_id=%s", ("complete", str(chat_id)))
        project_url = f"pdf://{doc.file_name}"
        
        c.execute("CREATE TABLE IF NOT EXISTS pdf_cache (project_url TEXT PRIMARY KEY, content TEXT)")
        c.execute("DELETE FROM pdf_cache WHERE project_url=%s", (project_url,))
        c.execute("INSERT INTO pdf_cache (project_url, content) VALUES (%s, %s)", (project_url, text))
        conn.commit()
        conn.close()
        
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [[InlineKeyboardButton("Confirm PDF Project", callback_data=f"confirm_{project_url}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"PDF '{doc.file_name}' read successfully ({len(text)} characters). Shall we proceed%s", reply_markup=reply_markup)
    else:
        conn.close()
        file_id = update.message.document.file_id
        logger.info(f"Received document upload with ID: {file_id}")
        await update.message.reply_text("File upload received and routed natively via Hermes.")

async def add_command(update, context):
    """Handles /add <url> <niche>"""
    if not context.args:
        await update.message.reply_text("Usage: /add <project_url> [niche]")
        return
    project = context.args[0]
    niche = " ".join(context.args[1:]) if len(context.args) > 1 else "auto"
    
    try:
        wdb.init_whitelist_db(config.BL_DB_PATH)
        
        # Pause all existing projects so we only focus on the new one
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE projects SET status='paused' WHERE project_url != %s", (project,))
        conn.commit()
        conn.close()
        
        name = project.split("://")[-1] if "://" in project else project
        pid = wdb.upsert_project(project, niche=niche, name=name)
        
        default_sites = ["reddit.com", "news.ycombinator.com", "bitcointalk.org"]
        for site in default_sites:
            wdb.upsert_whitelist_site(pid, site, added_by="seed", db_path=config.BL_DB_PATH)
            
        await update.effective_message.reply_text(f"✅ Project {project} added successfully!\n⏸️ All other projects have been paused.\nNiche set to: {niche}. Tracking started.")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error adding project: {e}")

async def projects_command(update, context):
    """Lists all active projects."""
    try:
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT project_url, niche FROM projects WHERE status = 'active'")
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            await update.effective_message.reply_text("No active projects. Use /add <url> <niche> to add one.")
            return
            
        msg = "📋 *Active Projects*\n\n"
        for i, row in enumerate(rows, 1):
            msg += f"{i}. {row['project_url']} (Niche: {row['niche']})\n"
            
        await update.effective_message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.effective_message.reply_text(f"Error fetching projects: {e}")

async def delete_command(update, context):
    """Handles /delete <url> - deletes from both SQLite (daemon) and PostgreSQL (dashboard)"""
    if not context.args:
        await update.effective_message.reply_text("Usage: /delete <project_url>")
        return
    project = context.args[0]
    try:
        # 1. Delete from SQLite (daemon's source of truth)
        wdb.init_whitelist_db(config.BL_DB_PATH)
        wdb.delete_project(project, config.BL_DB_PATH)

        # 2. Also delete from PostgreSQL (dashboard's source of truth)
        try:
            conn = config.get_db_connection()
            c = conn.cursor()
            c.execute("DELETE FROM whitelist_sites WHERE project_id = (SELECT id FROM projects WHERE project_url = %s)", (project,))
            c.execute("DELETE FROM opportunities WHERE project_url = %s", (project,))
            c.execute("DELETE FROM projects WHERE project_url = %s", (project,))
            conn.commit()
            conn.close()
        except Exception as pg_err:
            # Don't fail if PostgreSQL delete has an issue - SQLite delete was the critical one
            print(f"[delete_command] PostgreSQL delete warning: {pg_err}")

        await update.effective_message.reply_text(f"🗑️ Project deleted from all systems:\n`{project}`", parse_mode="Markdown")
    except ValueError as e:
        await update.effective_message.reply_text(f"❌ {e}")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error deleting project: {e}")

async def scan_command(update, context):
    """Handles /scan"""
    try:
        wdb.init_whitelist_db(config.BL_DB_PATH)
        projects = wdb.get_active_projects(config.BL_DB_PATH)
        total_due = 0
        for p in projects:
            total_due += wdb.set_project_sites_due_now(p["id"], config.BL_DB_PATH)
        
        await update.effective_message.reply_text(f"🔍 Scan triggered! Marked {total_due} sources as due now. The orchestrator will pick them up shortly.")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error triggering scan: {e}")

async def stats_command(update, context):
    """Displays global system stats."""
    try:
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM projects WHERE status = 'active'")
        projects = c.fetchone()["cnt"]
        conn.close()
        
        # harvest_leads is in SQLite
        import sqlite3
        sqlite_conn = sqlite3.connect(config.BL_DB_PATH)
        sqlite_conn.row_factory = sqlite3.Row
        sc = sqlite_conn.cursor()
        sc.execute("SELECT status, COUNT(*) as cnt FROM harvest_leads GROUP BY status")
        lead_rows = sc.fetchall()
        sqlite_conn.close()
        
        stats = {r["status"]: r["cnt"] for r in lead_rows}
        total = sum(stats.values())
        
        msg = "📈 *Hermes Global Stats*\n\n"
        msg += f"Active Projects: {projects}\n"
        msg += f"Total Leads Found: {total}\n"
        msg += f"Approved & Drafted: {stats.get('DRAFTED', 0) + stats.get('SENT', 0)}\n"
        msg += f"Pending Review: {stats.get('SCORED', 0) + stats.get('GATED', 0)}\n"
        msg += f"Rejected: {stats.get('REJECTED', 0)}\n"
        
        await update.effective_message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.effective_message.reply_text(f"Error fetching stats: {e}")


async def health_command(update, context):
    """Phase 10: Reports daemon health based on heartbeat file."""
    import json, time, os
    try:
        if not os.path.exists(".daemon_heartbeat.json"):
            hb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".daemon_heartbeat.json")
            if not os.path.exists(hb_path):
                hb_path = ".daemon_heartbeat.json"
        else:
            hb_path = ".daemon_heartbeat.json"
            
        with open(hb_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        last_tick = data.get("last_tick_time", 0)
        ago = int(time.time() - last_tick)
        status = data.get("status", "unknown")
        ticks = data.get("total_ticks", 0)
        
        msg = (
            "*Daemon Health Status*\n"
            f"Status: `{status}`\n"
            f"Last Tick: `{ago} seconds ago`\n"
            f"Total Ticks Processed: `{ticks}`"
        )
        if ago > 300:
            msg += "\n\nWARNING: Daemon has not updated heartbeat in over 5 minutes. It may have crashed."
    except Exception as e:
        msg = f"Failed to read heartbeat: `{e}`\nIs the daemon running?"
        
    await update.effective_message.reply_text(msg, parse_mode="Markdown")


# ── V2.0 Telegram Commands ───────────────────────────────────────────────────

async def trends_command(update, context):
    """V2.0: /trends - Show today's top global trending topics."""
    if not _V2_ENABLED:
        await update.effective_message.reply_text("V2 Trend Engine not available on this server.")
        return
    try:
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT trend_query, discovered_at FROM daily_trends WHERE status = 'active' ORDER BY discovered_at DESC LIMIT 10")
        rows = c.fetchall()
        conn.close()
        if not rows:
            await update.effective_message.reply_text("No trends found. Run /ingesttrends to fetch fresh data.")
            return
        msg = "*Today's Global Trends (V2.0)*\n\n"
        for i, r in enumerate(rows, 1):
            msg += f"{i}. {r['trend_query']}\n"
        msg += r"\nUse /angle <project\_url> to generate a Trend-Jacking angle for your project."
        await update.effective_message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.effective_message.reply_text(f"Error fetching trends: {e}")


async def angle_command(update, context):
    """V2.0: /angle <project_url> - Generate a live Trend-Jacking angle."""
    if not _V2_ENABLED:
        await update.message.reply_text("V2 Relevancy Engine not available on this server.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /angle <project_url>\nExample: /angle https://clientfruits.com")
        return
    project_url = context.args[0].strip()
    await update.message.reply_text(f"Generating trend-jacking angle for `{project_url}`...", parse_mode="Markdown")
    try:
        # Get project from DB
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, niche FROM projects WHERE project_url = %s", (project_url,))
        proj = c.fetchone()
        conn.close()
        if not proj:
            await update.message.reply_text(f"Project not found: {project_url}\nAdd it first with /add")
            return
        pid = proj['id']
        niche = proj['niche'] or ''
        sitemap = get_project_sitemap(pid)
        trend = get_latest_trend()
        if not sitemap:
            await update.message.reply_text("Sitemap not found in DB. Scanning live right now...", parse_mode="Markdown")
            scan_project_sitemap(pid, project_url)
            sitemap = get_project_sitemap(pid)
            if not sitemap:
                await update.message.reply_text("Failed to find or parse sitemap for this URL. Ensure it has a /sitemap.xml")
                return
                
        if not trend:
            await update.message.reply_text("No trends found. Scanning live right now...", parse_mode="Markdown")
            ingest_trends()
            trend = get_latest_trend()
            if not trend:
                await update.message.reply_text("Failed to fetch trends. Try again later.")
                return
                
        rel_map = generate_relevancy_map(niche, sitemap, trend)
        if not rel_map.get('angle'):
            await update.message.reply_text("Could not generate angle. Try again.")
            return
        msg = (
            f"*Trend-Jacking Angle for {project_url}*\n\n"
            f"*Trending Topic:* {trend['query']}\n\n"
            f"*Generated Angle:*\n_{rel_map['angle']}_\n\n"
            f"*Pillar Link:* {rel_map.get('pillar_url', 'N/A')}\n"
            f"*Post Link:* {rel_map.get('post_url', 'N/A')}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error generating angle: {e}")


async def sitemap_command(update, context):
    """V2.0: /sitemap <project_url> - Show sitemap knowledge base status."""
    if not _V2_ENABLED:
        await update.message.reply_text("V2 Sitemap Engine not available on this server.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /sitemap <project_url>\nExample: /sitemap https://clientfruits.com")
        return
    project_url = context.args[0].strip()
    try:
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM projects WHERE project_url = %s", (project_url,))
        proj = c.fetchone()
        if not proj:
            conn.close()
            await update.message.reply_text(f"Project not found: {project_url}")
            return
        pid = proj['id']
        c.execute("SELECT page_type, COUNT(*) as cnt FROM project_sitemaps WHERE project_id = %s GROUP BY page_type", (pid,))
        rows = c.fetchall()
        conn.close()
        if not rows:
            await update.message.reply_text("Sitemap not found in DB. Scanning live right now...", parse_mode="Markdown")
            scan_project_sitemap(pid, project_url)
            
            # Re-fetch after scan
            conn = config.get_db_connection()
            c = conn.cursor()
            c.execute("SELECT page_type, COUNT(*) as cnt FROM project_sitemaps WHERE project_id = %s GROUP BY page_type", (pid,))
            rows = c.fetchall()
            conn.close()
            
            if not rows or rows[0]['cnt'] == 0:
                await update.message.reply_text(f"Could not find or parse a sitemap for {project_url}. Make sure it has a valid `/sitemap.xml`.", parse_mode="Markdown")
                return
                
        msg = f"*Sitemap Knowledge Base: {project_url}*\n\n"
        for r in rows:
            msg += f"{r['page_type'].upper()} pages: {r['cnt']}\n"
        msg += "\nUse /angle to generate a trend-jacking reply using these pages."
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def ingesttrends_command(update, context):
    """V2.0: /ingesttrends - Manually trigger a fresh trend fetch."""
    if not _V2_ENABLED:
        await update.effective_message.reply_text("V2 Trend Engine not available.")
        return
    await update.effective_message.reply_text("Fetching latest global trends... please wait.")
    try:
        ingest_trends()
        await update.effective_message.reply_text("Done! Use /trends to see what's trending now.")
    except Exception as e:
        await update.effective_message.reply_text(f"Error: {e}")

# ── Button Interface ─────────────────────────────────────────────────────────

async def menu_command(update, context):
    """Shows the main interactive button menu."""
    keyboard = [
        [InlineKeyboardButton("➕ Add Project", callback_data="cmd_add"),
         InlineKeyboardButton("🗑 Delete Project", callback_data="cmd_delete")],
        [InlineKeyboardButton("🧠 Generate Angle", callback_data="cmd_angle"),
         InlineKeyboardButton("🗺 Check Sitemap", callback_data="cmd_sitemap")],
        [InlineKeyboardButton("🌍 Top Trends (V2)", callback_data="cmd_trends"),
         InlineKeyboardButton("📋 Active Projects", callback_data="cmd_projects")],
        [InlineKeyboardButton("📈 System Stats", callback_data="cmd_stats"),
         InlineKeyboardButton("🩺 Daemon Health", callback_data="cmd_health")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = (
        "🚀 *Hermes Orchestrator Dashboard*\n\n"
        "Welcome! I am the Hermes Core Engine. Select a quick action below:"
    )
    await update.effective_message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")

async def help_callback(update, context):
    """(Deprecated) Help section no longer needed as all features are buttons."""
    pass

# ─────────────────────────────────────────────────────────────────────────────



def main():
    logger.info("Starting native Python Telegram Webhook Receiver...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    # Button Interface
    app.add_handler(CommandHandler("start", menu_command))
    app.add_handler(CommandHandler("menu", menu_command))
    # V1 Commands
    app.add_handler(CommandHandler("onboard", onboard_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("projects", projects_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("health", health_command))
    # V2.0 Commands
    app.add_handler(CommandHandler("trends", trends_command))
    app.add_handler(CommandHandler("angle", angle_command))
    app.add_handler(CommandHandler("sitemap", sitemap_command))
    app.add_handler(CommandHandler("ingesttrends", ingesttrends_command))
    # Message & callback handlers
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    # drop_pending_updates=True clears any lingering long-poll from a previous instance (fixes 409 Conflict)
    app.run_polling(drop_pending_updates=True, timeout=10)

if __name__ == '__main__':
    main()
