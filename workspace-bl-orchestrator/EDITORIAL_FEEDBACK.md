# EDITORIAL_FEEDBACK.md — Backlink Card Feedback

Handles Telegram feedback on backlink cards sent after pipeline Step 4. **Not** a pipeline step — do not spawn subagents.

---

## When this applies

| Pattern | Example |
|---------|---------|
| Callback `bl_approve:` / `bl_reject:` / `bl_edit:` / `bl_edit_apply:` / `bl_edit_cancel:` | Button taps |
| Text | `APPROVE`, `EDIT`, `REJECT` (reply to card) |
| Document reply | `.md` file replying to bot's edit prompt |

---

## What to do

1. **Do NOT** start or continue the backlink pipeline.
2. **Do NOT** spawn subagents.
3. Run the handler:

```bash
python3 ~/.openclaw-backlink/workspace-bl-orchestrator/skills/pipeline/handle_card_feedback.py \
  --payload "<callback data if present>" \
  --message-text "<user text if present>" \
  --chat-id "<telegram chat id>" \
  --user-id "<telegram user id>" \
  --username "<telegram username if known>" \
  --reply-to-message-id "<replied-to message id if present>" \
  --document-file-id "<telegram file_id if document upload>" \
  --document-name "<original filename if document upload>"
```

4. If the handler already sent a Telegram reply, end turn silently.
5. If handler failed before replying, show stdout to the user.

---

## Pipeline vs feedback

| User says | Route |
|-----------|-------|
| `run backlink pipeline` + niche + URL | SOUL.md pipeline |
| APPROVE, EDIT, REJECT, callback taps, edit `.md` upload | This doc |

Cards and feedback run in the **backlink-agent** group (`config/telegram_card_config.json`).
