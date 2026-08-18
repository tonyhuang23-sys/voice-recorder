# MeetingAssist 会议助手

本地运行的会议语音助手:Tkinter 桌面应用,以及无界面 CLI。一键接听麦克风、捕获系统声音、粘贴会议链接下载音频,或监视 Zoom/Teams/Meet/Lark 本地录像目录,自动完成**语音转写(Qwen3-ASR 中文优先 / Whisper 英文优先)**、**翻译(本地离线 / 云端 API)**、**会议摘要**,并可 **SMTP 发信** 或 **推送到飞书/Lark 自定义机器人**。

所有推理均在本地运行,音频不上传。

> 仓库地址: https://github.com/tonyhuang23-sys/voice-recorder

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行(应用会自动检测并下载缺失的依赖/模型)
python app.py

# 也可以点击主界面上的[检查环境/下载模型],自动完成环境准备

# 无界面流水线(不启动 Tk)
python cli.py --help
```

**环境自检 & 自动下载**: 首次运行时,若检测到缺少以下任一资源,应用会提示并可通过[检查环境/下载模型]自动下载:

| 资源 | 缺失时行为 |
|---|---|
| Python 依赖(sherpa-onnx / faster-whisper / sounddevice / yt-dlp / argos-translate 等) | 自动 `pip install`(源码运行时;打包版已内置) |
| Qwen3-ASR-0.6B-int8 模型(~838MB) | 从官方 sherpa-onnx release 自动下载并解压到 `models/` |
| Whisper 模型(tiny/base/small/medium) | 首次使用时自动下载到 `models/whisper/` |

> 也可手动放置模型跳过下载: `models/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25/`
> (conv_frontend.onnx / encoder.int8.onnx / decoder.int8.onnx / tokenizer/),
> 来源: https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models

## 使用

1. **音源选择**
   - **麦克风**: 点击[开始接听]即可实时转写。
   - **系统声音(环回)**: 捕获 Windows 正在播放的声音(需系统有 Stereo Mix 或 VB-Cable)。适合接入 Teams/Zoom/Meet/X Spaces 会议。
   - **链接下载**: 粘贴会议链接(X Spaces / YouTube 等),应用用 yt-dlp 下载音频后离线转写。
2. **转写**: Qwen3-ASR(中文优先)与 Whisper(英文优先)自动路由;可按需在[设置]切换优先级。
3. **翻译**: 本机 CLI 默认离线 **Argos**。Grok 质量译文由助手处理 hearing 时完成,不需要本机 xAI Key。若你**已经有**云端 Key,可把 `translate.mode` 设为 `cloud` 作为可选覆盖。不要把 API key 提交到 git。
4. **摘要**: 本机 CLI 默认本地 **抽取式**。Grok 质量纪要由助手处理 hearing 时完成;无 Key 时 CLI 仍写出完整 `会议摘要.txt`。云端 OpenAI 兼容接口仅在已有 Key 时可选。
5. **四件套**: 每次处理完一场会议,输出目录固定写入四个文件(缺一不可):
   1. 原始 WAV(`audio.wav`,提取或现场录制)
   2. 原始转写 `转写记录.txt`
   3. 翻译 `翻译.txt`
   4. 中文摘要 `会议摘要.txt`
6. **邮件(Gmail/SMTP)**: 三个 `.txt` + **语音 MP3** 始终作为附件。每场会议都用 ffmpeg 把 WAV 转成 speech MP3(约 64–96kbps mono)再附上,即使 WAV 很小也不改附 WAV。完整 WAV **始终**留在输出目录。没有 MP3 就不发信。默认收件人 `gztonyhuang@outlook.com`(可用 `email.to` 或 `MEETING_EMAIL_TO` 覆盖)。
7. **飞书会话**: 只推送**中文摘要正文**(文本 + 卡片)。自定义机器人 Webhook **不能可靠传附件**,卡片会注明四件套已通过邮件发送。

## 无界面 CLI

`cli.py` 不导入 Tk,适合定时任务或本机脚本。自动跑完 ASR → 翻译 → 中文摘要,并**始终**写出四件套。Webhook / SMTP 已配置时会自动推飞书并发邮件;也可用 `--push-lark` / `--email` 显式请求(未配置则跳过)。模型、Webhook 或 SMTP 缺失时会打印原因,不会把密钥写进日志。

```bash
# 本地音频或视频(经 ffmpeg 抽取 16kHz 单声道 wav)
python cli.py --file meeting.mp4 --title "周会" --target-lang zh --push-lark --email

# 会议/视频链接(走现有 yt-dlp 下载路径)
python cli.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --title "talk"

# 实时麦克风 / 系统环回(Ctrl+C 结束;音频写入 output/.../audio.wav)
python cli.py --mic --title "live"
python cli.py --loopback --title "zoom"

# 监视 Zoom / Teams / Meet / Lark 本地录像目录
python cli.py --watch "C:\Users\you\Documents\Zoom" --push-lark --email
```

| 参数 | 说明 |
|---|---|
| `--file PATH` | 音频或视频文件;非 16k 单声道 wav 时调用 ffmpeg |
| `--url URL` | yt-dlp 下载并转 16k mono wav |
| `--mic` / `--loopback` | 实时采集;可用 `--device N` 指定 sounddevice 输入设备 |
| `--watch DIR` | 递归监视目录,文件停止增长后再处理 |
| `--title` | 会议标题(默认 `会议记录`) |
| `--target-lang` | 翻译目标语言,默认 `zh` |
| `--push-lark` | 把中文摘要推到飞书会话;Webhook 已配置时即使不写此参数也会推 |
| `--email` | 把四件套发到邮件收件人;SMTP 已配置时即使不写此参数也会发 |

需要 ffmpeg 处理视频/非 wav 音频: 设置 `FFMPEG_BIN` 或保证 `ffmpeg` 在 PATH 中。

### 监视文件夹工作流

把 `--watch` 指到本地录像目录即可(无需入会机器人):

- **Zoom**: 常见为 `Documents\Zoom\日期 主题\audio_only.m4a` 或 `*.mp4`
- **Teams / Google Meet**: 下载或录制得到的 `*.mp4` / `*.m4a`
- **飞书/Lark**: 本地云文档或录制文件夹中的音视频

程序每隔几秒扫描(可用 `--poll` 调整),仅处理体积已稳定 `--watch-settle` 秒(默认 8)的媒体文件,跳过 `.part` / `.tmp` 等未完成下载。已处理路径记在 `output/watch_seen.json`,避免重复。发现新文件后走与 `--file` 相同的流水线:抽取 wav → 转写 → 翻译 → 中文摘要 → 写出四件套 → 已配置则邮件 + 飞书。

```bash
# 例: Zoom 默认录像目录
python cli.py --watch "%USERPROFILE%\Documents\Zoom" --title "Zoom" --target-lang zh --push-lark
```

## 飞书 / Lark 推送

使用**自定义机器人** Webhook(不是应用 secret)。**不要把真实 Webhook URL 提交到 git。**

解析顺序:

1. 环境变量 `LARK_WEBHOOK_URL`(推荐)
2. 本地 `config.json` 的 `lark.webhook_url`(`config.json` 已在 `.gitignore` 中)

```bash
# Linux / macOS
export LARK_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/<your-token>"

# Windows PowerShell
$env:LARK_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/<your-token>"

python cli.py --file meeting.wav --push-lark
```

未设置变量且 `config.json` 中也无 URL 时会跳过并提示,四件套仍会保存。GUI 在[设置→飞书/Lark]填写 Webhook 后,摘要完成会把**中文摘要**推进会话(文本 + 卡片),并注明四件套已邮件发送。Webhook **不会**附加 WAV/文件。请求有超时;非 2xx 或机器人返回错误码会记日志,不会打印完整 Webhook。

## 翻译与摘要: 本机默认离线,不需要 xAI Key

**Grok 质量的翻译与摘要由助手在处理一场 hearing 时完成**(用你现有的 Grok 订阅)。本机 `python cli.py` **不调用** xAI API,也**不要**去申请或填写 xAI Key。

无人值守默认:

- `translate.mode` / `summary.mode` = `local`
- 翻译: 离线 **Argos**
- 摘要: 本地 **抽取式**
- 无任何云端 Key 也能完整跑完并写出四个本地文件

可选覆盖(仅当你**已经有**密钥时): 把 mode 设为 `cloud`,或设环境变量 `XAI_API_KEY` / 在 gitignored `config.json` 填写 `translate.cloud.api_key` / `summary.cloud.api_key`。此时走 OpenAI 兼容接口(`base_url` 默认 `https://api.x.ai/v1`,模型默认读配置)。没有 Key 时云端路径会被跳过,回退 Argos / 抽取式。

本地小模型只作后备,不在本流程下载 Qwen 权重。**不要把 API key 提交到 git。** `config.json` 已在 `.gitignore`。

## 邮件 / Gmail 附件

默认收件人 **gztonyhuang@outlook.com**。覆盖顺序:

1. 环境变量 `MEETING_EMAIL_TO`
2. `config.json` 的 `email.to`(或 `email.to_addrs`)
3. 上述默认地址

SMTP 可用[设置→邮件]填写(写入本地 `config.json`,已 gitignore),或只用环境变量(推荐 Gmail 应用专用密码):

```bash
# 收件人
export MEETING_EMAIL_TO="gztonyhuang@outlook.com"

# Gmail SMTP(不要把应用专用密码提交到 git)
export GMAIL_USER="you@gmail.com"
export GMAIL_APP_PASSWORD="<gmail-app-password>"

# 或通用 SMTP
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USER="you@gmail.com"
export SMTP_PASSWORD="<app-password>"

python cli.py --file meeting.wav --email
```

信件正文为**中文摘要**,并说明音频以 MP3 附件发送。附件始终是:

- `转写记录.txt` / `翻译.txt` / `会议摘要.txt`
- `audio.mp3`(ffmpeg 从本地 WAV 转出,约 80kbps,必要时 64kbps mono)

**不附完整 WAV。** 即使录音很小也发 MP3。若转码失败或 MP3+文本仍超过 Gmail 25MB,则**不发送这封邮件**(避免无音频空信),完整 WAV/MP3 留在本地 `output/`。无 SMTP 密码时跳过发送,不中断流水线。

## 目录结构

```
MeetingAssist/
├── app.py                 # GUI 入口
├── cli.py                 # 无界面流水线入口(不导入 Tk)
├── config.json            # 运行时配置(自动生成,不入库;可含 lark.webhook_url)
├── requirements.txt
├── MeetingAssist.spec     # PyInstaller 打包配置(模型不打包,运行时外置)
├── core/
│   ├── config.py          # 配置加载/保存(含 lark 默认段)
│   ├── asr.py             # Qwen3-ASR + faster-whisper 双引擎
│   ├── audio_source.py    # 麦克风 / 环回 / 文件 / 链接下载
│   ├── translator.py      # argos 离线 + 云端翻译
│   ├── summarizer.py      # 摘要(local/cloud)
│   ├── emailer.py         # SMTP 发送 + 测试连接
│   ├── lark.py            # 飞书自定义机器人(文本 + 卡片)
│   ├── job.py             # 无界面一次任务
│   ├── watch.py           # 录像目录监视
│   ├── env_check.py       # 环境自检 & 依赖/模型自动下载
│   ├── pipeline.py        # 实时分段→转写→翻译流水线
│   └── output.py          # 文件保存
├── ui/
│   ├── main.py            # 主窗口(含环境检查入口)
│   └── settings.py        # 设置对话框(SMTP / 飞书)
├── models/                # 模型目录(不入库,运行时自动下载)
│   └── sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25/   # Qwen3-ASR 模型
└── output/                # 每场会议: audio.wav + 转写记录.txt + 翻译.txt + 会议摘要.txt
```

## 打包为独立 exe

模型较大(~838MB)不打包进 exe;打包版运行时从 exe 同级 `models/` 目录读取模型,并通过[检查环境/下载模型]自动补齐。

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build MeetingAssist.spec
# 产物: dist/MeetingAssist.exe
# 使用: 把 exe 放到一个空目录,运行时若缺少模型会自动下载
```

## 关键技术

| 组件 | 方案 |
|---|---|
| ASR 中文 | Qwen3-ASR-0.6B-int8 (sherpa-onnx ≥1.10, ONNX) |
| ASR 英文 | faster-whisper (CTranslate2, int8) |
| 翻译 | 本机默认 Argos;Grok 质量由助手完成。云端 OpenAI 兼容接口仅在已有 Key 时可选 |
| 摘要 | 本机默认抽取式;Grok 质量由助手完成。xAI Key 可选、非必需 |
| 音频捕获 | sounddevice(麦克风/环回) + ffmpeg(文件/视频) + yt-dlp(链接) |
| 邮件 | smtplib SMTP/SSL(隐式 SSL 不再套 STARTTLS) + 测试连接 |
| 飞书/Lark | 自定义机器人 Webhook(文本 + interactive card) |
| 环境自检 | 自动 pip 安装缺失依赖 + 自动下载缺失模型 |

## 说明与限制

- Qwen3-ASR HuggingFace 原始权重不可直接用,必须使用经 sherpa-onnx 导出规范转换的 ONNX(conv_frontend/encoder/decoder/tokenizer)。
- 中文优先时,中文语音由 Qwen3-ASR 识别;若 Qwen3 失败则回退 Whisper。英文优先反之。
- 系统声音捕获依赖 Windows 音频输入设备中存在 "Stereo Mix" 或虚拟声卡。
- 语音分段采用能量阈值(VAD 简化版),安静环境效果最佳;复杂会议建议配合实际场景调参(`config.json` → audio)。
- 首次自动下载 Qwen3-ASR 模型约 838MB,请保持网络畅通。
