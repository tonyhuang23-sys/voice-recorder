"""Main Tkinter application window."""
import logging
import os
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox

from core.config import load_config, save_config, OUTPUT_DIR
from core.audio_source import (MicrophoneCapture, LoopbackCapture,
                               download_audio_from_link, list_input_devices)
from core.asr import ASRManager
from core.translator import Translator
from core.summarizer import Summarizer
from core.emailer import EmailSender
from core.pipeline import MeetingPipeline
from core import output
from ui.settings import SettingsDialog

logger = logging.getLogger(__name__)


class MeetingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.title("会议助手 MeetingAssist — 语音转写 · 翻译 · 摘要 · 邮件")
        self.geometry("1080x760")
        self.minsize(900, 620)

        self.pipeline = None
        self.asr_mgr = None
        self.translator = None
        self.trans_pairs = []       # list of {"src","dst"}
        self.transcript_lines = []  # (ts, speaker, text)
        self.meeting_title = "会议记录"

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(400, self._startup_env_hint)

    # ================= UI =================
    def _build_ui(self):
        # top control bar
        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill="x")

        ttk.Button(top, text="设置", command=self._open_settings).pack(side="left")
        ttk.Button(top, text="打开输出目录", command=self._open_output).pack(side="left", padx=4)
        ttk.Button(top, text="检查环境/下载模型",
                   command=self._check_env).pack(side="left", padx=4)

        self.var_source = tk.StringVar(value="麦克风")
        ttk.Label(top, text="音源:").pack(side="left", padx=(16, 2))
        ttk.Combobox(top, textvariable=self.var_source, width=14,
                     values=["麦克风", "系统声音(环回)", "链接下载"]).pack(side="left")

        self.var_link = tk.StringVar()
        ttk.Entry(top, textvariable=self.var_link, width=34).pack(side="left", padx=6)

        self.var_dev = tk.StringVar(value="默认")
        ttk.Label(top, text="设备:").pack(side="left")
        self.cmb_dev = ttk.Combobox(top, textvariable=self.var_dev, width=18)
        self.cmb_dev.pack(side="left", padx=4)
        self._refresh_devices()

        self.var_title = tk.StringVar(value="会议记录")
        ttk.Label(top, text="标题:").pack(side="left", padx=(8, 2))
        ttk.Entry(top, textvariable=self.var_title, width=18).pack(side="left")

        # buttons
        btns = ttk.Frame(self, padding=(8, 0))
        btns.pack(fill="x")
        self.btn_start = ttk.Button(btns, text="▶ 开始接听", command=self._start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(btns, text="■ 停止", command=self._stop,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.btn_summarize = ttk.Button(btns, text="生成摘要",
                                        command=self._make_summary)
        self.btn_summarize.pack(side="left", padx=6)
        self.btn_save = ttk.Button(btns, text="保存全部",
                                   command=self._save_all, state="disabled")
        self.btn_save.pack(side="left", padx=6)
        self.btn_email = ttk.Button(btns, text="发送摘要邮件",
                                    command=self._send_email, state="disabled")
        self.btn_email.pack(side="left", padx=6)

        self.var_status = tk.StringVar(value="就绪 — 请选择音源后点击[开始接听]")
        ttk.Label(self, textvariable=self.var_status, foreground="#0070c0",
                  padding=(10, 2)).pack(fill="x")

        # transcript area
        self.txt = scrolledtext.ScrolledText(self, wrap="word", font=("Microsoft YaHei", 11))
        self.txt.pack(fill="both", expand=True, padx=8, pady=4)
        self.txt.tag_configure("eng", foreground="#1a1a1a")
        self.txt.tag_configure("trans", foreground="#2e7d32")

    def _refresh_devices(self):
        devs = list_input_devices()
        names = ["默认"] + [f"[{i}] {n}" for i, n, *_ in devs]
        self.cmb_dev["values"] = names
        self._dev_list = devs

    def _log(self, text, tag=None):
        self.txt.insert("end", text + "\n", tag or "eng")
        self.txt.see("end")

    # ================= actions =================
    def _startup_env_hint(self):
        from core.env_check import EnvCheck, QWEN3_FILES
        from core.config import QWEN3_DIR
        missing = [f for f in QWEN3_FILES
                   if not os.path.exists(os.path.join(QWEN3_DIR, f))]
        if missing:
            self.var_status.set("提示: Qwen3-ASR 模型缺失,点击[检查环境/下载模型]自动下载")
        else:
            self.var_status.set("就绪 — 请选择音源后点击[开始接听]")

    def _check_env(self):
        from core.env_check import EnvCheck
        win = tk.Toplevel(self)
        win.title("环境检查")
        win.geometry("520x320")
        win.resizable(False, False)
        win.transient(self)
        lbl = ttk.Label(win, text="正在检查运行环境...", padding=(12, 8))
        lbl.pack(fill="x")
        bar = ttk.Progressbar(win, maximum=100)
        bar.pack(fill="x", padx=12)
        txt = scrolledtext.ScrolledText(win, height=10, state="disabled",
                                        font=("Microsoft YaHei", 10))
        txt.pack(fill="both", expand=True, padx=12, pady=(8, 4))
        btn_close = ttk.Button(win, text="关闭", command=win.destroy, state="disabled")
        btn_close.pack(pady=6)

        def report(msg, pct=None):
            def _ui():
                if pct is not None:
                    bar["value"] = pct
                txt.configure(state="normal")
                txt.insert("end", msg + "\n")
                txt.see("end")
                txt.configure(state="disabled")
            try:
                self.after(0, _ui)
            except Exception:
                pass

        def work():
            ok, msgs = EnvCheck(self.cfg, on_progress=report).run_all()
            report("---- 检查结果 ----")
            for name, st in msgs:
                report(f"{name}: {st}")
            report("环境就绪,可以开始会议。" if ok else "环境不完整,请查看上方错误。")
            self.after(0, lambda: btn_close.configure(state="normal"))

        threading.Thread(target=work, daemon=True).start()

    def _open_settings(self):
        SettingsDialog(self, self.cfg, on_save=lambda c: setattr(self, "cfg", c))

    def _open_output(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        os.startfile(OUTPUT_DIR)

    def _get_source(self):
        src = self.var_source.get()
        if src == "麦克风":
            idx = self._selected_dev_index()
            return MicrophoneCapture(self.cfg, device_index=idx)
        if src == "系统声音(环回)":
            idx = self._selected_dev_index() or _find_loopback()
            if idx is None:
                raise RuntimeError(
                    "未找到系统声音捕获设备(Stereo Mix)。请先在 Windows 声音设置中"
                    "启用'立体声混音',或安装 VB-Cable。")
            return LoopbackCapture(self.cfg, device_index=idx)
        if src == "链接下载":
            url = self.var_link.get().strip()
            if not url:
                raise RuntimeError("请粘贴会议链接(X Spaces / YouTube 等)")
            folder = os.path.join(OUTPUT_DIR, "downloads")
            os.makedirs(folder, exist_ok=True)
            self.var_status.set("正在下载链接音频,请稍候...")
            self.update_idletasks()
            wav = download_audio_from_link(url,
                    os.path.join(folder, "meeting_" + time.strftime("%Y%m%d_%H%M%S") + ".wav"))
            # return a file source (list of samples loaded fully)
            return FileSource(wav)
        raise RuntimeError("未知音源")

    def _selected_dev_index(self):
        sel = self.var_dev.get()
        if sel == "默认":
            return None
        try:
            idx = int(sel[sel.index("[") + 1:sel.index("]")])
            return idx
        except Exception:
            return None

    def _start(self):
        if self.pipeline and self.pipeline.running:
            return
        self.meeting_title = self.var_title.get().strip() or "会议记录"
        self.transcript_lines = []
        self.trans_pairs = []
        self.txt.delete("1.0", "end")
        self._log(f"===== 会议开始: {self.meeting_title} =====")
        self.var_status.set("正在启动...")
        self.update_idletasks()
        try:
            source = self._get_source()
            self.asr_mgr = ASRManager(self.cfg)
            self.translator = Translator(self.cfg)
            self.pipeline = MeetingPipeline(
                self.cfg, asr=self.asr_mgr, translator=self.translator,
                source=source, callback=self._on_pipeline)
            self.pipeline.start()
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            self.var_status.set("正在接听... (说/播放内容将自动转写)")
        except Exception as e:
            messagebox.showerror("启动失败", str(e), parent=self)
            self.var_status.set("启动失败: " + str(e))

    def _on_pipeline(self, kind, payload):
        self.after(0, lambda: self._ui_pipeline(kind, payload))

    def _ui_pipeline(self, kind, payload):
        if kind == "line":
            ts, speaker, text = payload["ts"], payload["speaker"], payload["text"]
            self.transcript_lines.append((ts, speaker, text))
            self._log(f"[{ts}] {text}")
        elif kind == "trans":
            self.trans_pairs.append(payload)
            self._log(f"   ↳ {payload['dst']}", "trans")
        elif kind == "status":
            if payload:
                self.var_status.set(payload)
            else:
                self.var_status.set("正在接听...")

    def _stop(self):
        if self.pipeline:
            self.pipeline.stop()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_save.config(state="normal")
        self.var_status.set("已停止 — 共 %d 句。可生成摘要或保存。" % len(self.transcript_lines))

    def _make_summary(self):
        if not self.transcript_lines:
            messagebox.showinfo("提示", "暂无转写内容", parent=self)
            return
        self.var_status.set("正在生成摘要...")
        self.update_idletasks()
        def work():
            try:
                summ = Summarizer(self.cfg).summarize(
                    self.transcript_lines, title=self.meeting_title)
                self.after(0, lambda: self._show_summary(summ))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("摘要失败", str(e), parent=self))
        threading.Thread(target=work, daemon=True).start()

    def _show_summary(self, summ):
        top = tk.Toplevel(self)
        top.title("会议摘要")
        top.geometry("720x560")
        txt = scrolledtext.ScrolledText(top, wrap="word", font=("Microsoft YaHei", 11))
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        txt.insert("1.0", summ)
        txt.config(state="disabled")
        self._last_summary = summ
        self.var_status.set("摘要已生成")
        messagebox.showinfo("摘要", "摘要已生成,可在新窗口查看。发送邮件前请先保存。", parent=self)

    def _save_all(self):
        folder = output.meeting_folder(self.meeting_title)
        files = {}
        files["transcript"] = output.save_transcript(folder, self.transcript_lines)
        if self.trans_pairs:
            files["translation"] = output.save_translation(folder, self.trans_pairs)
        if hasattr(self, "_last_summary"):
            files["summary"] = output.save_summary(folder, self._last_summary)
        elif self.transcript_lines:
            summ = Summarizer(self.cfg).summarize(self.transcript_lines,
                                                  title=self.meeting_title)
            files["summary"] = output.save_summary(folder, summ)
        self._last_folder = folder
        os.startfile(folder)
        self.var_status.set("已保存到: " + folder)
        messagebox.showinfo("已保存", f"文件已保存到:\n{folder}\n\n{len(files)} 个文件。", parent=self)

    def _send_email(self):
        sender = EmailSender(self.cfg)
        if not sender.is_configured():
            messagebox.showwarning("邮件未配置",
                "请先在[设置→邮件]中填写 SMTP 信息(服务器/账号/授权码/收件人)。",
                parent=self)
            self._open_settings()
            return
        if not hasattr(self, "_last_summary"):
            messagebox.showinfo("提示", "请先生成摘要", parent=self)
            return
        folder = getattr(self, "_last_folder", None)
        attachments = []
        if folder and os.path.isdir(folder):
            attachments = [os.path.join(folder, f)
                           for f in os.listdir(folder)
                           if f.endswith(".txt")]
        self.var_status.set("正在发送邮件...")
        self.update_idletasks()
        def work():
            try:
                sender.send(
                    subject=f"[会议摘要] {self.meeting_title}",
                    body=self._last_summary,
                    attachments=attachments,
                )
                self.after(0, lambda: self._mail_done(True, "邮件发送成功"))
            except Exception as e:
                self.after(0, lambda: self._mail_done(False, str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _mail_done(self, ok, msg):
        if ok:
            self.var_status.set(msg)
            messagebox.showinfo("邮件", msg, parent=self)
        else:
            self.var_status.set("邮件发送失败")
            messagebox.showerror("邮件发送失败", msg, parent=self)

    def _on_close(self):
        if self.pipeline:
            self.pipeline.stop()
        save_config(self.cfg)
        self.destroy()


class FileSource:
    """Plays back a fully-loaded audio file as chunks for the pipeline."""

    def __init__(self, wav_path, sr=16000):
        import wave
        self.wav_path = wav_path
        self._samples = None
        self._pos = 0
        self.sample_rate = sr
        with wave.open(wav_path, "rb") as w:
            self.sample_rate = w.getframerate()
            raw = w.readframes(w.getnframes())
        import numpy as np
        self._samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        self._q = []
        self._fill()

    def _fill(self):
        chunk = int(self.sample_rate * 0.5)
        i = 0
        while i < len(self._samples):
            self._q.append(self._samples[i:i + chunk].copy())
            i += chunk

    def read(self, timeout=0.5):
        if self._q:
            return self._q.pop(0)
        return None

    def stop(self):
        self._q = []


def _find_loopback():
    from core.audio_source import find_loopback_device
    return find_loopback_device()
