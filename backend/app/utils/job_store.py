import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

BASE_SESSIONS_DIR = Path(__file__).resolve().parent.parent.parent / ".sessions"
BASE_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_old_sessions(max_age_seconds: int = 3600) -> int:
    """Remove session directories older than max_age_seconds (default: 1 hour)."""
    now = time.time()
    removed = 0
    if not BASE_SESSIONS_DIR.exists():
        return 0
    for child in list(BASE_SESSIONS_DIR.iterdir()):
        if not child.is_dir():
            continue
        try:
            mtime = child.stat().st_mtime
            # Check meta.json mtime if present to reflect most recent activity
            meta_file = child / "meta.json"
            if meta_file.exists():
                mtime = max(mtime, meta_file.stat().st_mtime)
            if (now - mtime) > max_age_seconds:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except Exception:
            continue
    return removed


def create_session() -> str:
    cleanup_old_sessions(3600)
    session_id = uuid.uuid4().hex[:12]
    session_dir = BASE_SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    save_meta(session_id, {"session_id": session_id})
    return session_id


def get_session_dir(session_id: str) -> Path:
    safe_id = "".join(c for c in session_id if c.isalnum() or c in ("-", "_"))
    session_dir = BASE_SESSIONS_DIR / safe_id
    if not session_dir.exists():
        raise FileNotFoundError(f"Session '{session_id}' not found.")
    return session_dir


def save_text(session_id: str, filename: str, content: str) -> Path:
    path = get_session_dir(session_id) / filename
    path.write_text(content, encoding="utf-8")
    return path


def read_text(session_id: str, filename: str) -> Optional[str]:
    path = get_session_dir(session_id) / filename
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def get_file_path(session_id: str, filename: str) -> Path:
    return get_session_dir(session_id) / filename


def save_meta(session_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    path = get_session_dir(session_id) / "meta.json"
    current: Dict[str, Any] = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    current.update(updates)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def load_meta(session_id: str) -> Dict[str, Any]:
    path = get_session_dir(session_id) / "meta.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
