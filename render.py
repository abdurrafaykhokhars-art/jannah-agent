"""Jannah Leveling reel renderer.

Turns one script JSON (the output of the n8n "Write Script" step) into a
1080x1920 MP4 with a free Kokoro voiceover, synced scene by scene.

Usage:  python render.py sample.json out.mp4
"""
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import soundfile as sf
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
FPS = int(os.getenv("FPS", "30"))
MODEL = HERE / "models" / "kokoro-v1.0.int8.onnx"
VOICES = HERE / "models" / "voices-v1.0.bin"
VOICE = os.getenv("TTS_VOICE", "am_michael")             # calm male voice; try bm_george, am_adam
SPEED = float(os.getenv("TTS_SPEED", "0.95"))
AMBIENCE_DIR = HERE / "ambience"                         # optional: put soft background sounds here
THEMES = json.loads((HERE / "themes.json").read_text())
GAP = 0.35                                               # silence between spoken parts (seconds)


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


_kokoro = None
_PRON = None


def to_phonemes(text):
    """English parts go through the normal phonemizer; Arabic words listed in
    pronunciations.json are swapped for their Arabic sounds. Captions are untouched."""
    global _PRON
    if _PRON is None:
        entries = json.loads((HERE / "pronunciations.json").read_text(encoding="utf-8"))
        entries = [(k, v) for k, v in entries.items() if not k.startswith("_")]
        entries.sort(key=lambda kv: -len(kv[0]))            # longest phrases first
        groups = "|".join(f"(?P<w{i}>{k})" for i, (k, _) in enumerate(entries))
        _PRON = (re.compile(rf"(?<![\w])(?:{groups})(?P<poss>['’]s)?(?![\w])", re.I),
                 [v for _, v in entries])
    pattern, sounds = _PRON
    out, pos = [], 0
    for m in pattern.finditer(text):
        before = text[pos:m.start()]
        if before.strip():
            out.append(_kokoro.tokenizer.phonemize(before, "en-us"))
        idx = next(int(name[1:]) for name, val in m.groupdict().items() if val and name.startswith("w"))
        out.append(sounds[idx] + ("z" if m.group("poss") else ""))
        trail = re.match(r"\s*[,.!?;:…]+", text[m.end():])  # keep pauses after the word
        if trail:
            out[-1] += trail.group().strip()
            pos = m.end() + trail.end()
        else:
            pos = m.end()
    if text[pos:].strip():
        out.append(_kokoro.tokenizer.phonemize(text[pos:], "en-us"))
    return " ".join(out)


def speak(text, path):
    """Free voiceover with the open-source Kokoro model (Apache-2.0), run on this
    machine. Without the model files, writes timed silence for layout previews."""
    global _kokoro
    text = text.replace("*", "")
    if MODEL.exists():
        if _kokoro is None:
            from kokoro_onnx import Kokoro
            _kokoro = Kokoro(str(MODEL), str(VOICES))
        voice = VOICE
        if ":" in VOICE:   # blend, e.g. "hm_omega:0.6,am_michael:0.4"
            voice = sum(float(w) * _kokoro.get_voice_style(name)
                        for name, w in (part.split(":") for part in VOICE.split(",")))
        samples, sr = _kokoro.create(to_phonemes(text), voice=voice, speed=SPEED,
                                     lang="en-us", is_phonemes=True)
        sf.write(str(path), samples, sr)
        run(["ffmpeg", "-y", "-i", str(path), "-ar", "44100", "-ac", "1", str(path) + ".wav"])
        os.replace(str(path) + ".wav", path)
    else:
        secs = max(1.2, len(text.split()) / 2.6)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{secs:.2f}", str(path)])
    return duration(path)


def plan(script, tmp):
    """Make one audio clip per spoken part and lay the scenes out around them."""
    lessons = [script.get(k) for k in ("lesson_1", "lesson_2", "lesson_3") if script.get(k)]
    parts = [("hook", script["hook"])]
    parts += [(f"lesson{i}", line) for i, line in enumerate(lessons)]
    parts += [("step", "Today's level. " + script["todays_step"]), ("cta", script["cta"])]

    clips, t = [], 0.6                       # small lead-in before the first word
    starts = {}
    for name, text in parts:
        wav = tmp / f"{name}.wav"
        d = speak(text, wav)
        if name == "lesson0":
            t += 1.6                         # time to show the Arabic and reference first
        starts[name] = (t, d)
        clips.append((wav, t))
        t += d + GAP
    total = t + 0.8

    lesson_start = starts["lesson0"][0] - 1.6
    step_start = starts["step"][0] - 0.2
    cta_start = starts["cta"][0] - 0.2
    scenes = [
        {"id": "hook", "start": 0.0, "end": lesson_start},
        {"id": "lesson", "start": lesson_start, "end": step_start},
        {"id": "step", "start": step_start, "end": cta_start},
        {"id": "cta", "start": cta_start, "end": total},
    ]
    lesson_times = [starts[f"lesson{i}"][0] for i in range(len(lessons))]
    return lessons, scenes, lesson_times, clips, total


def mix_audio(clips, total, out):
    inputs, filters = [], []
    for i, (wav, start) in enumerate(clips):
        inputs += ["-i", str(wav)]
        filters.append(f"[{i}:a]adelay={int(start * 1000)}:all=1[a{i}]")
    labels = "".join(f"[a{i}]" for i in range(len(clips)))
    n = len(clips)
    ambience = sorted(AMBIENCE_DIR.glob("*.mp3")) + sorted(AMBIENCE_DIR.glob("*.wav")) if AMBIENCE_DIR.exists() else []
    if ambience:
        inputs += ["-stream_loop", "-1", "-i", str(random.choice(ambience))]
        filters.append(f"[{n}:a]volume=0.08,afade=t=out:st={total - 1.5:.2f}:d=1.5[bg]")
        labels += "[bg]"
        n += 1
    filters.append(f"{labels}amix=inputs={n}:normalize=0,apad,atrim=0:{total:.2f}[out]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[out]",
         "-ar", "44100", "-ac", "2", str(out)])


def render(script, out_path):
    theme = THEMES.get(script.get("theme", "cream"), THEMES["cream"])
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        lessons, scenes, lesson_times, clips, total = plan(script, tmp)
        audio = tmp / "voice.wav"
        mix_audio(clips, total, audio)

        reel = {
            "theme": theme, "level_label": script.get("level_label", ""), "hook": script["hook"],
            "arabic": script.get("arabic", ""), "reference": script.get("reference", ""),
            "lessons": lessons, "todays_step": script["todays_step"], "cta": script["cta"],
            "scenes": scenes, "lessonTimes": lesson_times, "total": total,
        }
        html = (HERE / "template.html").read_text(encoding="utf-8").replace(
            "<script>", "<script>window.REEL = " + json.dumps(reel, ensure_ascii=False) + ";", 1)
        page_file = HERE / f".page-{os.getpid()}.html"   # sits next to fonts/ so they load
        page_file.write_text(html, encoding="utf-8")

        frames = int(total * FPS)
        ff = subprocess.Popen([
            "ffmpeg", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
            "-i", str(audio), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest",
            "-movflags", "+faststart", str(out_path)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(args=["--disable-gpu", "--font-render-hinting=none"])
                page = browser.new_page(viewport={"width": 1080, "height": 1920})
                page.goto(page_file.as_uri())
                page.evaluate("document.fonts.ready")
                for f in range(frames):
                    page.evaluate(f"window.renderAt({f / FPS})")
                    ff.stdin.write(page.screenshot(type="jpeg", quality=92))
                browser.close()
        finally:
            page_file.unlink(missing_ok=True)
            ff.stdin.close()
            ff.wait()
        if ff.returncode != 0:
            raise RuntimeError(ff.stderr.read().decode()[-800:])
    return total


if __name__ == "__main__":
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    secs = render(data.get("output", data), sys.argv[2])
    print(f"done: {sys.argv[2]} ({secs:.1f}s)")
