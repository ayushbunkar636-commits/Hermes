import os
import json
import time
import uuid
import logging
import config
import threading
import urllib.request
import urllib.error
from urllib.error import URLError, HTTPError
import config

BIFROST_URL = config.BIFROST_BASE_URL
DEFAULT_MODEL = "vertex/gemini-2.5-flash-lite"
DB_PATH = config.BL_DB_PATH

logger = logging.getLogger("hermes_client")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(levelname)s] hermes_client: %(message)s"))
    logger.addHandler(ch)

class HermesMetrics:
    @staticmethod
    def record_call(agent_id: str, duration: float, success: bool, retries: int):
        status = "SUCCESS" if success else "FAILED"
        logger.info(f"METRIC | Agent: {agent_id} | Status: {status} | Latency: {duration:.2f}s | Retries: {retries}")

class HermesAPIError(Exception):
    pass

def _call_bifrost_with_retry(prompt: str, model: str, timeout: int = 60, max_retries: int = 3, tools: list = None, stream: bool = False):
    url = f"{BIFROST_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 2000,
        "stream": stream
    }
    
    if tools:
        payload["tools"] = []
        for t in tools:
            if hasattr(t, "__hermes_schema__"):
                payload["tools"].append({
                    "type": "function",
                    "function": {
                        "name": getattr(t, "__hermes_name__", t.__name__),
                        "parameters": getattr(t, "__hermes_schema__", {})
                    }
                })
    
    data_encoded = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_encoded,
        headers={
            "Content-Type": "application/json", 
            "Authorization": f"Bearer {os.environ.get('HERMES_API_KEY')}",
            "x-bf-vk": str(os.environ.get('HERMES_API_KEY'))
        },
        method="POST",
    )
    
    for attempt in range(max_retries):
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            if stream:
                def iter_stream():
                    with resp:
                        for line in resp:
                            if line.strip():
                                yield line.decode("utf-8")
                return iter_stream()
            
            with resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                return data["choices"][0]["message"]
                
        except HTTPError as e:
            error_body = e.read().decode("utf-8", errors="ignore")
            logger.warning(f"Bifrost HTTP Error {e.code} on attempt {attempt+1}/{max_retries}. Body: {error_body[:500]}")
            if e.code not in [502, 503, 504, 429]:
                raise HermesAPIError(f"Fatal HTTP Error {e.code}: {error_body[:200]}")
        except (URLError, TimeoutError) as e:
            logger.warning(f"Bifrost Network/Timeout Error on attempt {attempt+1}/{max_retries}: {e}")
        
        if attempt < max_retries - 1:
            sleep_time = 2 ** attempt
            logger.info(f"Retrying in {sleep_time} seconds...")
            time.sleep(sleep_time)
            
    raise HermesAPIError(f"Exhausted {max_retries} retries connecting to Bifrost.")

class WorkerManager:
    @staticmethod
    def spawn_worker(agent_id: str, target_func, *args, **kwargs) -> str:
        trace_id = f"hermes-spawn-{uuid.uuid4().hex[:8]}"
        def safe_wrapper():
            try:
                target_func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Worker {agent_id} ({trace_id}) failed: {e}")
        threading.Thread(target=safe_wrapper, name=trace_id, daemon=True).start()
        return trace_id

class SessionManager:
    @staticmethod
    def get_or_create_session(chat_id: str, user_id: str) -> dict:
        try:
            conn = config.get_db_connection()
            c = conn.cursor()
            c.execute("CREATE TABLE IF NOT EXISTS onboard_sessions (chat_id TEXT, user_id TEXT, step TEXT, PRIMARY KEY(chat_id, user_id))")
            c.execute("SELECT step FROM onboard_sessions WHERE chat_id=%s AND user_id=%s LIMIT 1", (str(chat_id), str(user_id)))
            row = c.fetchone()
            if row:
                step = row[0]
            else:
                step = "new"
                c.execute("INSERT INTO onboard_sessions (chat_id, user_id, step) VALUES (%s, %s, %s)", (str(chat_id), str(user_id), step))
                conn.commit()
            conn.close()
            return {"chat_id": chat_id, "user_id": user_id, "step": step}
        except Exception as e:
            logger.error(f"SessionManager DB error: {e}")
            return {"chat_id": chat_id, "user_id": user_id, "step": "error"}

def run_agent(agent_id: str, prompt: str, context: dict = None, timeout: int = 60, tools: list = None, stream: bool = False, **kwargs):
    start_time = time.time()
    success = False
    try:
        response = _call_bifrost_with_retry(prompt, DEFAULT_MODEL, timeout=timeout, tools=tools, stream=stream)
        success = True
        
        if stream:
            return {"status": "success", "stream": response}
            
        text = response.get("content", "")
        if "tool_calls" in response:
            logger.info(f"LLM invoked tool calls: {response['tool_calls']}")
            
        if context and "result_path" in context:
            if text.startswith("```"):
                text = text.split("```", 2)[1] if text.count("```") >= 2 else text
                text = text.lstrip("json").strip()
            try:
                parsed = json.loads(text)
                with open(context["result_path"], "w", encoding="utf-8") as f:
                    json.dump({"status": "ok", "scores": parsed.get("scores", [])}, f)
            except Exception:
                with open(context["result_path"], "w", encoding="utf-8") as f:
                    json.dump({"status": "error", "scores": []}, f)
                    
        return {"status": "success", "response": text, "tool_calls": response.get("tool_calls")}
    except HermesAPIError as he:
        logger.error(f"run_agent failed: {he}")
        return {"status": "failed", "error": str(he)}
    finally:
        HermesMetrics.record_call(agent_id, time.time() - start_time, success, retries=0)

def run_worker(worker_id: str, task_payload: dict, timeout_seconds: int = 120, tools: list = None, **kwargs):
    start_time = time.time()
    success = False
    try:
        prompt = task_payload.get("task", "Draft content")
        response = _call_bifrost_with_retry(prompt, DEFAULT_MODEL, timeout=timeout_seconds, tools=tools)
        success = True
        
        text = response.get("content", "")
        if worker_id == "bl-content" and "run_dir" in task_payload:
            posts_path = os.path.join(task_payload["run_dir"], "content", "posts.json")
            os.makedirs(os.path.dirname(posts_path), exist_ok=True)
            if text.startswith("```"):
                text = text.split("```", 2)[1] if text.count("```") >= 2 else text
                text = text.lstrip("json").strip()
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "status" not in parsed:
                    parsed["status"] = "ok"
                with open(posts_path, "w", encoding="utf-8") as f:
                    json.dump(parsed, f)
            except Exception:
                with open(posts_path, "w", encoding="utf-8") as f:
                    json.dump({"status": "error", "posts": []}, f)
                    
        return {"status": "success"}
    except Exception as he:
        return {"status": "failed", "error": str(he)}
    finally:
        HermesMetrics.record_call(worker_id, time.time() - start_time, success, retries=0)

def spawn(agent_id: str, mode: str = "run", runtime: str = "subagent", context: str = "isolated", task: str = "") -> str:
    return WorkerManager.spawn_worker(agent_id, run_agent, agent_id=agent_id, prompt=task)

def yield_result(status: str, data: dict = None) -> None:
    pass

def tool(name: str, schema: dict = None):
    def decorator(func):
        func.__hermes_tool__ = True
        func.__hermes_name__ = name
        func.__hermes_schema__ = schema
        return func
    return decorator

def session(chat_id: str, user_id: str, **kwargs):
    return SessionManager.get_or_create_session(chat_id, user_id)
