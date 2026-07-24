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
        
        elif step == "wait_add_url":
            url = update.message.text.strip()
            if '\n' in url:
                # Extract the actual URL if user copy-pasted a multi-line message
                url = url.split('\n')[-1].strip()
            # Basic validation
            if not url.startswith("http"):
                url = "https://" + url
            new_step = f"wait_add_niche|{url}"
            c.execute("UPDATE onboard_sessions SET step=%s WHERE chat_id=%s AND user_id=%s", (new_step, str(chat_id), str(user_id)))
            await update.message.reply_text(f"URL received:\n{url}\n\nNow, please reply with the Niche for this project (e.g. `Tech`, `AI Tools`, `Web Dev`).")
            
        elif step.startswith("wait_add_niche|"):
            url = step.split("|", 1)[1]
            niche = update.message.text.strip()
            context.args = [url, niche]
            success = await add_command(update, context)
            if success:
                c.execute("DELETE FROM onboard_sessions WHERE chat_id=%s AND user_id=%s", (str(chat_id), str(user_id)))
                
        elif step == "wait_delete":
            context.args = [update.message.text.strip()]
            success = await delete_command(update, context)
            if success:
                c.execute("DELETE FROM onboard_sessions WHERE chat_id=%s AND user_id=%s", (str(chat_id), str(user_id)))
            
        elif step == "wait_angle":
            context.args = [update.message.text.strip()]
            success = await angle_command(update, context)
            if success:
                c.execute("DELETE FROM onboard_sessions WHERE chat_id=%s AND user_id=%s", (str(chat_id), str(user_id)))
            
        elif step == "wait_sitemap":
            context.args = [update.message.text.strip()]
            success = await sitemap_command(update, context)
            if success:
                c.execute("DELETE FROM onboard_sessions WHERE chat_id=%s AND user_id=%s", (str(chat_id), str(user_id)))
            
        conn.commit()
    else:
        text = update.message.text.strip()
        import re
        alert_match = re.search(r"\bbl-([A-Za-z0-9_-]+(?:-[A-Za-z0-9_-]+)*)\b", text)
        alert_id = alert_match.group(0) if alert_match else None
        
        if alert_id:
            opp = bdb.lookup_by_alert_id(alert_id, config.BL_DB_PATH)
            if opp:
                class DummyQuery:
                    def __init__(self, data, message):
                        self.data = data
                        self.message = message
                if re.match(r"^(bl_approve|approve)\s*$", text, re.IGNORECASE):
                    update.callback_query = DummyQuery(f'bl_approve:{alert_id}', update.message)
                    await handle_bl_approve(update, context, opp)
                elif re.match(r"^(bl_reject|reject)\s*$", text, re.IGNORECASE):
                    update.callback_query = DummyQuery(f'bl_reject:{alert_id}', update.message)
                    await handle_bl_reject(update, context, opp)
                elif re.match(r"^(bl_edit|edit)\s*$", text, re.IGNORECASE):
                    update.callback_query = DummyQuery(f'bl_edit:{alert_id}', update.message)
                    await handle_bl_edit(update, context, opp)
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
            "cmd_add": ("wait_add_url", "Please reply with the new project URL."),
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
        
    elif query.data.startswith("cmd_angle_id_"):
        pid = query.data.replace("cmd_angle_id_", "")
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT project_url FROM projects WHERE id = %s", (pid,))
        proj = c.fetchone()
        conn.close()
        if proj:
            context.args = [proj['project_url']]
            await angle_command(update, context)
        else:
            await query.message.reply_text("Project not found.")

    elif query.data.startswith("bl_"):
        await query.answer()
        alert_id = query.data.split(":", 1)[1] if ":" in query.data else None
        opp = bdb.lookup_by_alert_id(alert_id, config.BL_DB_PATH) if alert_id else None
        if query.data.startswith("bl_approve:"):
            await handle_bl_approve(update, context, opp)
        elif query.data.startswith("bl_reject:"):
            await handle_bl_reject(update, context, opp)
        elif query.data.startswith("bl_edit:"):
            await handle_bl_edit(update, context, opp)
        elif query.data.startswith("bl_edit_apply:"):
            await handle_bl_edit_apply(update, context, opp)
        elif query.data.startswith("bl_edit_cancel:"):
            await handle_bl_edit_cancel(update, context, opp)
        elif query.data.startswith("bl_regen:"):
            await handle_bl_regen(update, context, opp)

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
        doc_name = update.message.document.file_name or ""
        reply_to = update.message.reply_to_message
        
        if reply_to and doc_name.lower().endswith(".md"):
            pair = bdb.get_edit_session_by_prompt(reply_to.message_id, config.BL_DB_PATH)
            if pair:
                session, opp = pair
                if session.state == "awaiting_paste":
                    file = await context.bot.get_file(file_id)
                    import tempfile
                    with tempfile.NamedTemporaryFile("wb", delete=False) as f:
                        await file.download_to_drive(f.name)
                        tmp_path = f.name
                    with open(tmp_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    os.unlink(tmp_path)
                    
                    baseline = bdb.resolve_opportunity_content(opp, config.BL_DB_PATH) or ""
                    def normalize_md(text): return "\n".join([ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]).strip()
                    
                    if normalize_md(content) == normalize_md(baseline):
                        await update.message.reply_text("No changes detected. Edit the file and upload again.", reply_to_message_id=reply_to.message_id)
                    else:
                        version_id = bdb.save_content_version(opp.id, "user_suggested", content, user_id=str(user_id), user_username=update.effective_user.username, db_path=config.BL_DB_PATH)
                        bdb.upsert_edit_session(opp.id, str(user_id), "awaiting_confirm", prompt_message_id=session.prompt_message_id, suggested_version_id=version_id, db_path=config.BL_DB_PATH)
                        diff_summary = _format_diff_summary(baseline, content)
                        
                        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                        keyboard = [[
                            InlineKeyboardButton("Apply edit", callback_data=f"bl_edit_apply:{opp.alert_id}"),
                            InlineKeyboardButton("Cancel", callback_data=f"bl_edit_cancel:{opp.alert_id}")
                        ]]
                        await update.message.reply_text(f"Edit saved for <code>{opp.alert_id}</code> — <b>{diff_summary}</b> changed.\n\nApply edit?", reply_markup=InlineKeyboardMarkup(keyboard), reply_to_message_id=reply_to.message_id, parse_mode="HTML")
                    return
        
        logger.info(f"Received document upload with ID: {file_id}")
        await update.message.reply_text("File upload received and routed natively via Hermes.")

async def add_command(update, context):
    """Handles /add <url> <niche> or triggers interactive add flow if no args."""
    if not context.args:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS onboard_sessions (chat_id TEXT, user_id TEXT, step TEXT, PRIMARY KEY(chat_id, user_id))")
        c.execute("""
            INSERT INTO onboard_sessions (chat_id, user_id, step) 
            VALUES (%s, %s, %s)
            ON CONFLICT (chat_id, user_id) 
            DO UPDATE SET step = EXCLUDED.step
        """, (str(chat_id), str(user_id), "wait_add_url"))
        conn.commit()
        conn.close()
        
        await update.effective_message.reply_text("Please reply with the new project URL.")
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
            
        progress_text = (
            "⏳ *Project Setup: Active* [░░░░░░░░░░] 0% Scanned\n"
            "• *Status:* Project Initialized\n"
            "• *Time Elapsed:* 0s\n"
            "• *Est. Remaining:* ~8m\n\n"
            "_You will receive the first backlink opportunity report in this chat shortly._"
        )
        sent_msg = await update.effective_message.reply_text(progress_text, parse_mode="Markdown")
        
        # Save progress record so the background daemon can edit this message
        wdb.upsert_scan_progress(
            project_id=pid,
            percent=0,
            status="Project Initialized",
            chat_id=str(update.effective_chat.id),
            telegram_message_id=sent_msg.message_id,
            db_path=config.BL_DB_PATH
        )
        return True
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error adding project: {e}")
        return False

async def projects_command(update, context):
    """Lists all active projects."""
    msg_obj = await update.effective_message.reply_text("⏳ Fetching active projects list...")
    try:
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT project_url, niche FROM projects WHERE status = 'active'")
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            await msg_obj.edit_text("No active projects. Use /add <url> <niche> to add one.")
            return
            
        msg = "📋 *Active Projects*\n\n"
        for i, row in enumerate(rows, 1):
            msg += f"{i}. {row['project_url']} (Niche: {row['niche']})\n"
            
        await msg_obj.edit_text(msg, parse_mode="Markdown")
    except Exception as e:
        await msg_obj.edit_text(f"Error fetching projects: {e}")

async def delete_command(update, context):
    """Handles /delete <url> - deletes from both SQLite (daemon) and PostgreSQL (dashboard)"""
    if not context.args:
        await update.effective_message.reply_text("Usage: /delete <project_url>")
        return
    project = context.args[0]
    msg_obj = await update.effective_message.reply_text(f"⏳ Deleting project `{project}` from all systems...", parse_mode="Markdown")
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

        await msg_obj.edit_text(f"🗑️ Project deleted from all systems:\n`{project}`", parse_mode="Markdown")
    except ValueError as e:
        await msg_obj.edit_text(f"❌ {e}")
        return False
    except Exception as e:
        await msg_obj.edit_text(f"❌ Error deleting project: {e}")
        return False
        
    return True

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
    msg_obj = await update.effective_message.reply_text("⏳ Compiling global system stats...")
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
        lead_rows = []
        try:
            sc.execute("SELECT status, COUNT(*) as cnt FROM harvest_leads GROUP BY status")
            lead_rows = sc.fetchall()
        except sqlite3.OperationalError:
            # Table might not exist yet if farmer hasn't run or if migrated
            pass
        sqlite_conn.close()
        
        stats = {r["status"]: r["cnt"] for r in lead_rows}
        total = sum(stats.values())
        
        msg = "📈 *Hermes Global Stats*\n\n"
        msg += f"Active Projects: {projects}\n"
        msg += f"Total Leads Found: {total}\n"
        msg += f"Approved & Drafted: {stats.get('DRAFTED', 0) + stats.get('SENT', 0)}\n"
        msg += f"Pending Review: {stats.get('SCORED', 0) + stats.get('GATED', 0)}\n"
        msg += f"Rejected: {stats.get('REJECTED', 0)}\n"
        
        await msg_obj.edit_text(msg, parse_mode="Markdown")
    except Exception as e:
        await msg_obj.edit_text(f"Error fetching stats: {e}")


async def health_command(update, context):
    """Phase 10: Reports daemon health based on heartbeat file."""
    import json, time, os
    msg_obj = await update.effective_message.reply_text("⏳ Checking daemon health and heartbeat...")
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
        air_gap = data.get("air_gap", 300)
        
        msg = (
            "*Daemon Health Status*\n"
            f"Status: `{status}`\n"
            f"Last Tick: `{ago} seconds ago`\n"
            f"Total Ticks Processed: `{ticks}`"
        )
        if ago > (air_gap + 60):
            msg += f"\n\nWARNING: Daemon has not updated heartbeat in over {air_gap//60} minutes. It may have crashed."
    except Exception as e:
        msg = f"Failed to read heartbeat: `{e}`\nIs the daemon running?"
        
    await msg_obj.edit_text(msg, parse_mode="Markdown")


# ── V2.0 Telegram Commands ───────────────────────────────────────────────────

async def trends_command(update, context):
    """V2.0: /trends - Show today's top global trending topics."""
    if not _V2_ENABLED:
        await update.effective_message.reply_text("V2 Trend Engine not available on this server.")
        return
    msg_obj = await update.effective_message.reply_text("⏳ Fetching today's top global trending topics...")
    try:
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT trend_query, discovered_at FROM daily_trends WHERE status = 'active' ORDER BY discovered_at DESC LIMIT 10")
        rows = c.fetchall()
        conn.close()
        if not rows:
            await msg_obj.edit_text("No trends found. Run /ingesttrends to fetch fresh data.")
            return
        msg = "*Today's Global Trends (V2.0)*\n\n"
        for i, r in enumerate(rows, 1):
            msg += f"{i}. {r['trend_query']}\n"
        msg += r"\nUse /angle <project\_url> to generate a Trend-Jacking angle for your project."
        await msg_obj.edit_text(msg, parse_mode="Markdown")
    except Exception as e:
        await msg_obj.edit_text(f"Error fetching trends: {e}")


async def angle_command(update, context):
    """V2.0: /angle <project_url> - Generate a live Trend-Jacking angle."""
    if not _V2_ENABLED:
        await update.effective_message.reply_text("V2 Relevancy Engine not available on this server.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /angle <project_url>\nExample: /angle https://clientfruits.com")
        return
    project_url = context.args[0].strip()
    msg_obj = await update.effective_message.reply_text(f"⏳ Fetching project details for `{project_url}`...", parse_mode="Markdown")
    try:
        # Get project from DB
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, niche FROM projects WHERE project_url = %s", (project_url,))
        proj = c.fetchone()
        conn.close()
        if not proj:
            await msg_obj.edit_text(f"Project not found: {project_url}\nAdd it first with /add")
            return False
        pid = proj['id']
        niche = proj['niche'] or ''
        await msg_obj.edit_text("⏳ Checking Sitemap Knowledge Base...")
        sitemap = get_project_sitemap(pid)
        trend = get_latest_trend()
        if not sitemap:
            await msg_obj.edit_text("⏳ Sitemap not found in DB. Scanning live right now...", parse_mode="Markdown")
            scan_project_sitemap(pid, project_url)
            sitemap = get_project_sitemap(pid)
            if not sitemap:
                await msg_obj.edit_text("❌ Failed to find or parse sitemap for this URL. Ensure it has a /sitemap.xml")
                return False
                
        await msg_obj.edit_text("⏳ Checking for Top Global Trends...")
        if not trend:
            await msg_obj.edit_text("⏳ No trends found. Fetching live trends right now...", parse_mode="Markdown")
            ingest_trends()
            trend = get_latest_trend()
            if not trend:
                await msg_obj.edit_text("❌ Failed to fetch trends. Try again later.")
                return False
                
        await msg_obj.edit_text("⏳ Generating Relevancy Map & Angle (AI Processing)...")
        rel_map = generate_relevancy_map(niche, sitemap, trend)
        if not rel_map.get('angle'):
            await msg_obj.edit_text("❌ Could not generate angle. Try again.")
            return False
        msg = (
            f"*Trend-Jacking Angle for {project_url}*\n\n"
            f"*Trending Topic:* {trend['query']}\n\n"
            f"*Generated Angle:*\n_{rel_map['angle']}_\n\n"
            f"*Pillar Link:* {rel_map.get('pillar_url', 'N/A')}\n"
            f"*Post Link:* {rel_map.get('post_url', 'N/A')}"
        )
        await msg_obj.edit_text(msg, parse_mode="Markdown")
        return True
    except Exception as e:
        await msg_obj.edit_text(f"❌ Error generating angle: {e}")
        return False


async def sitemap_command(update, context):
    """V2.0: /sitemap <project_url> - Show sitemap knowledge base status."""
    if not _V2_ENABLED:
        await update.message.reply_text("V2 Sitemap Engine not available on this server.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /sitemap <project_url>\nExample: /sitemap https://clientfruits.com")
        return
    project_url = context.args[0].strip()
    msg_obj = await update.message.reply_text(f"⏳ Checking sitemap knowledge base for `{project_url}`...", parse_mode="Markdown")
    try:
        conn = config.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM projects WHERE project_url = %s", (project_url,))
        proj = c.fetchone()
        if not proj:
            conn.close()
            await msg_obj.edit_text(f"Project not found: {project_url}")
            return False
        pid = proj['id']
        c.execute("SELECT page_type, COUNT(*) as cnt FROM project_sitemaps WHERE project_id = %s GROUP BY page_type", (pid,))
        rows = c.fetchall()
        conn.close()
        if not rows:
            await msg_obj.edit_text("⏳ Sitemap not found in DB. Scanning live right now...", parse_mode="Markdown")
            scan_project_sitemap(pid, project_url)
            
            # Re-fetch after scan
            conn = config.get_db_connection()
            c = conn.cursor()
            c.execute("SELECT page_type, COUNT(*) as cnt FROM project_sitemaps WHERE project_id = %s GROUP BY page_type", (pid,))
            rows = c.fetchall()
            conn.close()
            
            if not rows or rows[0]['cnt'] == 0:
                await msg_obj.edit_text(f"❌ Could not find or parse a sitemap for {project_url}. Make sure it has a valid `/sitemap.xml`.", parse_mode="Markdown")
                return False
                
        msg = f"*Sitemap Knowledge Base: {project_url}*\n\n"
        for r in rows:
            msg += f"{r['page_type'].upper()} pages: {r['cnt']}\n"
        msg += "\nClick the button below to generate a Trend-Jacking reply using these pages."
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🧠 Generate Angle", callback_data=f"cmd_angle_id_{pid}")]])
        await msg_obj.edit_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
        return True
    except Exception as e:
        await msg_obj.edit_text(f"❌ Error: {e}")
        return False


async def ingesttrends_command(update, context):
    """V2.0: /ingesttrends - Manually trigger a fresh trend fetch."""
    if not _V2_ENABLED:
        await update.effective_message.reply_text("V2 Trend Engine not available.")
        return
    msg_obj = await update.effective_message.reply_text("⏳ Fetching latest global trends... please wait.")
    try:
        ingest_trends()
        await msg_obj.edit_text("✅ Done! Use /trends to see what's trending now.")
    except Exception as e:
        await msg_obj.edit_text(f"❌ Error: {e}")

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

async def help_command(update, context):
    """Displays available commands."""
    msg = (
        "*Available Commands*\n"
        "/start - Show Hermes Dashboard\n"
        "/projects - List active projects\n"
        "/add - Add a new project\n"
        "/stats - View project statistics\n"
        "/health - Check daemon health\n"
        "/trends - Show trending topics\n"
        "/angle - Generate a trend-jacking angle\n"
        "/sitemap - Process sitemap for a project\n"
    )
    await update.effective_message.reply_text(msg, parse_mode="Markdown")

async def help_callback(update, context):
    """(Deprecated) Help section no longer needed as all features are buttons."""
    pass

# ─────────────────────────────────────────────────────────────────────────────




# ─────────────────────────────────────────────────────────────────────────────
# NATIVE CARD FEEDBACK HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

def _format_diff_summary(baseline: str, edited: str) -> str:
    import difflib
    def normalize_md(text: str) -> str:
        return "\n".join([ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]).strip()
    base_lines = normalize_md(baseline).splitlines()
    edit_lines = normalize_md(edited).splitlines()
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base_lines, edit_lines).get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "replace":
            added += j2 - j1
            removed += i2 - i1
    return f"+{min(added, 99)} / -{min(removed, 99)} lines"

async def handle_bl_approve(update, context, opp):
    if not opp: return
    bdb.set_status(opp.id, "approved", config.BL_DB_PATH)
    bdb.record_feedback(opp.id, "approve", user_id=str(update.effective_user.id), user_username=update.effective_user.username, source="callback", raw_payload=update.callback_query.data, db_path=config.BL_DB_PATH)
    if opp.project_url and opp.site_url:
        wdb.mark_seen_for_project_url(opp.project_url, opp.site_url, db_path=config.BL_DB_PATH)
    try:
        pid = wdb.get_project_id(opp.project_url or "", db_path=config.BL_DB_PATH) if opp.project_url else None
        if pid:
            import vocab_miner
            vocab_miner.mine_project_vocab(pid, db_path=config.BL_DB_PATH)
    except Exception as e:
        logger.error(f"VOCAB_MINE_SKIP: {e}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Approved <code>{opp.alert_id}</code> for manual submission.", reply_to_message_id=update.callback_query.message.message_id, parse_mode="HTML")

async def handle_bl_reject(update, context, opp):
    if not opp: return
    bdb.set_status(opp.id, "rejected", config.BL_DB_PATH)
    bdb.record_feedback(opp.id, "reject", user_id=str(update.effective_user.id), user_username=update.effective_user.username, source="callback", raw_payload=update.callback_query.data, db_path=config.BL_DB_PATH)
    if opp.project_url and opp.site_url:
        wdb.mark_seen_for_project_url(opp.project_url, opp.site_url, db_path=config.BL_DB_PATH)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Rejected <code>{opp.alert_id}</code>. Feedback saved.", reply_to_message_id=update.callback_query.message.message_id, parse_mode="HTML")

async def handle_bl_edit(update, context, opp):
    if not opp: return
    content = bdb.resolve_opportunity_content(opp, config.BL_DB_PATH)
    if not content: return
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(content)
        tmp_path = f.name
        
    try:
        caption = f"Edit <code>{opp.alert_id}</code>\n\nDownload -> edit -> save -> reply with corrected <b>.md</b> file."
        msg = await context.bot.send_document(
            chat_id=update.effective_chat.id, 
            document=open(tmp_path, "rb"), 
            caption=caption, 
            reply_to_message_id=update.callback_query.message.message_id, 
            parse_mode="HTML"
        )
        prompt_id = msg.message_id
        bdb.upsert_edit_session(opp.id, str(update.effective_user.id), "awaiting_paste", prompt_message_id=prompt_id, db_path=config.BL_DB_PATH)
    finally:
        os.unlink(tmp_path)

async def handle_bl_edit_apply(update, context, opp):
    if not opp: return
    suggested = bdb.get_latest_version(opp.id, "user_suggested", config.BL_DB_PATH)
    if not suggested: return
    bdb.save_content_version(opp.id, "applied", suggested.content_md, user_id=str(update.effective_user.id), db_path=config.BL_DB_PATH)
    bdb.record_feedback(opp.id, "edit_apply", user_id=str(update.effective_user.id), source="callback", raw_payload=update.callback_query.data, edited_content=suggested.content_md, db_path=config.BL_DB_PATH)
    bdb.clear_edit_session(opp.id, str(update.effective_user.id), config.BL_DB_PATH)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Edit applied for <code>{opp.alert_id}</code>. Saved to database.", reply_to_message_id=update.callback_query.message.message_id, parse_mode="HTML")

async def handle_bl_edit_cancel(update, context, opp):
    if not opp: return
    bdb.clear_edit_session(opp.id, str(update.effective_user.id), config.BL_DB_PATH)
    bdb.record_feedback(opp.id, "edit_cancel", user_id=str(update.effective_user.id), source="callback", raw_payload=update.callback_query.data, db_path=config.BL_DB_PATH)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Edit cancelled for <code>{opp.alert_id}</code>.", reply_to_message_id=update.callback_query.message.message_id, parse_mode="HTML")

def _sync_regen_task(opp):
    import harvest_draft
    import json
    lead = {
        "id": opp.id,
        "url": opp.site_url or "",
        "domain": opp.site_domain or "",
        "type": opp.site_type or "forum",
        "target_title": opp.target_title or "",
        "target_excerpt": opp.target_excerpt or "",
        "discussion_intent": opp.opportunity_context or "",
        "question_type": "",
        "opportunity_context": opp.opportunity_context or "",
        "opportunity_freshness": opp.opportunity_freshness or "unknown",
        "posting_action": opp.posting_action or "reply",
        "platform": opp.site_domain or "",
        "raw_json": "{}",
    }
    project_url = opp.project_url or ""
    project = wdb.get_project_by_url(project_url, db_path=config.BL_DB_PATH) or {"project_url": project_url, "niche": "", "id": 0}
    run_dir, manifest_path, run_id = harvest_draft.build_run_bundle(project, [lead])
    ok = harvest_draft.invoke_ink(project, run_dir, manifest_path)
    if ok:
        posts_path = os.path.join(run_dir, "content", "posts.json")
        with open(posts_path, encoding="utf-8") as f:
            posts = json.load(f).get("posts") or []
        if posts:
            new_content = posts[0].get("content") or ""
            return {"success": True, "content": new_content}
    return {"success": False, "error": "Ink worker error or no content"}

async def handle_bl_regen(update, context, opp):
    if not opp: return
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"⏳ Regenerating reply for <code>{opp.alert_id}</code>... Please wait.", reply_to_message_id=update.callback_query.message.message_id, parse_mode="HTML")
    import asyncio
    
    try:
        result = await asyncio.to_thread(_sync_regen_task, opp)
        if result.get("success"):
            new_content = result["content"]
            bdb.save_content_version(opp.id, "regenerated", new_content, user_id=str(update.effective_user.id), db_path=config.BL_DB_PATH)
            bdb.record_feedback(opp.id, "regen", user_id=str(update.effective_user.id), source="callback", raw_payload=update.callback_query.data, db_path=config.BL_DB_PATH)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ Regenerated reply for <code>{opp.alert_id}</code>:\n\n<pre>{new_content[:3000]}</pre>", reply_to_message_id=update.callback_query.message.message_id, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Regeneration failed: {result.get('error')}", reply_to_message_id=update.callback_query.message.message_id)
    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Regeneration error: {e}", reply_to_message_id=update.callback_query.message.message_id)

def main():
    logger.info("Starting native Python Telegram Webhook Receiver...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    # Button Interface
    app.add_handler(CommandHandler("start", menu_command))
    app.add_handler(CommandHandler("menu", menu_command))
    # V1 Commands
    app.add_handler(CommandHandler("help", help_command))
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
