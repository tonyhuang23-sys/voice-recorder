"""Environment self-check and auto-download.

Detects whether the runtime can use the app:
  * required Python packages (source mode only; frozen exe bundles them)
  * Qwen3-ASR ONNX model files (conv_frontend / encoder / decoder / tokenizer)
  * faster-whisper model (auto-downloaded by faster_whisper on first use;
    this module can pre-download it to the model dir)

If a model is missing, it downloads it automatically from the official
sherpa-onnx model release.
"""
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.request

logger = logging.getLogger(__name__)

# Official sherpa-onnx Qwen3-ASR 0.6B int8 package (2026-03-25)
QWEN3_PACKAGE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "asr-models/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25.tar.bz2"
)
QWEN3_FOLDER = "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25"
QWEN3_FILES = [
    "conv_frontend.onnx",
    "encoder.int8.onnx",
    "decoder.int8.onnx",
    "tokenizer/vocab.json",
    "tokenizer/merges.txt",
    "tokenizer/tokenizer_config.json",
]

WHISPER_MODEL = "tiny"
WHISPER_MODEL_URLS = {
    "tiny": "https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/",
    "base": "https://huggingface.co/Systran/faster-whisper-base/resolve/main/",
    "small": "https://huggingface.co/Systran/faster-whisper-small/resolve/main/",
    "medium": "https://huggingface.co/Systran/faster-whisper-medium/resolve/main/",
}
WHISPER_FILES = ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"]


class EnvCheck:
    def __init__(self, cfg, on_progress=None, cancel_event=None):
        self.cfg = cfg
        self.on_progress = on_progress or (lambda msg, pct: None)
        self.cancel = cancel_event or threading.Event()

    # ---------- progress helper ----------
    def _report(self, msg, pct=None):
        try:
            self.on_progress(msg, pct)
        except Exception:
            pass

    # ---------- packages ----------
    def check_packages(self, auto_install=True):
        """Verify Python packages. Only meaningful in source mode."""
        if getattr(sys, "frozen", False):
            self._report("已打包运行环境(无需安装依赖)", 100)
            return True
        required = ["sherpa_onnx", "faster_whisper", "sounddevice",
                    "numpy", "yt_dlp", "argostranslate"]
        missing = []
        for mod in required:
            try:
                __import__(mod)
            except Exception:
                missing.append(mod)
        if not missing:
            self._report("Python 依赖完整", 100)
            return True
        if not auto_install:
            return False
        self._report(f"缺少依赖: {', '.join(missing)},开始自动安装...", 0)
        req = {
            "sherpa_onnx": "sherpa-onnx>=1.10.0",
            "faster_whisper": "faster-whisper>=1.2",
            "sounddevice": "sounddevice>=0.4.6",
            "numpy": "numpy>=1.24",
            "yt_dlp": "yt-dlp>=2024.1.1",
            "argostranslate": "argos-translate>=1.9",
        }
        for mod in missing:
            if self.cancel.is_set():
                return False
            pkg = req.get(mod, mod)
            self._report(f"正在安装 {pkg} ...", 30)
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "-q", pkg],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                logger.warning("pip install %s failed: %s", pkg, e)
                self._report(f"安装 {pkg} 失败:{e}", None)
        self._report("依赖安装完成", 100)
        return True

    # ---------- Qwen3-ASR ----------
    def qwen3_model_dir(self):
        from core.config import QWEN3_DIR
        return QWEN3_DIR

    def qwen3_ready(self):
        d = self.qwen3_model_dir()
        return all(os.path.exists(os.path.join(d, f)) for f in QWEN3_FILES)

    def download_qwen3(self):
        if self.qwen3_ready():
            self._report("Qwen3-ASR 模型已就绪", 100)
            return True
        target = os.path.dirname(self.qwen3_model_dir())
        os.makedirs(target, exist_ok=True)
        tmp = os.path.join(tempfile.gettempdir(), "qwen3asr.tar.bz2")
        self._report("Qwen3-ASR 模型缺失,开始下载(约838MB,可能需要几分钟)...", 5)
        try:
            self._download_file(QWEN3_PACKAGE_URL, tmp)
            self._report("下载完成,正在解压...", 80)
            with tarfile.open(tmp, "r:bz2") as t:
                t.extractall(target)
        except Exception as e:
            self._report(f"Qwen3-ASR 下载失败:{e}", None)
            logger.exception("qwen3 download failed")
            return False
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        if self.qwen3_ready():
            self._report("Qwen3-ASR 模型就绪", 100)
            return True
        self._report("Qwen3-ASR 解压后文件不完整,请手动放置模型", None)
        return False

    # ---------- whisper ----------
    def whisper_ready(self):
        """Check if the configured whisper model exists in the cache dir."""
        import faster_whisper.utils as fu
        model = self.cfg["asr"]["whisper"].get("model", WHISPER_MODEL)
        cache_dir = self.cfg["asr"]["whisper"].get("model_dir")
        if not cache_dir:
            cache_dir = fu.get_default_download_root()
        target = os.path.join(cache_dir, "models--Systran--faster-whisper-" + model)
        if os.path.isdir(target):
            snap = os.path.join(target, "snapshots")
            if os.path.isdir(snap):
                snapshots = [os.path.join(snap, d) for d in os.listdir(snap)
                             if os.path.isdir(os.path.join(snap, d))]
                if snapshots:
                    return os.path.exists(os.path.join(snapshots[0], "model.bin"))
        return False

    def download_whisper(self):
        model = self.cfg["asr"]["whisper"].get("model", WHISPER_MODEL)
        if self.whisper_ready():
            self._report(f"Whisper-{model} 模型已就绪", 100)
            return True
        self._report(f"Whisper-{model} 模型缺失,开始下载...", 50)
        try:
            from faster_whisper import download_model
            download_model(model, cache_dir=self.cfg["asr"]["whisper"]["model_dir"])
            self._report(f"Whisper-{model} 模型就绪", 100)
            return True
        except Exception as e:
            logger.exception("whisper download failed")
            self._report(f"Whisper 下载失败:{e}", None)
            return False

    # ---------- generic ----------
    def _download_file(self, url, dst):
        """Download with progress reporting. Blocks; checks cancel flag."""
        req = urllib.request.Request(url, headers={"User-Agent": "MeetingAssist/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            done = 0
            with open(dst, "wb") as f:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = 5 + int(done / total * 75)
                        self._report(f"正在下载 Qwen3-ASR ... {done//(1<<20)}MB/{total//(1<<20)}MB", pct)
                    if self.cancel.is_set():
                        raise RuntimeError("已取消")
        return dst

    # ---------- entry ----------
    def run_all(self, auto_install=True):
        """Run full environment check & repair. Returns (ok, messages)."""
        msgs = []
        ok_pkg = self.check_packages(auto_install)
        msgs.append(("Python 依赖", "OK" if ok_pkg else "FAIL"))

        ok_q = self.download_qwen3()
        msgs.append(("Qwen3-ASR 模型", "OK" if ok_q else "FAIL"))

        ok_w = self.download_whisper()
        msgs.append(("Whisper 模型", "OK" if ok_w else "FAIL"))

        all_ok = ok_pkg and ok_q and ok_w
        self._report("环境检查完成", 100)
        return all_ok, msgs
