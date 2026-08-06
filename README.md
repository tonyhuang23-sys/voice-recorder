# MeetingAssist 会议助手

本地运行的会议语音助手(Tkinter 桌面应用):一键接听麦克风、捕获系统声音、或粘贴会议链接下载音频,自动完成**语音转写(Qwen3-ASR 中文优先 / Whisper 英文优先)**、**翻译(本地离线 / 云端 API)**、**会议摘要**并通过 **SMTP 发送邮件**。

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
3. **翻译**: 默认本地 argos-translate 离线翻译;可在[设置→翻译]切换到云端 API(OpenAI/DeepL)。
4. **摘要**: [生成摘要] → 本地规则摘要或云端 LLM 摘要。
5. **保存**: 转写/翻译/摘要存到 `output/日期_标题/`。
6. **邮件**: [设置→邮件] 配置 SMTP(可用[测试连接]验证服务器/账号/授权码)后,[发送摘要邮件]可将摘要和附件发到指定邮箱。

## 目录结构

```
MeetingAssist/
├── app.py                 # 入口
├── config.json            # 运行时配置(自动生成,不入库)
├── requirements.txt
├── MeetingAssist.spec     # PyInstaller 打包配置(模型不打包,运行时外置)
├── core/
│   ├── config.py          # 配置加载/保存(兼容打包后的路径)
│   ├── asr.py             # Qwen3-ASR + faster-whisper 双引擎
│   ├── audio_source.py    # 麦克风 / 环回 / 链接下载
│   ├── translator.py      # argos 离线 + 云端翻译
│   ├── summarizer.py      # 摘要(local/cloud)
│   ├── emailer.py         # SMTP 发送 + 测试连接
│   ├── env_check.py       # 环境自检 & 依赖/模型自动下载
│   ├── pipeline.py        # 实时分段→转写→翻译流水线
│   └── output.py          # 文件保存
├── ui/
│   ├── main.py            # 主窗口(含环境检查入口)
│   └── settings.py        # 设置对话框(SMTP 测试连接)
├── models/                # 模型目录(不入库,运行时自动下载)
│   └── sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25/   # Qwen3-ASR 模型
└── output/                # 会议输出
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
| 翻译本地 | argos-translate (en↔zh) |
| 翻译云端 | OpenAI 兼容 / DeepL API |
| 摘要本地 | 关键词+句子抽取 |
| 摘要云端 | OpenAI 兼容 LLM |
| 音频捕获 | sounddevice(麦克风/环回) + yt-dlp(链接) |
| 邮件 | smtplib SMTP/SSL + 测试连接 |
| 环境自检 | 自动 pip 安装缺失依赖 + 自动下载缺失模型 |

## 说明与限制

- Qwen3-ASR HuggingFace 原始权重不可直接用,必须使用经 sherpa-onnx 导出规范转换的 ONNX(conv_frontend/encoder/decoder/tokenizer)。
- 中文优先时,中文语音由 Qwen3-ASR 识别;若 Qwen3 失败则回退 Whisper。英文优先反之。
- 系统声音捕获依赖 Windows 音频输入设备中存在 "Stereo Mix" 或虚拟声卡。
- 语音分段采用能量阈值(VAD 简化版),安静环境效果最佳;复杂会议建议配合实际场景调参(`config.json` → audio)。
- 首次自动下载 Qwen3-ASR 模型约 838MB,请保持网络畅通。
