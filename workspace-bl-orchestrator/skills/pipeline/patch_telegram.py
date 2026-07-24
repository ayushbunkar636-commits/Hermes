import os
import re

FILE_PATH = "d:\\Yash Coding2\\internship\\openclaw-backlink-full-20260716\\.openclaw-backlink\\workspace-bl-orchestrator\\skills\\pipeline\\telegram_router.py"

with open(FILE_PATH, "r", encoding="utf-8") as f:
    code = f.read()

# CHUNK 1: handle_message replacements
old_handle_msg = """    else:
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
    conn.close()"""

new_handle_msg = """    else:
        text = update.message.text.strip()
        import re
        alert_match = re.search(r"\\bbl-([A-Za-z0-9_-]+(?:-[A-Za-z0-9_-]+)*)\\b", text)
        alert_id = alert_match.group(0) if alert_match else None
        
        if alert_id:
            opp = bdb.lookup_by_alert_id(alert_id, config.BL_DB_PATH)
            if opp:
                class DummyQuery:
                    def __init__(self, data, message):
                        self.data = data
                        self.message = message
                if re.match(r"^(bl_approve|approve)\\s*$", text, re.IGNORECASE):
                    update.callback_query = DummyQuery(f'bl_approve:{alert_id}', update.message)
                    await handle_bl_approve(update, context, opp)
                elif re.match(r"^(bl_reject|reject)\\s*$", text, re.IGNORECASE):
                    update.callback_query = DummyQuery(f'bl_reject:{alert_id}', update.message)
                    await handle_bl_reject(update, context, opp)
                elif re.match(r"^(bl_edit|edit)\\s*$", text, re.IGNORECASE):
                    update.callback_query = DummyQuery(f'bl_edit:{alert_id}', update.message)
                    await handle_bl_edit(update, context, opp)
    conn.close()"""

code = code.replace(old_handle_msg, new_handle_msg)

# CHUNK 2: handle_callback replacements
old_handle_cb = """    elif query.data.startswith("bl_"):
        await query.answer()
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
        ])"""

new_handle_cb = """    elif query.data.startswith("bl_"):
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
            await handle_bl_regen(update, context, opp)"""

code = code.replace(old_handle_cb, new_handle_cb)

# CHUNK 3: handle_document replacements
old_handle_doc = """    else:
        conn.close()
        file_id = update.message.document.file_id
        logger.info(f"Received document upload with ID: {file_id}")
        await update.message.reply_text("File upload received and routed natively via Hermes.")"""

new_handle_doc = """    else:
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
                    def normalize_md(text): return "\\n".join([ln.rstrip() for ln in text.replace("\\r\\n", "\\n").split("\\n")]).strip()
                    
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
                        await update.message.reply_text(f"Edit saved for <code>{opp.alert_id}</code> — <b>{diff_summary}</b> changed.\\n\\nApply edit?", reply_markup=InlineKeyboardMarkup(keyboard), reply_to_message_id=reply_to.message_id, parse_mode="HTML")
                    return
        
        logger.info(f"Received document upload with ID: {file_id}")
        await update.message.reply_text("File upload received and routed natively via Hermes.")"""

code = code.replace(old_handle_doc, new_handle_doc)

# CHUNK 4: Add new functions before def main()

new_functions = """
# ─────────────────────────────────────────────────────────────────────────────
# NATIVE CARD FEEDBACK HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

def _format_diff_summary(baseline: str, edited: str) -> str:
    import difflib
    def normalize_md(text: str) -> str:
        return "\\n".join([ln.rstrip() for ln in text.replace("\\r\\n", "\\n").split("\\n")]).strip()
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
        caption = f"Edit <code>{opp.alert_id}</code>\\n\\nDownload -> edit -> save -> reply with corrected <b>.md</b> file."
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
    project = wdb.get_project(project_url, db_path=config.BL_DB_PATH) or {"project_url": project_url, "niche": "", "id": 0}
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
    escaped_id = str(opp.alert_id).replace("-com", "-c\u200bom").replace(".com", ".c\u200bom").replace("-org", "-o\u200brg").replace(".org", ".o\u200brg")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"⏳ Regenerating reply for <code>{escaped_id}</code>... Please wait.", reply_to_message_id=update.callback_query.message.message_id, parse_mode="HTML")
    import asyncio
    
    try:
        result = await asyncio.to_thread(_sync_regen_task, opp)
        if result.get("success"):
            new_content = result["content"]
            bdb.save_content_version(opp.id, "regenerated", new_content, user_id=str(update.effective_user.id), db_path=config.BL_DB_PATH)
            bdb.record_feedback(opp.id, "regen", user_id=str(update.effective_user.id), source="callback", raw_payload=update.callback_query.data, db_path=config.BL_DB_PATH)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ Regenerated reply for <code>{escaped_id}</code>:\\n\\n<pre>{new_content[:3000]}</pre>", reply_to_message_id=update.callback_query.message.message_id, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Regeneration failed: {result.get('error')}", reply_to_message_id=update.callback_query.message.message_id)
    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Regeneration error: {e}", reply_to_message_id=update.callback_query.message.message_id)

def main():"""

code = code.replace("def main():", new_functions)

with open(FILE_PATH, "w", encoding="utf-8") as f:
    f.write(code)
print("Patch applied successfully.")
