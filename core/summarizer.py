"""Meeting summary: Grok/xAI cloud preferred, local extractive fallback."""
import logging
import re

from .llm import chat_completions, resolve_llm_cloud

logger = logging.getLogger(__name__)

GROK_SUMMARY_SYSTEM = (
    "你是专业会议纪要生成器。根据提供的会议转写文本,生成结构化的中文会议纪要,"
    "必须包含以下四个小节(使用这些标题):\n"
    "【会议主题】\n"
    "【关键要点】(分条列出,含数字/金额/名称等具体信息)\n"
    "【结论与决议】\n"
    "【后续行动】(谁在何时做什么)\n"
    "语言精炼、信息完整,只用中文。"
)


class Summarizer:
    def __init__(self, cfg):
        self.cfg = cfg

    def _mode(self, engine=None):
        sm = self.cfg.get("summary") or {}
        return engine or sm.get("mode") or sm.get("engine") or "cloud"

    def summarize(self, transcript_lines, title="会议记录", engine=None, mode=None):
        """transcript_lines: list of (timestamp, speaker, text)."""
        mode = mode or self._mode(engine)
        text = _lines_to_text(transcript_lines)
        if not text.strip():
            return "（无有效转写内容）"

        if mode != "local":
            cloud = resolve_llm_cloud(self.cfg, "summary")
            if cloud.get("api_key"):
                try:
                    return self._cloud_summarize(text, title, cloud)
                except Exception as e:
                    logger.warning("Grok/cloud summary failed (%s), using local.", e)
            else:
                logger.info("summary cloud key unset, using local extractive")

        return self._local_summarize(transcript_lines)

    def _cloud_summarize(self, text, title, cloud=None):
        cloud = cloud or resolve_llm_cloud(self.cfg, "summary")
        return chat_completions(
            [
                {"role": "system", "content": GROK_SUMMARY_SYSTEM},
                {"role": "user", "content": f"会议标题:{title}\n\n转写内容:\n{text[:12000]}"},
            ],
            cloud,
            timeout=120,
            temperature=0.3,
        )

    def _local_summarize(self, transcript_lines):
        """Rule-based extractive summary with frequency-weighted key sentences."""
        from collections import Counter

        texts = [t[2] for t in transcript_lines if t[2]]
        full = "\n".join(texts)
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9\.\-]{2,}", full)
        stop = {
            "我们", "他们", "这个", "那个", "什么", "一个", "可以", "就是", "因为",
            "所以", "但是", "然后", "觉得", "知道", "应该", "如果", "还是", "没有",
            "the", "and", "that", "this", "with", "for", "you", "your", "have",
            "was", "are", "not", "but", "out", "all", "like", "just", "about",
        }
        freq = Counter(t.lower() for t in tokens if t.lower() not in stop)
        top_kw = [w for w, _ in freq.most_common(15) if w]

        sents = re.split(r"[。！？!?.]+\s*", full)
        scored = []
        for s in sents:
            s = s.strip()
            if len(s) < 6:
                continue
            score = sum(1 for k in top_kw if k in s.lower())
            scored.append((score, s))
        scored.sort(reverse=True)
        key_sents = [s for _, s in scored[:12] if _ > 0][:8]

        title = ""
        if transcript_lines:
            title = transcript_lines[0][1] if len(transcript_lines[0]) > 1 else ""
        lines = [
            "【会议主题】",
            title or "未命名",
            "",
            "【关键要点】",
        ]
        if top_kw:
            lines.append("关键词: " + "、".join(top_kw[:12]))
        for i, s in enumerate(key_sents, 1):
            lines.append(f"  {i}. {s}")
        if not key_sents:
            lines.append("  （无足够句子可抽取）")
        lines.extend([
            "",
            "【结论与决议】",
            "  （本地规则摘要未能可靠抽取决议）",
            "",
            "【后续行动】",
            "  （本地规则摘要未能可靠抽取行动项）",
            "",
            "（本地抽取摘要。配置 XAI_API_KEY 后优先使用 Grok 生成纪要。）",
        ])
        return "\n".join(lines)


def _lines_to_text(lines):
    parts = []
    for ts, speaker, text in lines:
        if text and text.strip():
            parts.append(f"[{ts}] {text.strip()}")
    return "\n".join(parts)
