"""Settings dialog (Tkinter)."""
import tkinter as tk
from tkinter import ttk, messagebox

from core.config import save_config


class SettingsDialog(tk.Toplevel):
    def __init__(self, master, cfg, on_save=None):
        super().__init__(master)
        self.cfg = cfg
        self.on_save = on_save
        self.title("设置")
        self.geometry("720x620")
        self.resizable(True, True)
        self.transient(master)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self._build_translate_tab(nb)
        self._build_summary_tab(nb)
        self._build_email_tab(nb)
        self._build_lark_tab(nb)
        self._build_asr_tab(nb)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=8, pady=6)
        ttk.Button(btns, text="保存", command=self._save).pack(side="right", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")

        self.grab_set()

    # ---- tabs ----
    def _grid(self, parent, row, label, var, show=None, width=40):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ent = ttk.Entry(parent, textvariable=var, width=width, show=show)
        ent.grid(row=row, column=1, sticky="we", pady=3, padx=6)
        parent.columnconfigure(1, weight=1)
        return ent

    def _build_translate_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="翻译")
        self.tr_mode = tk.StringVar(value=self.cfg["translate"]["mode"])
        self.tr_target = tk.StringVar(value=self.cfg["translate"]["target_lang"])
        self.tr_auto = tk.BooleanVar(value=self.cfg["translate"]["auto"])
        self.tr_provider = tk.StringVar(value=self.cfg["translate"]["cloud"]["provider"])
        self.tr_api = tk.StringVar(value=self.cfg["translate"]["cloud"]["api_key"])
        self.tr_base = tk.StringVar(value=self.cfg["translate"]["cloud"]["base_url"])
        self.tr_model = tk.StringVar(value=self.cfg["translate"]["cloud"]["model"])
        self.tr_deepl = tk.StringVar(value=self.cfg["translate"]["cloud"]["deepl_api_key"])

        ttk.Label(f, text="翻译引擎:").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.tr_mode, values=["local", "cloud"],
                     state="readonly", width=10).grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="目标语言:").grid(row=1, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.tr_target, values=["zh", "en"],
                     state="readonly", width=10).grid(row=1, column=1, sticky="w")
        ttk.Checkbutton(f, text="自动翻译非目标语言内容", variable=self.tr_auto).grid(
            row=2, column=0, columnspan=2, sticky="w")

        ttk.Separator(f).grid(row=3, column=0, columnspan=2, sticky="we", pady=8)
        ttk.Label(f, text="云端 API 配置(选填):").grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Provider").grid(row=5, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.tr_provider, values=["openai", "deepl"],
                     state="readonly", width=10).grid(row=5, column=1, sticky="w")
        self._grid(f, 6, "OpenAI API Key", self.tr_api)
        self._grid(f, 7, "Base URL", self.tr_base)
        self._grid(f, 8, "模型", self.tr_model)
        self._grid(f, 9, "DeepL API Key", self.tr_deepl)

    def _build_summary_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="摘要")
        self.sm_engine = tk.StringVar(value=self.cfg["summary"]["engine"])
        self.sm_api = tk.StringVar(value=self.cfg["summary"]["cloud"]["api_key"])
        self.sm_base = tk.StringVar(value=self.cfg["summary"]["cloud"]["base_url"])
        self.sm_model = tk.StringVar(value=self.cfg["summary"]["cloud"]["model"])

        ttk.Label(f, text="摘要引擎:").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.sm_engine, values=["local", "cloud"],
                     state="readonly", width=10).grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="(local=本地关键词摘要,cloud=LLM摘要)").grid(
            row=1, column=0, columnspan=2, sticky="w")
        ttk.Separator(f).grid(row=2, column=0, columnspan=2, sticky="we", pady=8)
        self._grid(f, 3, "LLM API Key", self.sm_api)
        self._grid(f, 4, "Base URL", self.sm_base)
        self._grid(f, 5, "模型", self.sm_model)

    def _build_email_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="邮件")
        e = self.cfg["email"]
        self.em_host = tk.StringVar(value=e["smtp_host"])
        self.em_port = tk.StringVar(value=str(e["smtp_port"]))
        self.em_user = tk.StringVar(value=e["smtp_user"])
        self.em_pwd = tk.StringVar(value=e["smtp_password"])
        self.em_ssl = tk.BooleanVar(value=e["use_ssl"])
        self.em_from = tk.StringVar(value=e["from_addr"])
        self.em_to = tk.StringVar(value=", ".join(e["to_addrs"]))

        self._grid(f, 0, "SMTP 服务器", self.em_host)
        self._grid(f, 1, "SMTP 端口", self.em_port, width=10)
        self._grid(f, 2, "账号", self.em_user)
        self._grid(f, 3, "密码/授权码", self.em_pwd, show="*")
        ttk.Checkbutton(f, text="使用 SSL", variable=self.em_ssl).grid(
            row=4, column=0, columnspan=2, sticky="w")
        self._grid(f, 5, "发件人地址", self.em_from)
        self._grid(f, 6, "收件人(逗号分隔)", self.em_to)
        ttk.Label(f, text="例: 163/QQ 邮箱需开启 SMTP 并填授权码",
                  foreground="gray").grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Button(f, text="测试连接", command=self._test_smtp).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=6)

    def _build_lark_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="飞书/Lark")
        lark = self.cfg.get("lark") or {}
        self.lk_url = tk.StringVar(value=lark.get("webhook_url") or "")
        self.lk_on = tk.BooleanVar(value=bool(lark.get("enabled", True)))
        ttk.Checkbutton(f, text="摘要后自动推送(需配置 Webhook)", variable=self.lk_on).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=3)
        self._grid(f, 1, "Webhook URL", self.lk_url, show="*")
        ttk.Label(
            f,
            text="优先使用环境变量 LARK_WEBHOOK_URL。Webhook 只保存在本地 config.json,不会入库。",
            foreground="gray",
            wraplength=620,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=6)

    def _test_smtp(self):
        from core.emailer import EmailSender
        from tkinter import messagebox
        import threading

        e = self.cfg["email"]
        e["smtp_host"] = self.em_host.get().strip()
        e["smtp_port"] = int(self.em_port.get() or 465)
        e["smtp_user"] = self.em_user.get().strip()
        e["smtp_password"] = self.em_pwd.get().strip()
        e["use_ssl"] = bool(self.em_ssl.get())

        def work():
            try:
                EmailSender(self.cfg).test_connection()
                self.after(0, lambda: messagebox.showinfo("SMTP", "连接成功", parent=self))
            except Exception as ex:
                self.after(0, lambda: messagebox.showerror("SMTP", f"连接失败:\n{ex}", parent=self))

        threading.Thread(target=work, daemon=True).start()

    def _build_asr_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="ASR")
        self.asr_pri = tk.StringVar(value=self.cfg["asr"]["lang_priority"])
        self.ws_model = tk.StringVar(value=self.cfg["asr"]["whisper"]["model"])
        self.ws_threads = tk.StringVar(value=str(self.cfg["asr"]["qwen3"]["num_threads"]))
        self.auto_tr = tk.BooleanVar(value=self.cfg["translate"]["auto"])

        ttk.Label(f, text="语言优先级:").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.asr_pri, values=["cn", "en"],
                     state="readonly", width=10).grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="(cn=Qwen3-ASR中文优先,en=Whisper英文优先)").grid(
            row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Whisper 模型:").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.ws_model, values=["tiny", "base", "small", "medium"],
                     state="readonly", width=10).grid(row=2, column=1, sticky="w")
        ttk.Label(f, text="Qwen3 线程数:").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.ws_threads, width=10).grid(row=3, column=1, sticky="w")

    # ---- save ----
    def _save(self):
        cfg = self.cfg
        cfg["translate"]["mode"] = self.tr_mode.get()
        cfg["translate"]["target_lang"] = self.tr_target.get()
        cfg["translate"]["auto"] = bool(self.tr_auto.get())
        cfg["translate"]["cloud"]["provider"] = self.tr_provider.get()
        cfg["translate"]["cloud"]["api_key"] = self.tr_api.get().strip()
        cfg["translate"]["cloud"]["base_url"] = self.tr_base.get().strip()
        cfg["translate"]["cloud"]["model"] = self.tr_model.get().strip()
        cfg["translate"]["cloud"]["deepl_api_key"] = self.tr_deepl.get().strip()

        cfg["summary"]["engine"] = self.sm_engine.get()
        cfg["summary"]["cloud"]["api_key"] = self.sm_api.get().strip()
        cfg["summary"]["cloud"]["base_url"] = self.sm_base.get().strip()
        cfg["summary"]["cloud"]["model"] = self.sm_model.get().strip()

        cfg["email"]["smtp_host"] = self.em_host.get().strip()
        cfg["email"]["smtp_port"] = int(self.em_port.get() or 465)
        cfg["email"]["smtp_user"] = self.em_user.get().strip()
        cfg["email"]["smtp_password"] = self.em_pwd.get().strip()
        cfg["email"]["use_ssl"] = bool(self.em_ssl.get())
        cfg["email"]["from_addr"] = self.em_from.get().strip()
        cfg["email"]["to_addrs"] = [x.strip() for x in self.em_to.get().split(",") if x.strip()]

        cfg.setdefault("lark", {})
        cfg["lark"]["webhook_url"] = self.lk_url.get().strip()
        cfg["lark"]["enabled"] = bool(self.lk_on.get())

        cfg["asr"]["lang_priority"] = self.asr_pri.get()
        cfg["asr"]["whisper"]["model"] = self.ws_model.get()
        cfg["asr"]["qwen3"]["num_threads"] = int(self.ws_threads.get() or 4)

        save_config(cfg)
        if self.on_save:
            self.on_save(cfg)
        messagebox.showinfo("设置", "已保存", parent=self)
        self.destroy()
