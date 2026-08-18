"""AUC Hearing auto-capture daemon — segmented recording + real-time processing.

Records live hearings in 15-min WAV segments, converts each to MP3,
transcribes (Whisper medium) + translates (DeepSeek V4 Flash -> argos) on the fly,
and summarizes at the end. Temp WAV folder capped at 100MB (deletes oldest).
"""
import datetime
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from core.config import load_config, OUTPUT_DIR

log = logging.getLogger("auc")

PLAYLIST = "https://www.youtube.com/playlist?list=PLxLCGOtuvAwOkmoHzyKeGXnnLg7nAJ3na"
VIDEO_IDS = [
    "D-GxmZ20sxU", "t6Tdv1r9TOw", "bsF_UTAd3Uk", "t9nYhDWECck",
    "vsT5SnXNI7I", "CbEFf8pWs0I", "JTfuE20pdaI", "X6kBsvwJPdA",
    "wS_uchChlOk", "14HIAIdXLJs", "tAysIVg_Mx8", "JFETU6T8Do0",
]
DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-v4-flash"
FFMPEG = r"C:\Users\ht_34\AppData\Local\Programs\Python\Python311\ffmpeg.exe"

OUT_ROOT = os.path.join(OUTPUT_DIR, "AUC_听证会")
STATE_FILE = os.path.join(OUT_ROOT, "_state.json")


def msg(m):
    try:
        print(m, flush=True)
    except Exception:
        pass
    log.info(m)


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {"done": []}


def save_state(st):
    os.makedirs(OUT_ROOT, exist_ok=True)
    json.dump(st, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# ---------- video status ----------
def video_status(vid):
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True,
                               "noplaylist": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info("https://www.youtube.com/watch?v=" + vid, download=False)
            ls = info.get("live_status")
            if ls == "is_live":
                return ("live", info.get("title") or "NA")
            if ls == "is_upcoming":
                return ("upcoming", info.get("title") or "NA")
            return ("ended", info.get("title") or "NA")
    except Exception as ex:
        m = str(ex)
        if "live event will begin" in m:
            return ("upcoming", "NA")
        if "unavailable" in m.lower() or "private" in m.lower():
            return ("unavailable", "NA")
        return ("unknown", "NA")


def get_stream_url(vid):
    """Extract the actual stream URL via yt-dlp."""
    url = "https://www.youtube.com/watch?v=" + vid
    out = subprocess.check_output(
        [sys.executable, "-m", "yt_dlp", "-g", "-f", "bestaudio/best", url],
        stderr=subprocess.DEVNULL).decode().strip()
    return out.split("\n")[-1]


# ---------- segmented recording ----------
def start_segmenter(stream_url, temp_folder, segment_sec):
    """Start ffmpeg segment muxer. Returns Popen process."""
    os.makedirs(temp_folder, exist_ok=True)
    pattern = os.path.join(temp_folder, "seg_%03d.wav")
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error",
        "-i", stream_url,
        "-f", "segment", "-segment_time", str(segment_sec),
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        pattern
    ]
    msg(f"  segmenter: ffmpeg segment every {segment_sec}s -> {pattern}")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def enforce_temp_limit(temp_folder, max_mb):
    """Delete oldest WAVs until total size <= max_mb."""
    wavs = []
    for f in os.listdir(temp_folder):
        if f.endswith(".wav"):
            p = os.path.join(temp_folder, f)
            wavs.append((p, os.path.getsize(p), os.path.getmtime(p)))
    wavs.sort(key=lambda x: x[2])  # oldest first
    total_mb = sum(s for _, s, _ in wavs) / (1024 * 1024)
    while total_mb > max_mb and wavs:
        oldest = wavs.pop(0)
        try:
            os.remove(oldest[0])
            total_mb -= oldest[1] / (1024 * 1024)
            msg(f"  temp cleanup: removed {os.path.basename(oldest[0])}")
        except OSError:
            break


# ---------- cloud LLM ----------
def cloud_call(messages, max_tokens=4000):
    import urllib.request
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return None
    body = json.dumps({"model": DEEPSEEK_MODEL, "messages": messages,
                      "temperature": 0.3, "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(DEEPSEEK_BASE + "/chat/completions", data=body,
                                headers={"Content-Type": "application/json",
                                         "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read().decode())
            return d["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("DeepSeek failed: %s", e)
        return None


def translate(text):
    return cloud_call([{"role": "system",
                        "content": "Translate the following hearing transcript to simplified Chinese. Output only the translation."},
                       {"role": "user", "content": text}], max_tokens=8000)


def summarize(text, title):
    return cloud_call([{"role": "system",
                        "content": "你是专业听证会摘要员。用中文输出结构化摘要:①基本信息(案件号、日期、与会方)②议程议题③各方论点与关键证据④委员提问⑤决定与后续行动⑥关键时间节点。要点式,保留关键数字和名称。"},
                       {"role": "user", "content": f"标题:{title}\n\n转写:\n{text}"}], max_tokens=4000)


# ---------- per-segment processing ----------
def read_wav(wav_path):
    import numpy as np
    import wave
    with wave.open(wav_path, "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def wav_to_mp3(wav_path, mp3_path):
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", wav_path, "-codec:a", "libmp3lame", "-q:a", "4", mp3_path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def process_segment(wav_path, idx, out_folder, asr, cfg, title, transcript_acc,
                    trans_acc):
    """Convert WAV->MP3, transcribe, translate, append to accumulators."""
    base = f"seg_{idx:03d}"
    mp3_path = os.path.join(out_folder, base + ".mp3")
    msg(f"  segment {idx}: {os.path.basename(wav_path)} -> {base}.mp3")

    # WAV -> MP3
    try:
        wav_to_mp3(wav_path, mp3_path)
    except Exception as e:
        msg(f"  mp3 conversion failed: {e}")

    # transcribe
    samples = read_wav(wav_path)
    if samples is None or len(samples) < 16000 * 3:
        msg(f"  segment {idx}: too short, skip")
        return
    en = asr.transcribe_whisper(samples, 16000, language="en")
    if len(en) < 10:
        try:
            zh = asr.transcribe_qwen3(samples, 16000)
            if len(zh) > len(en):
                en = zh
        except Exception:
            pass
    if not en.strip():
        return
    transcript_acc.append(en)
    msg(f"  segment {idx}: transcribed {len(en)} chars")

    # translate
    zh = translate(en)
    if not zh:
        from core.translator import Translator
        t = Translator(cfg)
        zh = t.translate_local(en[:20000], "en", "zh")
    if zh:
        trans_acc.append(zh)
    msg(f"  segment {idx}: translated")


# ---------- watch loop: detect completed segments & process ----------
def watch_and_process(proc, temp_folder, out_folder, asr, cfg, title,
                      segment_sec, transcript_acc, trans_acc):
    """Watch temp folder for completed segments; process each one."""
    idx = 1
    max_idle = 600  # seconds with no new segment => consider ended
    last_activity = time.time()
    while True:
        cur = os.path.join(temp_folder, f"seg_{idx:03d}.wav")
        nxt = os.path.join(temp_folder, f"seg_{idx+1:03d}.wav")
        if os.path.exists(nxt) and os.path.exists(cur):
            process_segment(cur, idx, out_folder, asr, cfg, title,
                            transcript_acc, trans_acc)
            enforce_temp_limit(temp_folder, cfg.get("auc", {}).get("temp_wav_max_mb", 100))
            idx += 1
            last_activity = time.time()
        elif proc.poll() is not None:
            # processer exited; process remaining segments
            if os.path.exists(cur) and os.path.getsize(cur) > 1024:
                process_segment(cur, idx, out_folder, asr, cfg, title,
                                transcript_acc, trans_acc)
                idx += 1
            break
        elif time.time() - last_activity > max_idle:
            msg(f"  no new segment in {max_idle}s, stopping watch")
            break
        time.sleep(8)
    # process any leftover segments
    while True:
        cur = os.path.join(temp_folder, f"seg_{idx:03d}.wav")
        if os.path.exists(cur) and os.path.getsize(cur) > 1024:
            process_segment(cur, idx, out_folder, asr, cfg, title,
                            transcript_acc, trans_acc)
            idx += 1
        else:
            break
    try:
        proc.wait(timeout=15)
    except Exception:
        proc.kill()


# ---------- main process per video ----------
def process(vid, cfg):
    folder = os.path.join(OUT_ROOT, vid)
    os.makedirs(folder, exist_ok=True)
    if os.path.exists(os.path.join(folder, "done.txt")):
        return "done"

    status, title = video_status(vid)
    msg(f"  {vid}: {status} - {title}")

    if status == "unavailable":
        return "unavailable"

    segment_sec = int(cfg.get("auc", {}).get("segment_minutes", 15)) * 60
    transcript_acc = []
    trans_acc = []

    if status == "ended":
        # VOD: download, then split into segments locally
        msg(f"  downloading VOD ...")
        vod = os.path.join(folder, "vod.m4a")
        if not os.path.exists(vod):
            r = subprocess.run([sys.executable, "-m", "yt_dlp", "-f", "bestaudio/best",
                                "-o", vod, "https://www.youtube.com/watch?v=" + vid],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if r.returncode != 0 or not os.path.exists(vod):
                msg(f"  VOD download failed (YouTube auth), skipping")
                with open(os.path.join(folder, "done.txt"), "w", encoding="utf-8") as f:
                    f.write(f"SKIP_VOD_FAIL\n{title}")
                return "failed"
        # split into 15-min wav segments in temp
        temp = os.path.join(folder, "temp_wav")
        os.makedirs(temp, exist_ok=True)
        pattern = os.path.join(temp, "seg_%03d.wav")
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error",
                        "-i", vod, "-f", "segment", "-segment_time", str(segment_sec),
                        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", pattern],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        from core.asr import ASRManager
        asr = ASRManager(cfg)
        idx = 1
        while True:
            seg = os.path.join(temp, f"seg_{idx:03d}.wav")
            if not os.path.exists(seg):
                break
            process_segment(seg, idx, folder, asr, cfg, title,
                            transcript_acc, trans_acc)
            enforce_temp_limit(temp, cfg.get("auc", {}).get("temp_wav_max_mb", 100))
            idx += 1
        import shutil
        shutil.rmtree(temp, ignore_errors=True)

    elif status == "live":
        stream_url = get_stream_url(vid)
        temp = os.path.join(folder, "temp_wav")
        proc = start_segmenter(stream_url, temp, segment_sec)
        from core.asr import ASRManager
        asr = ASRManager(cfg)
        watch_and_process(proc, temp, folder, asr, cfg, title,
                          segment_sec, transcript_acc, trans_acc)
        import shutil
        shutil.rmtree(temp, ignore_errors=True)

    elif status == "upcoming":
        return "pending"

    # combine transcripts
    full_text = "\n".join(transcript_acc)
    full_zh = "\n".join(trans_acc)
    if not full_text.strip():
        return "failed"

    msg(f"  total transcript: {len(full_text)} chars")

    # summary (DeepSeek -> local)
    sm = summarize(full_text[:120000], title) if full_text else None
    if not sm:
        from core.summarizer import Summarizer
        try:
            sm = Summarizer(cfg).summarize([("", "", x) for x in
                                            re.split(r"(?<=[.!?。])\s+", full_text)],
                                           title=title)
        except Exception:
            sm = "摘要生成失败"

    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(folder, "transcript_en.txt"), "w",
              encoding="utf-8") as f:
        f.write(f"标题: {title}\nURL: https://www.youtube.com/watch?v={vid}\n\n{full_text}")
    if full_zh:
        with open(os.path.join(folder, "transcript_zh.txt"), "w",
                  encoding="utf-8") as f:
            f.write(f"标题: {title}\nURL: https://www.youtube.com/watch?v={vid}\n\n{full_zh}")
    with open(os.path.join(folder, "summary_zh.md"), "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\nURL: https://www.youtube.com/watch?v={vid}\n\n{sm}")
    with open(os.path.join(folder, "done.txt"), "w", encoding="utf-8") as f:
        f.write(f"{now}\n{title}")
    msg(f"  done -> {folder}")
    return "done"


def master_summary():
    lines = ["# AUC 听证会汇总\n"]
    for vid in sorted(os.listdir(OUT_ROOT)):
        folder = os.path.join(OUT_ROOT, vid)
        if not os.path.isdir(folder):
            continue
        s = os.path.join(folder, "summary_zh.md")
        d = os.path.join(folder, "done.txt")
        if not (os.path.exists(s) and os.path.exists(d)):
            continue
        head = open(d, encoding="utf-8").read().strip().splitlines()[0]
        lines.append(f"\n---\n\n## {head}\n")
        lines.append(open(s, encoding="utf-8").read())
    with open(os.path.join(OUT_ROOT, "汇总摘要.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    msg("汇总摘要已更新")


def main():
    os.makedirs(OUT_ROOT, exist_ok=True)
    cfg = load_config()
    state = load_state()
    recording = {}

    while True:
        for vid in VIDEO_IDS:
            if vid in state.get("done", []):
                continue
            if vid in recording:
                if not recording[vid].is_alive():
                    del recording[vid]
                continue
            status, title = video_status(vid)
            if status in ("live", "ended"):
                msg(f"[{vid}] {status}, start processing")
                def make_work(v, c):
                    def w():
                        process(v, c)
                        state.setdefault("done", []).append(v)
                        save_state(state)
                        master_summary()
                    return w
                t = threading.Thread(target=make_work(vid, cfg), daemon=True)
                t.start()
                recording[vid] = t

        pending = [v for v in VIDEO_IDS
                   if v not in state.get("done", []) and v not in recording]
        if not pending:
            msg("全部完成!")
            break
        msg(f"等待中: {len(pending)} 场未处理; 处理中: {len(recording)}")
        time.sleep(1800)


if __name__ == "__main__":
    os.makedirs(OUT_ROOT, exist_ok=True)
    logging.basicConfig(filename=os.path.join(OUT_ROOT, "auc_auto.log"),
                        level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        encoding="utf-8")
    main()
