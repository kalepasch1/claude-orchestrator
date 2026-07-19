"""Cross-agent conversation memory — pass compressed transcripts between retries."""
import sys, os, re, json, time, threading, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("conversation_memory")
try:
    import db
except Exception:
    db = None

ENABLED = os.environ.get("ORCH_CONVERSATION_MEMORY_ENABLED", "true").lower() in ("true", "1", "yes")
MAX_MEMORY_CHARS = int(os.environ.get("ORCH_CONVERSATION_MEMORY_MAX", "3000"))

_ACTION_PAT = re.compile(r"(?:Created|Modified|Edited|Added|Removed|Deleted|Installed|Fixed)\s+(.{10,100})", re.IGNORECASE)
_ERROR_PAT = re.compile(r"(?:Error|FAIL|Exception|error):\s*(.{10,150})")
_FILE_PAT = re.compile(r"[\w/.-]+\.\w{1,6}")
_APPROACH_PAT = re.compile(r"(?:I'll|Let me|approach|strategy|plan)\s+(.{10,80})", re.IGNORECASE)


class _ConversationMemory:
    def __init__(self):
        self._lock = threading.Lock()
        self._memories = {}  # task_id -> [{"attempt": int, "summary": str}]
        self._stats = {"memories_stored": 0, "memories_injected": 0, "chars_saved": 0}

    def compress_transcript(self, task_id, attempt, agent_output, model, success):
        """Compress agent output into a concise memory entry."""
        if not ENABLED:
            return ""
        out = agent_output or ""
        lines = []
        lines.append(f"Attempt {attempt} ({model}, {'SUCCESS' if success else 'FAILED'}):")
        # Extract actions taken
        actions = [m.group(1).strip() for m in _ACTION_PAT.finditer(out)][:5]
        if actions:
            lines.append(f"  Actions: {'; '.join(actions)}")
        # Extract errors encountered
        errors = [m.group(1).strip() for m in _ERROR_PAT.finditer(out)][:3]
        if errors:
            lines.append(f"  Errors: {'; '.join(errors)}")
        # Extract files touched
        files = list(set(_FILE_PAT.findall(out)))
        real_files = [f for f in files if "/" in f and not f.startswith("http")][:8]
        if real_files:
            lines.append(f"  Files: {', '.join(real_files)}")
        # Extract approach
        approaches = [m.group(1).strip() for m in _APPROACH_PAT.finditer(out)][:2]
        if approaches:
            lines.append(f"  Approach: {approaches[0]}")
        summary = "\n".join(lines)
        # Cap per-entry length
        if len(summary) > MAX_MEMORY_CHARS // 3:
            summary = summary[:MAX_MEMORY_CHARS // 3]
        return summary

    def store(self, task_id, attempt, agent_output, model, success):
        if not ENABLED:
            return
        summary = self.compress_transcript(task_id, attempt, agent_output, model, success)
        if not summary:
            return
        with self._lock:
            entries = self._memories.setdefault(task_id, [])
            entries.append({"attempt": attempt, "summary": summary, "success": success})
            # Keep only last 3 attempts
            if len(entries) > 3:
                entries[:] = entries[-3:]
            self._stats["memories_stored"] += 1

    def recall(self, task_id):
        """Retrieve compressed memory of prior attempts for this task."""
        if not ENABLED:
            return None
        with self._lock:
            entries = self._memories.get(task_id)
        if not entries:
            return None
        return entries

    def inject_memory(self, prompt, task_id):
        """Add prior attempt memories to the prompt so agent doesn't repeat mistakes."""
        entries = self.recall(task_id)
        if not entries:
            return prompt
        memory_lines = ["## Prior Attempt History",
                        "Previous agents attempted this task. Learn from their experience:\n"]
        total_chars = 0
        for entry in entries:
            s = entry["summary"]
            if total_chars + len(s) > MAX_MEMORY_CHARS:
                break
            memory_lines.append(s)
            total_chars += len(s)
        if not entries[-1].get("success"):
            memory_lines.append("\nDo NOT repeat the same approaches that failed. Try a different strategy.")
        block = "\n".join(memory_lines)
        with self._lock:
            self._stats["memories_injected"] += 1
            self._stats["chars_saved"] += total_chars
        return prompt + "\n\n" + block

    def clear(self, task_id):
        with self._lock:
            self._memories.pop(task_id, None)

    def stats(self):
        with self._lock:
            return dict(self._stats, enabled=ENABLED, tasks_tracked=len(self._memories))


_mem = _ConversationMemory()

def compress_transcript(task_id, attempt, agent_output, model="", success=False):
    try: return _mem.compress_transcript(task_id, attempt, agent_output, model, success)
    except Exception: return ""

def store(task_id, attempt, agent_output, model="", success=False):
    try: _mem.store(task_id, attempt, agent_output, model, success)
    except Exception: pass

def recall(task_id):
    try: return _mem.recall(task_id)
    except Exception: return None

def inject_memory(prompt, task_id):
    try: return _mem.inject_memory(prompt, task_id)
    except Exception: return prompt

def clear(task_id):
    try: _mem.clear(task_id)
    except Exception: pass

def stats():
    try: return _mem.stats()
    except Exception: return {"enabled": False}
