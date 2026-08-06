"""Meeting summary generation: local rule-based fallback + cloud LLM."""
import logging
import re

logger = logging.getLogger(__name__)


class Summarizer:
    def __init__(self, cfg):
        self.cfg = cfg

    def summarize(self, transcript_lines, title="会议记录", engine=None):
        """transcript_lines: list of (timestamp, speaker, text)."""
        engine = engine or self.cfg["summary"].get("engine", "local")
        text = _lines_to_text(transcript_lines)
        if not text.strip():
            return "（无有效转写内容）"

        if engine == "cloud" and self.cfg["summary"]["cloud"].get("api_key"):
            try:
                return self._cloud_summarize(text, title)
            except Exception as e:
                logger.warning("Cloud summary failed (%s), using local.", e)

        return self._local_summarize(transcript_lines)

    def _cloud_summarize(self, text, title):
        import json
        import urllib.request

        cloud = self.cfg["summary"]["cloud"]
        body = json.dumps({
            "model": cloud.get("model", "gpt-4o-mini"),
            "messages": [
                {"role": "system",
                 "content": (
                     "你是专业会议纪要生成器。根据提供的会议转写文本,生成结构化的中文会议摘要,"
                     "包含:【会议主题】【关键要点】(分条列出,含数字/金额/名称等具体信息)"
                     "【结论与决议】【后续行动】(谁在何时做什么)。语言精炼、信息完整。"
                 )},
                {"role": "user", "content": f"会议标题:{title}\n\n转写内容:\n{text[:12000]}"},
            ],
            "temperature": 0.3,
        }).encode("utf-8")
        req = urllib.request.Request(
            cloud.get("base_url", "https://api.openai.com/v1") + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {cloud['api_key']}"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()

    def _local_summarize(self, transcript_lines):
        """Rule-based extractive summary with frequency-weighted key sentences."""
        from collections import Counter

        texts = [t[2] for t in transcript_lines if t[2]]
        full = "\n".join(texts)
        # keyword candidates (Chinese/English)
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9\.\-]{2,}", full)
        stop = {
            "我们", "他们", "这个", "那个", "什么", "一个", "可以", "就是", "因为",
            "所以", "但是", "然后", "觉得", "知道", "应该", "如果", "还是", "没有",
            "the", "and", "that", "this", "with", "for", "you", "your", "have",
            "was", "are", "not", "but", "out", "all", "like", "just", "about",
        }
        freq = Counter(t.lower() for t in tokens if t.lower() not in stop)
        top_kw = [w for w, _ in freq.most_common(15) if w]

        # sentence scoring: pick top sentences containing keywords
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

        lines = []
        lines.append(f"会议标题:{transcript_lines[0][1] if transcript_lines else '未命名'}")
        lines.append("")
        lines.append("【高频关键词】" + "、".join(top_kw[:12]) if top_kw else "")
        lines.append("")
        lines.append("【关键句子摘要】")
        for i, s in enumerate(key_sents, 1):
            lines.append(f"  {i}. {s}")
        lines.append("")
        lines.append("（本地规则摘要,如需更高质量请配置云端 LLM）")
        return "\n".join(lines)


def _lines_to_text(lines):
    parts = []
    for ts, speaker, text in lines:
        if text and text.strip():
            parts.append(f"[{ts}] {text.strip()}")
    return "\n".join(parts)
