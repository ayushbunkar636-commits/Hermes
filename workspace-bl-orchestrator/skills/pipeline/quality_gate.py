#!/usr/bin/env python3
"""quality_gate.py — Cheap-LLM relevance/spam gate over the top-N scored leads.

Hybrid scoring:
  1. Deterministic math (score_opportunities.py) scores EVERY lead for free.
  2. Only the top-N survivors reach THIS gate, where bl-gate (or direct API fallback)
     reads title/excerpt and returns a 0-10 relevance/spam judgment.

Primary path: OpenClaw agent `bl-gate` (Nova Lite).
Fallback: direct Bifrost HTTP (Nova Lite → MiniMax).
Fail-open: if all paths fail, leads pass with gate_reason='gate_unavailable'.

Used as a library by nexus_daemon.py:
    from quality_gate import gate_leads
    judged = gate_leads(leads, niche="saas", project_desc="...", threshold=6.0)

CLI (manual testing):
    python3 quality_gate.py --in leads.json --niche "saas" --threshold 6 --out gated.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)
from pipeline_tz import now_compact  # noqa: E402
from pipeline_log import plog_info, plog_verbose, truncate  # noqa: E402

DEFAULT_BASE_URL = os.environ.get("BIFROST_BASE_URL", "https://placing-reliability-container-oecd.trycloudflare.com/v1")
DEFAULT_MODEL = os.environ.get("BL_GATE_MODEL", "vertex/gemini-2.5-flash")
DEFAULT_MODEL_FALLBACK = os.environ.get("BL_GATE_MODEL_FALLBACK", "vertex/gemini-2.5-flash")
DEFAULT_THRESHOLD = float(os.environ.get("BL_GATE_THRESHOLD", "6.0"))
DEFAULT_TIMEOUT = int(os.environ.get("BL_GATE_TIMEOUT", "60"))
GATE_USE_AGENT = os.environ.get("BL_GATE_USE_AGENT", "true").lower() in ("1", "true", "yes")
GATE_AGENT = os.environ.get("BL_GATE_AGENT", "bl-gate")
PROFILE = os.environ.get("BL_PROFILE", "backlink")

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

_SYSTEM_PROMPT = (
    "You are a strict backlink-opportunity quality gate and business impact predictor. "
    "For each candidate thread, decide how good a fit it is for placing a genuinely helpful reply. "
    "Reward: on-topic discussions, recent activity. Penalize: spam, off-topic, listicles. "
    "Reject non-English content (score 0). "
    "You must ALSO evaluate intent and spam markers based on the full text and SEO metrics provided. "
    "Return STRICT JSON ONLY matching this exact schema:\n"
    '{"scores":[{"i":<index>,"score":<0-10 number>,"reason":"<short>","is_appropriate":<bool>,"is_spam":<bool>,"is_active":<bool>,"has_commercial_intent":<bool>,"reject_opportunity":<bool>,"discussion_intent":"<e.g. debugging/recommendation>","question_type":"<e.g. how-to>","impact":{"traffic":"<e.g. 12K>","seo":"<Low/Medium/High>","lead_quality":"<e.g. Excellent>","business_impact":"<e.g. High>","revenue":"<e.g. $4500>","priority":"<Low/Medium/High>"}}]}\n'
    "No prose outside the JSON."
)


def _log(msg: str) -> None:
    plog_info("gate", msg)


def _build_user_prompt(leads: list[dict], niche: str, project_desc: str) -> str:
    lines = [
        f"PROJECT NICHE: {niche}",
        f"PROJECT DESCRIPTION: {project_desc or '(none provided)'}",
        "",
        "CANDIDATES (judge each, keep indexes):",
    ]
    for i, lead in enumerate(leads):
        title = (lead.get("target_title") or "").strip()
        url = lead.get("url") or ""
        fresh = lead.get("opportunity_freshness") or "unknown"
        
        # Extract full HTML from raw_json if possible, fallback to excerpt
        raw_json_str = lead.get("raw_json", "{}")
        try:
            raw_dict = json.loads(raw_json_str) if isinstance(raw_json_str, str) else raw_json_str
            html = raw_dict.get("raw_html", "")
            if html and BeautifulSoup:
                soup = BeautifulSoup(html, "html.parser")
                text = soup.get_text(separator=" ", strip=True)
                excerpt = text[:4000]
            else:
                excerpt = (lead.get("target_excerpt") or "").strip()[:1000]
            
            dofollow = raw_dict.get("is_dofollow", True)
            obl = raw_dict.get("outbound_link_count", 0)
        except Exception:
            excerpt = (lead.get("target_excerpt") or "").strip()[:1000]
            dofollow = True
            obl = 0
            
        lines.append(
            f"[{i}] title: {title!r} | freshness: {fresh} | url: {url} | dofollow: {dofollow} | OBL: {obl}\n     text: {excerpt!r}"
        )
    lines.append("")
    lines.append('Respond with JSON: {"scores":[{"i":0,"score":7.5,"reason":"...", "is_spam":false, ...}]}')
    return "\n".join(lines)


def _call_llm(
    messages: list[dict], model: str, base_url: str, timeout: int
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 1500,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('HERMES_API_KEY')}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    return data["choices"][0]["message"]["content"]


def _parse_scores(content: str, n: int) -> dict[int, dict]:
    """Extract {index: {score, reason}} from a (possibly noisy) LLM response."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        text = text.lstrip("json").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in gate response")
    obj = json.loads(text[start : end + 1])
    out: dict[int, dict] = {}
    for item in obj.get("scores", []):
        try:
            res_idx = int(item.get("i", -1))
            score = float(item.get("score", 0.0))
            reason = str(item.get("reason") or "").strip()
            impact = item.get("impact") or {}
            if 0 <= res_idx < n:
                out[res_idx] = {
                    "score": max(0.0, min(10.0, score)),
                    "reason": reason[:200],
                    "impact": impact,
                    "is_appropriate": bool(item.get("is_appropriate", True)),
                    "is_spam": bool(item.get("is_spam", False)),
                    "is_active": bool(item.get("is_active", True)),
                    "has_commercial_intent": bool(item.get("has_commercial_intent", False)),
                    "reject_opportunity": bool(item.get("reject_opportunity", False)),
                    "discussion_intent": str(item.get("discussion_intent", "")),
                    "question_type": str(item.get("question_type", ""))
                }
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _apply_scores(leads: list[dict], scores: dict[int, dict], threshold: float) -> list[dict]:
    for i, lead in enumerate(leads):
        judged = scores.get(i)
        if judged is None:
            lead["gate_score"] = None
            lead["gate_reason"] = "gate_no_verdict"
            lead["gate_passed"] = True
        else:
            lead["gate_score"] = judged["score"]
            lead["gate_reason"] = judged["reason"]
            lead["impact"] = judged["impact"]
            lead["discussion_intent"] = judged["discussion_intent"]
            lead["question_type"] = judged["question_type"]
            lead["has_commercial_intent"] = judged["has_commercial_intent"]
            
            if judged["reject_opportunity"] or judged["is_spam"]:
                lead["gate_passed"] = False
                lead["gate_reason"] = "rejected_by_ai: " + judged["reason"]
            else:
                lead["gate_passed"] = judged["score"] >= threshold
        plog_verbose(
            "gate", "gate_lead",
            url=truncate(lead.get("url") or "", 120),
            gate_score=lead.get("gate_score"),
            passed=lead.get("gate_passed"),
            reason=truncate(lead.get("gate_reason") or ""),
        )
    return leads


def _fail_open(leads: list[dict], reason: str) -> list[dict]:
    for lead in leads:
        lead["gate_score"] = None
        lead["gate_reason"] = reason[:200]
        lead["gate_passed"] = True
    return leads


def _build_gate_run_dir(
    project_url: str,
    leads: list[dict],
    *,
    niche: str,
    project_desc: str,
    threshold: float,
) -> tuple[str, str, str]:
    ts = now_compact()
    run_dir = f"/tmp/backlink-gate-{os.getpid()}-{ts}"
    os.makedirs(run_dir, exist_ok=True)
    batch_path = os.path.join(run_dir, "gate_batch.json")
    result_path = os.path.join(run_dir, "gate_result.json")
    batch = {
        "niche": niche,
        "project_url": project_url,
        "project_desc": project_desc,
        "threshold": threshold,
        "candidates": [
            {
                "i": i,
                "lead_id": lead.get("id"),
                "url": lead.get("url") or "",
                "target_title": lead.get("target_title") or "",
                "target_excerpt": (lead.get("target_excerpt") or "")[:400],
                "opportunity_freshness": lead.get("opportunity_freshness") or "unknown",
            }
            for i, lead in enumerate(leads)
        ],
    }
    with open(batch_path, "w", encoding="utf-8") as f:
        json.dump(batch, f, indent=2, ensure_ascii=False)
    return run_dir, batch_path, result_path


def _invoke_gate_agent(
    run_dir: str,
    batch_path: str,
    result_path: str,
    *,
    niche: str,
    project_url: str,
    project_desc: str,
    threshold: float,
    timeout: int,
) -> bool:
    task = (
        "Follow your SOUL. Score each candidate in the gate batch.\n"
        f"RUN_DIR={run_dir}\n"
        f"Read batch from: {batch_path}\n"
        f"Write results to: {result_path}\n"
        f"Project URL: {project_url}\n"
        f"Niche: {niche}\n"
        f"Project description: {project_desc}\n"
        f"Pass threshold: {threshold}\n"
        "Do NOT return JSON in chat. Yield SUCCESS only."
    )
    import hermes_client
    try:
        hermes_client.run_agent(
            agent_id=GATE_AGENT,
            prompt=task,
            context={"run_dir": run_dir, "batch_path": batch_path, "result_path": result_path},
            timeout=timeout
        )
        return os.path.isfile(result_path)
    except Exception as e:
        _log(f"agent failed via hermes: {e}")
        return False


def _read_gate_result(result_path: str, n: int) -> dict[int, dict]:
    with open(result_path, encoding="utf-8") as f:
        obj = json.load(f)
    if obj.get("status") != "ok":
        raise ValueError(f"gate_result status={obj.get('status')!r}")
    scores_raw = obj.get("scores")
    if not isinstance(scores_raw, list) or not scores_raw:
        raise ValueError("gate_result scores empty")
    out: dict[int, dict] = {}
    for item in scores_raw:
        try:
            res_idx = int(item.get("i", -1))
            score = float(item.get("score", 0.0))
            reason = str(item.get("reason") or "").strip()
            impact = item.get("impact") or {}
            if 0 <= res_idx < n:
                out[res_idx] = {
                    "score": max(0.0, min(10.0, score)),
                    "reason": reason[:200],
                    "impact": impact
                }
        except (KeyError, ValueError, TypeError):
            continue
    if not out:
        raise ValueError("no valid scores in gate_result.json")
    return out


def _gate_via_api(
    leads: list[dict],
    *,
    niche: str,
    project_desc: str,
    threshold: float,
    model: str,
    fallback_model: str,
    base_url: str,
    timeout: int,
) -> list[dict] | None:
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(leads, niche, project_desc)},
    ]
    models = [model]
    if fallback_model and fallback_model != model:
        models.append(fallback_model)
    last_err: Exception | None = None
    for m in models:
        try:
            content = _call_llm(messages, m, base_url, timeout)
            scores = _parse_scores(content, len(leads))
            return _apply_scores(leads, scores, threshold)
        except Exception as e:  # noqa: BLE001
            last_err = e
            _log(f"direct API model={m} failed: {e}")
    if last_err:
        _log(f"direct API exhausted: {last_err}")
    return None


def gate_leads(
    leads: list[dict],
    *,
    niche: str = "",
    project_desc: str = "",
    project_url: str = "",
    threshold: float = DEFAULT_THRESHOLD,
    model: str = DEFAULT_MODEL,
    fallback_model: str = DEFAULT_MODEL_FALLBACK,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = DEFAULT_TIMEOUT,
    use_agent: bool = GATE_USE_AGENT,
) -> list[dict]:
    """Return leads annotated with gate_score, gate_reason, gate_passed.

    Fail-open: on total failure every lead gets gate_passed=True,
    gate_score=None, gate_reason='gate_unavailable'.
    """
    if not leads:
        return []

    path = "agent" if use_agent else "api"
    plog_verbose(
        "gate", "gate_batch",
        project_url=project_url or None,
        leads=len(leads),
        threshold=threshold,
        path=path,
    )

    if use_agent:
        run_dir, batch_path, result_path = _build_gate_run_dir(
            project_url, leads, niche=niche, project_desc=project_desc, threshold=threshold,
        )
        if _invoke_gate_agent(
            run_dir, batch_path, result_path,
            niche=niche, project_url=project_url, project_desc=project_desc,
            threshold=threshold, timeout=timeout,
        ):
            try:
                scores = _read_gate_result(result_path, len(leads))
                return _apply_scores(leads, scores, threshold)
            except Exception as e:  # noqa: BLE001
                _log(f"invalid gate_result.json: {e}")
        _log("agent failed, falling back to direct API")

    result = _gate_via_api(
        leads, niche=niche, project_desc=project_desc, threshold=threshold,
        model=model, fallback_model=fallback_model, base_url=base_url, timeout=timeout,
    )
    if result is not None:
        return result
    return _fail_open(leads, "gate_unavailable")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cheap-LLM relevance/spam gate over top-N leads")
    parser.add_argument("--in", required=True, dest="in_path")
    parser.add_argument("--out", dest="out_path", default=None)
    parser.add_argument("--niche", default="")
    parser.add_argument("--project-desc", default="", dest="project_desc")
    parser.add_argument("--project-url", default="", dest="project_url")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--no-agent", action="store_true", help="skip bl-gate agent; direct API only")
    args = parser.parse_args()

    with open(args.in_path, encoding="utf-8") as f:
        data = json.load(f)
    leads = data.get("leads", data) if isinstance(data, dict) else data

    judged = gate_leads(
        leads, niche=args.niche, project_desc=args.project_desc,
        project_url=args.project_url, threshold=args.threshold, model=args.model,
        use_agent=not args.no_agent,
    )
    passed = sum(1 for l in judged if l.get("gate_passed"))

    if args.out_path:
        os.makedirs(os.path.dirname(os.path.abspath(args.out_path)), exist_ok=True)
        with open(args.out_path, "w", encoding="utf-8") as f:
            json.dump({"leads": judged}, f, indent=2, ensure_ascii=False)

    print(f"GATE_OK: judged={len(judged)} passed={passed} threshold={args.threshold}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
