"""Check voice notes for the problems that cause static: clipping, a noisy room, or a level that is too low or high.

    .venv/bin/python video/check_voice.py video/voice
"""
import pathlib, re, subprocess, sys

EXT = ("m4a", "mp3", "wav", "ogg", "opus", "aac", "caf", "aiff", "aif", "flac", "mp4", "webm")
d = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "video/voice")
files = sorted(p for p in d.iterdir() if p.suffix.lstrip(".").lower() in EXT)
if not files:
    sys.exit(f"no audio files in {d}")
bad = 0
print(f"{'file':32s} {'sec':>5s} {'peak':>7s} {'speech':>7s} {'room':>7s}  verdict")
for f in files:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(f), "-af", "astats=metadata=0", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    def g(label):
        m = re.findall(rf"{label}: (-?[\d.]+|-inf)", out)
        return float(m[-1]) if m and m[-1] != "-inf" else -99.0
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]))
    peak, rms, trough, flat = g("Peak level dB"), g("RMS level dB"), g("RMS trough dB"), g("Flat factor")
    issues = []
    if peak > -0.5 or flat > 3:
        issues.append("CLIPPED: too loud, lower the input volume and record again")
    def level(ss, t):
        o = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(ss), "-t", str(t), "-i", str(f), "-af", "astats=metadata=0", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
        m = re.findall(r"RMS level dB: (-?[\d.]+|-inf)", o)
        return float(m[-1]) if m and m[-1] != "-inf" else -99.0
    noise = min(level(0, 0.35), level(max(dur - 0.35, 0), 0.35))
    snr = rms - noise
    trough = noise
    if snr < 25:
        issues.append(f"noisy: only {snr:.0f} dB between your voice and the room (want 30+)")
    if rms < -45:
        issues.append("very quiet: move closer to the mic")
    bad += bool(issues)
    print(f"{f.name[:32]:32s} {dur:5.1f} {peak:7.1f} {rms:7.1f} {trough:7.1f}  {'; '.join(issues) or 'good'}")
print("\nAll notes look clean." if not bad else f"\n{bad} of {len(files)} notes have a problem.")
