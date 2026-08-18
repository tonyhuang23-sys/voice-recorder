"""Watch a folder for Zoom / Teams / Meet / Lark local recording files."""
import json
import logging
import os
import time

from .audio_source import MEDIA_EXTS
from .config import OUTPUT_DIR

logger = logging.getLogger(__name__)

SKIP_SUFFIXES = (".part", ".tmp", ".download", ".crdownload", ".partial")
SEEN_NAME = "watch_seen.json"


def seen_store_path():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return os.path.join(OUTPUT_DIR, SEEN_NAME)


def load_seen(path=None):
    path = path or seen_store_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_seen(seen, path=None):
    path = path or seen_store_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def is_media_file(path):
    name = os.path.basename(path)
    if not name or name.startswith("."):
        return False
    lower = name.lower()
    if any(lower.endswith(suf) for suf in SKIP_SUFFIXES):
        return False
    ext = os.path.splitext(lower)[1]
    return ext in MEDIA_EXTS


def iter_media_files(root):
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            path = os.path.join(dirpath, name)
            if is_media_file(path):
                yield path


def file_token(path):
    st = os.stat(path)
    return [int(st.st_mtime), int(st.st_size)]


def is_stable(path, settle_sec, now=None):
    try:
        st = os.stat(path)
    except OSError:
        return False
    now = time.time() if now is None else now
    return (now - st.st_mtime) >= float(settle_sec) and st.st_size > 0


def discover_ready(root, seen=None, settle_sec=8):
    """Return [(path, token), ...] for finished recordings not yet processed."""
    seen = seen if seen is not None else {}
    ready = []
    now = time.time()
    for path in iter_media_files(root):
        key = os.path.abspath(path)
        try:
            token = file_token(path)
        except OSError:
            continue
        prev = seen.get(key)
        if prev == token:
            continue
        if not is_stable(path, settle_sec, now=now):
            continue
        ready.append((path, token))
    ready.sort(key=lambda item: item[0])
    return ready


def mark_seen(seen, path, token=None):
    key = os.path.abspath(path)
    seen[key] = token or file_token(path)
    return seen
