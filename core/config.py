"""Application configuration management."""
import json
import os
import sys

if getattr(sys, "frozen", False):
    # frozen (PyInstaller) mode: models/config live next to the exe
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODEL_BASE = os.path.join(APP_DIR, "models")
QWEN3_DIR = os.path.join(
    MODEL_BASE, "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25"
)
WHISPER_DIR = os.path.join(MODEL_BASE, "whisper")
OUTPUT_DIR = os.path.join(APP_DIR, "output")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")

DEFAULT_CONFIG = {
    "asr": {
        "lang_priority": "cn",  # "cn" = Qwen3-ASR primary; "en" = Whisper primary
        "qwen3": {
            "conv_frontend": os.path.join(QWEN3_DIR, "conv_frontend.onnx"),
            "encoder": os.path.join(QWEN3_DIR, "encoder.int8.onnx"),
            "decoder": os.path.join(QWEN3_DIR, "decoder.int8.onnx"),
            "tokenizer": os.path.join(QWEN3_DIR, "tokenizer"),
            "max_new_tokens": 128,
            "num_threads": 4,
        },
        "whisper": {
            "model": "tiny",  # tiny/base/small/medium (auto-download on first use)
            "model_dir": WHISPER_DIR,
            "device": "cpu",
            "compute_type": "int8",
            "language": "en",
        },
    },
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        "chunk_sec": 0.5,
        "silence_threshold": 0.02,
        "silence_dur_to_stop": 1.5,
        "max_segment_sec": 30,
        "device_index": None,  # None = default mic
    },
    "translate": {
        "mode": "local",  # "local" | "cloud"
        "local": {"engine": "argos"},  # argos
        "cloud": {
            "provider": "openai",  # openai | deepl
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "deepl_api_key": "",
        },
        "auto": True,  # auto: translate other-language text to primary output lang
        "target_lang": "zh",  # primary display language
    },
    "summary": {
        "engine": "local",  # local | cloud
        "cloud": {
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        },
        "max_lines": 1000,
    },
    "email": {
        "smtp_host": "",
        "smtp_port": 465,
        "smtp_user": "",
        "smtp_password": "",
        "use_ssl": True,
        "from_addr": "",
        # Recipient: config email.to (or to_addrs), else env MEETING_EMAIL_TO.
        # Never put SMTP passwords / app passwords in git.
        "to": "gztonyhuang@outlook.com",
        "to_addrs": ["gztonyhuang@outlook.com"],
        "max_attach_bytes": 26214400,  # Gmail ~25MB for txts + speech MP3 (WAV stays local)
    },
    "lark": {
        # webhook_url: leave empty here. Prefer env LARK_WEBHOOK_URL.
        # If you put a URL in local config.json, that file is gitignored.
        "webhook_url": "",
        "enabled": True,
        "timeout_sec": 15,
    },
    "ui": {
        "theme": "clam",
    },
}


def ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(WHISPER_DIR, exist_ok=True)


def load_config(path=CONFIG_FILE):
    ensure_dirs()
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            _merge(cfg, user_cfg)
        except Exception:
            pass
    return cfg


def save_config(cfg, path=CONFIG_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _merge(base, override):
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _merge(base[k], v)
        else:
            base[k] = v


def resource_path(rel):
    """Return absolute path for a project resource (works for frozen exe too)."""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), rel)
    return os.path.join(APP_DIR, rel)
