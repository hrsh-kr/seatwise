"""Build the Seatwise demo video from voice notes.

    .venv/bin/python video/build.py --voice video/voice --out video/out/seatwise-demo.mp4

Needs: the Seatwise API on localhost:8000, Google Chrome, ffmpeg, whisper-cli (whisper.cpp) and the base.en model.
Timing: each voice note is transcribed with word timestamps; highlights, clicks and subtitles are anchored to the
phrases you actually said. A tiny local web server (port 8765) serves the stage page and the slides.
"""
from __future__ import annotations
import argparse, asyncio, base64, difflib, json, pathlib, re, shutil, subprocess, sys, time
from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent
WORK = ROOT / "work"
MODEL = ROOT / "models" / "ggml-base.en.bin"
STAGE = "http://127.0.0.1:8765/video/stage.html"
DECK = "http://127.0.0.1:8765/video/slides/deck.html"
APP = "http://localhost:8000/"
AUDIO_EXT = ("m4a", "mp3", "wav", "ogg", "opus", "aac", "caf", "aiff", "aif", "flac", "mp4", "webm")


def sh(*a, **k):
    return subprocess.run([str(x) for x in a], check=True, capture_output=True, text=True, **k)


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower())


# ---------------------------------------------------------------- script and voice
def narration():
    t = (REPO / "docs" / "DEMO_SCRIPT.md").read_text()
    out = {}
    for m in re.finditer(r"### (\d\d)\. .*?\n> (.*?)\n", t, re.S):
        out[m.group(1)] = m.group(2).strip()
    return out


def prepare_notes(voice: pathlib.Path):
    WORK.mkdir(exist_ok=True)
    notes = []
    for nid in sorted(narration()):
        src = next((p for e in AUDIO_EXT for p in voice.glob(f"{nid}.{e}")), None) or next(
            (p for e in AUDIO_EXT for p in voice.glob(f"{nid}*.{e}")), None)
        if src is None:
            sys.exit(f"missing voice note {nid} in {voice}")
        raw, wav, w16 = WORK / f"r{nid}.wav", WORK / f"n{nid}.wav", WORK / f"w{nid}.wav"
        sh("ffmpeg", "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", raw)
        # trim leading and trailing silence, then keep a small cushion
        trim = ("highpass=f=70,"
                "silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.12,areverse,"
                "silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.2,areverse,"
                "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,adelay=200:all=1,apad=pad_dur=0.2")
        sh("ffmpeg", "-v", "error", "-y", "-i", raw, "-af", trim, "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", wav)
        sh("ffmpeg", "-v", "error", "-y", "-i", wav, "-ar", "16000", "-ac", "1", w16)
        base = WORK / f"t{nid}"
        sh("whisper-cli", "-m", MODEL, "-f", w16, "-oj", "-of", base, "-ml", "1", "-sow", "-np", "--prompt", "Seatwise, Delhi, Transport Stack Hackathon, Anand Vihar, Connaught Place, GTFS Realtime, e-ticket")
        segs = json.loads((WORK / f"t{nid}.json").read_text())["transcription"]
        words = []
        for s in segs:
            w = s["text"].strip()
            if w and not w.startswith("["):
                words.append((w, s["offsets"]["from"] / 1000, s["offsets"]["to"] / 1000))
        dur = float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav).stdout)
        end = speech_end(wav, dur)
        note = {"id": nid, "wav": wav, "dur": dur, "words": words, "script": narration()[nid], "end": end}
        same = difflib.SequenceMatcher(None, norm(" ".join(w for w, _, _ in words)), norm(note["script"])).ratio()
        toks = note["script"].split() if same >= 0.55 else [w for w, _, _ in words]
        if same < 0.55:
            print(f"  note {nid}: spoken words differ a lot from the script; subtitles use the transcript")
        note["aligned"], snaps = pause_align(wav, dur, toks)
        print(f"  note {nid}: timed from the audio's pauses ({snaps} sentence ends snapped to real pauses, voice stops at {end:.1f}s)")
        notes.append(note)
    return notes


def align(note):
    """Script words with the times they were actually spoken (so names, numbers and spelling come out right)."""
    toks = note["script"].split()
    sn = [norm(t) for t in toks]
    tn = [norm(w) for w, _, _ in note["words"]]
    sm = difflib.SequenceMatcher(None, sn, tn, autojunk=False)
    if sm.ratio() < 0.55:
        return None
    times = [None] * len(toks)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            times[a + k] = (note["words"][b + k][1], note["words"][b + k][2])
    first = next(t for t in times if t); last = next(t for t in reversed(times) if t)
    times = [t or None for t in times]
    i = 0
    while i < len(times):
        if times[i] is None:
            j = i
            while j < len(times) and times[j] is None: j += 1
            lo = times[i - 1][1] if i > 0 else first[0]
            hi = times[j][0] if j < len(times) else last[1]
            for k in range(i, j):
                f0, f1 = (k - i) / (j - i), (k - i + 1) / (j - i)
                times[k] = (lo + (hi - lo) * f0, lo + (hi - lo) * f1)
            i = j
        else:
            i += 1
    return [(toks[k], times[k][0], times[k][1]) for k in range(len(toks))]


def pause_list(wav, dur):
    o = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(wav), "-af", "silencedetect=n=-42dB:d=0.15", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    st = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", o)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", o)]
    en += [dur] * (len(st) - len(en))
    return [(max(a, 0.0), min(b, dur)) for a, b in zip(st, en)]


def speech_intervals(pa, dur):
    """Stretches of voice between the pauses. Short blips (a breath, a click) are not speech."""
    iv, t = [], 0.0
    for a, b in sorted(pa):
        if a > t + 0.05:
            iv.append((t, a))
        t = max(t, b)
    if dur > t + 0.05:
        iv.append((t, dur))
    return [x for x in iv if x[1] - x[0] >= 0.25] or iv


def pause_align(wav, dur, tokens):
    """Time every script word from the audio itself. Real pauses split the script into phrases; inside a phrase the
    words take the voiced time in proportion to their length. Returns ([(word, start, end)], number_of_pauses_used)."""
    pa = pause_list(wav, dur)
    iv = speech_intervals(pa, dur)
    wt = [max(1, len(re.sub(r"[^A-Za-z0-9]", "", w))) + 0.6 for w in tokens]
    cum = [0.0]
    for x in wt:
        cum.append(cum[-1] + x)

    def spread(k0, k1, S, E):
        """Words k0..k1-1 over the voiced time inside [S, E]."""
        sub = [(max(a, S), min(b, E)) for a, b in iv if min(b, E) - max(a, S) > 0.02] or [(S, E)]
        total = sum(b - a for a, b in sub)
        base, span = cum[k0], cum[k1] - cum[k0]
        def at(frac, start):
            x = frac * total
            for a, b in sub:
                if (x < b - a - 1e-9) if start else (x <= b - a + 1e-9):
                    return a + x
                x -= (b - a)
            return sub[-1][1]
        return [(tokens[k], at((cum[k] - base) / span, True), at((cum[k + 1] - base) / span, False)) for k in range(k0, k1)]

    # first guess over the whole clip, only used to decide which word each pause belongs to
    guess = spread(0, len(tokens), iv[0][0], iv[-1][1])
    pauses = [(a, b) for a, b in pa if b - a >= 0.2 and a > 0.4 and b < dur - 0.3]
    cands = {}
    for a, b in sorted(pauses):
        k = min(range(len(tokens) - 1), key=lambda k: abs(guess[k][2] - a))
        tol = 0.7 if re.search(r"[.!?]$", tokens[k]) else 0.35
        if abs(guess[k][2] - a) <= tol and k not in cands:
            cands[k] = (a, b)
    cuts, lasta = [], -1.0
    for k in sorted(cands):
        if cands[k][0] > lasta + 0.05:
            cuts.append((k + 1, cands[k][0], cands[k][1])); lasta = cands[k][0]     # (first word of next phrase, pause start, pause end)
    out, k0, S = [], 0, iv[0][0]
    for k1, a, b in cuts:
        out += spread(k0, k1, S, a)
        k0, S = k1, b
    out += spread(k0, len(tokens), S, iv[-1][1])
    return out, len(cuts)


def speech_end(wav, dur):
    """When the voice actually stops, from the audio itself."""
    return speech_intervals(pause_list(wav, dur), dur)[-1][1]


def repair_times(words, t_end):
    """whisper sometimes squeezes the last words of a clip into one instant (or gives one word a huge duration).
    Spread any such run of words over the real time between the last good word and the end of speech."""
    w = [list(x) for x in words]
    bad = lambda t: (t[2] - t[1]) > 1.0 or (t[2] - t[1]) <= 0.02
    fixed = 0
    i = len(w) - 1
    while i >= 0 and bad(w[i]):
        i -= 1
    first = i + 1                                  # start of the bad tail
    if first < len(w):
        lo, hi = w[first][1], t_end
        if w[first][1] >= t_end - 0.05:            # even the start is wrong: begin after the last good word
            lo = w[first - 1][2] if first > 0 else 0.0
        tot = sum(len(x[0]) + 1 for x in w[first:])
        cur = lo
        for x in w[first:]:
            d = (hi - lo) * (len(x[0]) + 1) / tot
            x[1], x[2] = cur, cur + d
            cur += d
        fixed = len(w) - first
    # zero-length runs inside the note: spread across the gap between their neighbours
    k = 0
    while k < len(w):
        if (w[k][2] - w[k][1]) <= 0.02 and k < first:
            j = k
            while j < first and (w[j][2] - w[j][1]) <= 0.02:
                j += 1
            lo = w[k - 1][2] if k > 0 else w[k][1]
            hi = w[j][1] if j < len(w) else t_end
            hi = max(hi, lo + 0.1 * (j - k))
            tot = sum(len(x[0]) + 1 for x in w[k:j]); cur = lo
            for x in w[k:j]:
                d = (hi - lo) * (len(x[0]) + 1) / tot
                x[1], x[2] = cur, cur + d; cur += d
            fixed += j - k
            k = j
        else:
            k += 1
    return [tuple(x) for x in w], fixed


def find_time(note, phrase):
    """Time (s, inside the note) of the first word of `phrase` as actually spoken."""
    toks = norm(phrase).split()
    src = note.get("aligned") or note["words"]
    ws = [norm(w) for w, _, _ in src]
    best, at = 0.0, None
    for i in range(len(ws) - len(toks) + 1):
        r = difflib.SequenceMatcher(None, " ".join(ws[i:i + len(toks)]), " ".join(toks)).ratio()
        if r > best:
            best, at = r, i
    if at is not None and best >= 0.72:
        return src[at][1]
    print(f"  warn: phrase {phrase!r} not found in note {note['id']} (best {best:.2f}); placing proportionally")
    idx = note["script"].lower().find(phrase.lower())
    frac = idx / max(len(note["script"]), 1) if idx >= 0 else 0.5
    return 0.2 + frac * (note["dur"] - 0.4)


def subtitle_cues(note):
    words = note.get("aligned") or [(w.replace("deli", "Delhi"), a, b) for w, a, b in note["words"]]
    sentences, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[.!?]$", w[0]):
            sentences.append(cur); cur = []
    if cur:
        sentences.append(cur)
    cues = []
    for sent in sentences:
        total = sum(len(w[0]) + 1 for w in sent)
        n = max(1, -(-total // 62))                      # about 62 characters per subtitle at most
        cumc, c = [], 0
        for w in sent:
            c += len(w[0]) + 1; cumc.append(c)
        brk = []
        for i in range(1, n):
            tgt = total * i / n
            best = None
            for k in range(1, len(sent) - 2):
                if abs(cumc[k] - tgt) > 14 or (brk and k <= brk[-1] + 1):
                    continue
                gap = sent[k + 1][1] - sent[k][2]
                sc = (gap >= 0.15, round(gap, 2), -abs(cumc[k] - tgt))   # prefer a real pause, then the closest to even
                if best is None or sc > best[0]:
                    best = (sc, k)
            if best:
                brk.append(best[1])
        start = 0
        for k in brk + [len(sent) - 1]:
            cues.append(sent[start:k + 1]); start = k + 1
    out = []
    for g in cues:
        text = " ".join(w for w, _, _ in g)
        if len(text) > 44:
            mid = len(text) // 2
            cut = min((m.start() for m in re.finditer(" ", text)), key=lambda p: abs(p - mid))
            text = text[:cut] + "\n" + text[cut + 1:]
        out.append([g[0][1], g[-1][2] + 0.2, text])
    for k in range(len(out) - 1):
        out[k][1] = min(out[k][1], out[k + 1][0] - 0.02)
    return [tuple(c) for c in out]


def cues_in(sent, cues):
    first = sent[0][1]
    return [c for c in cues if c[0][1] >= first]


# ---------------------------------------------------------------- driver
class Rec:
    def __init__(self, page):
        self.page = page

    def frame(self):
        return self.page.frame(name="view")

    async def go(self, url, wait="load"):
        await self.page.evaluate("u=>go(u)", url)
        await asyncio.sleep(0.4)
        for _ in range(60):
            f = self.frame()
            if f and f.url.startswith(url.split("#")[0].split("?")[0]):
                try:
                    await f.wait_for_load_state(wait, timeout=8000); break
                except Exception:
                    pass
            await asyncio.sleep(0.2)

    async def js(self, expr, arg=None):
        return await self.frame().evaluate(expr, arg)

    async def wait(self, sel, n=1, timeout=25):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if await self.js("([s,n])=>__d.count(s)>=n", [sel, n]):
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.15)
        print(f"  warn: timed out waiting for {sel}")
        return False

    async def box(self, sel, i=0, pad=10):
        ok = await self.js("([s,i,p])=>{__d.reveal(s,i);return __d.box(s,{i:i,pad:p})}", [sel, i, pad]);
        if not ok: print(f"  warn: no element for box {sel}[{i}]")

    async def mark(self, sel, i=0, pad=4):
        ok = await self.js("([s,i,p])=>{__d.reveal(s,i);return __d.mark(s,{i:i,pad:p})}", [sel, i, pad])
        if not ok: print(f"  warn: no element for mark {sel}[{i}]")

    async def clear(self):
        await self.js("()=>__d.clear()")

    async def point(self, sel, i=0, fx=.5, fy=.5):
        await self.js("([s,i,fx,fy])=>{__d.reveal(s,i);return __d.moveTo(s,{i:i,fx:fx,fy:fy})}", [sel, i, fx, fy])
        await asyncio.sleep(0.9)

    async def click(self, sel, i=0, fx=.5, fy=.5):
        await self.point(sel, i, fx, fy)
        await self.js("([s,i,fx,fy])=>__d.ripple(s,{i:i,fx:fx,fy:fy})", [sel, i, fx, fy])
        await asyncio.sleep(0.12)
        ok = await self.js("([s,i])=>__d.click(s,i)", [sel, i])
        if not ok: print(f"  warn: nothing to click {sel}[{i}]")

    async def slider(self, sel, a, b, steps=14, secs=1.4):
        await self.point(sel, 0, fx=(a - 1.5) / 6.5, fy=.5)
        for k in range(steps + 1):
            v = a + (b - a) * k / steps
            await self.js("([s,v])=>__d.setSlider(s,v)", [sel, v])
            await self.js("([s,v])=>__d.moveTo(s,{fx:(v-1.5)/6.5,fy:.5})", [sel, v])
            await asyncio.sleep(secs / steps)
        await self.js("s=>__d.fireChange(s)", sel)


async def run(notes, scenes, out):
    FR = WORK / "frames"
    shutil.rmtree(FR, ignore_errors=True); FR.mkdir(parents=True)
    frames = []
    async with async_playwright() as p:
        br = await p.chromium.launch(channel="chrome", headless=True, args=["--hide-scrollbars"])
        ctx = await br.new_context(viewport={"width": 1920, "height": 1080}, color_scheme="light", device_scale_factor=1)
        await ctx.add_init_script(path=str(ROOT / "overlay.js"))
        page = await ctx.new_page()
        problems = []
        page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
        page.on("console", lambda m: problems.append(f"console {m.type}: {m.text[:160]}") if m.type == "error" else None)
        page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url[:120]}") if r.status >= 400 and "localhost:8000" in r.url else None)
        await page.goto(STAGE)
        await page.evaluate("fade(true)")
        cdp = await ctx.new_cdp_session(page)
        n = {"i": 0}

        def on_frame(ev):
            ts = ev["metadata"]["timestamp"]; path = FR / f"{n['i']:06d}.jpg"; n["i"] += 1
            path.write_bytes(base64.b64decode(ev["data"])); frames.append((ts, path))
            asyncio.ensure_future(cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]}))
        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
        rec = Rec(page)
        await rec.go(f"{DECK}#s1")
        await asyncio.sleep(1.0)
        T0 = time.time()
        await page.evaluate("fade(false)")
        starts, t = [], 1.4
        for sc in scenes:
            note = next(x for x in notes if x["id"] == sc["id"])
            t += sc.get("gap", 0.55)
            starts.append(t); t += note["dur"] + sc.get("tail", 0)
        total = t + 1.6
        now = lambda: time.time() - T0
        async def at(tt):
            d = tt - now()
            if d > 0: await asyncio.sleep(d)
        for sc, st in zip(scenes, starts):
            note = next(x for x in notes if x["id"] == sc["id"])
            print(f"note {sc['id']} at {st:5.1f}s ({note['dur']:.1f}s)")
            pre_at = st - sc.get("gap", 0.55) + 0.05
            await at(pre_at)
            try:
                await rec.clear(); await sc["pre"](rec)
            except Exception as e:
                print("  pre failed:", e)
            events = [(st + find_time(note, ph), fn) for ph, fn in sc["events"]]
            cues = subtitle_cues(note)
            events += [(st + a, ("sub", txt)) for a, b, txt in cues]
            if cues:
                events += [(st + cues[-1][1], ("sub", ""))]
            for when, fn in sorted(events, key=lambda e: e[0]):
                await at(when)
                try:
                    if isinstance(fn, tuple):
                        await page.evaluate("t=>sub(t)", fn[1])
                    else:
                        await fn(rec)
                except Exception as e:
                    print("  event failed:", e)
            await at(st + note["dur"])
        await at(total - 1.0)
        await page.evaluate("fade(true)")
        await at(total)
        await cdp.send("Page.stopScreencast")
        await br.close()
        print("problems seen in the browser:", problems or "none")
    # ---- assemble video from timestamped frames
    frames.sort()
    lines, prev = [], None
    keep = [(max(0.0, ts - frames[0][0]), p) for ts, p in frames]
    base = None
    pts = [(ts - T0, p) for ts, p in frames]
    pre = [x for x in pts if x[0] <= 0]
    seq = ([(0.0, pre[-1][1])] if pre else []) + [x for x in pts if x[0] > 0]
    for i, (tt, pth) in enumerate(seq):
        nxt = seq[i + 1][0] if i + 1 < len(seq) else total
        lines.append(f"file '{pth}'\nduration {max(nxt - tt, 0.001):.4f}")
    lines.append(f"file '{seq[-1][1]}'")
    (WORK / "frames.txt").write_text("\n".join(lines))
    # ---- audio
    parts = []
    def silence(sec, name):
        f = WORK / name
        sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", f"{sec:.4f}", "-c:a", "pcm_s16le", f)
        return f
    cursor = 0.0
    for k, (sc, st) in enumerate(zip(scenes, starts)):
        note = next(x for x in notes if x["id"] == sc["id"])
        gap = st - cursor
        parts.append(silence(max(gap, 0.0), f"gap{k}.wav")); parts.append(note["wav"]); cursor = st + note["dur"]
    parts.append(silence(max(total - cursor, 0.0), "gap_end.wav"))
    for x in parts:
        fmt = sh("ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,channels", "-of", "csv=p=0", x).stdout.strip()
        if fmt != "48000,1":
            raise SystemExit(f"audio part {x} is {fmt}, expected 48000,1")
    (WORK / "audio.txt").write_text("\n".join(f"file '{x}'" for x in parts))
    sh("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", WORK / "audio.txt", "-c:a", "pcm_s16le", WORK / "audio.wav")
    sh("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", WORK / "frames.txt", "-i", WORK / "audio.wav",
       "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "160k",
       "-t", f"{total:.3f}", "-movflags", "+faststart", out)
    print(f"done: {out}  ({total:.1f}s)")
    verify_audio(out, notes, scenes, starts)


def verify_audio(out, notes, scenes, starts):
    """Listen to the finished video: transcribe each note's time window and compare with the script."""
    bad = 0
    for sc, st in zip(scenes, starts):
        note = next(x for x in notes if x["id"] == sc["id"])
        w = WORK / f"v{sc['id']}.wav"
        sh("ffmpeg", "-v", "error", "-y", "-ss", f"{st:.2f}", "-t", f"{note['dur']:.2f}", "-i", out, "-vn", "-ar", "16000", "-ac", "1", w)
        sh("whisper-cli", "-m", MODEL, "-f", w, "-otxt", "-of", WORK / f"v{sc['id']}", "-np")
        heard = (WORK / f"v{sc['id']}.txt").read_text().strip().replace("\n", " ")
        r = difflib.SequenceMatcher(None, norm(heard), norm(note["script"])).ratio()
        flag = "ok " if r >= 0.8 else "BAD"
        bad += r < 0.8
        print(f"  audio check note {sc['id']}: {flag} {r:.2f}  heard: {heard[:60]!r}")
    print("AUDIO VERIFIED" if not bad else f"AUDIO PROBLEM in {bad} notes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", required=True)
    ap.add_argument("--out", default=str(ROOT / "out" / "seatwise-demo.mp4"))
    a = ap.parse_args()
    # keep the deck up to date with the latest data
    deck = (ROOT / "slides" / "index.html").read_text().replace("__DATA__", (ROOT / "slides" / "data.json").read_text())
    (ROOT / "slides" / "deck.html").write_text(deck)
    sys.path.insert(0, str(ROOT))
    from scenes import SCENES
    notes = prepare_notes(pathlib.Path(a.voice))
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(notes, SCENES, a.out))


if __name__ == "__main__":
    main()
