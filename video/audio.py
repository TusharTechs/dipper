"""Sound for the demo film: composed music, the narration and soft interface clicks, mixed to one stereo WAV.

The music is synthesised here, so there is nothing to license: a dark D-minor pad under the problem, then an
F-major progression with a plucked arpeggio from the logo on, a bass pulse under the live demo, and a held final
chord. It ducks under the narration. make.mjs runs this after timing the film:
    uv run python video/audio.py video/out/timeline.json video/out/audio.wav
"""

import json
import sys
import wave
from pathlib import Path

import numpy as np

SR = 48000
rng = np.random.default_rng(7)


def midi(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        if w.getsampwidth() != 2 or w.getframerate() != SR:
            raise SystemExit(f"{path}: expected 16-bit {SR} Hz audio")
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
        return x.reshape(-1, w.getnchannels()).mean(axis=1)


def env_adsr(n: int, attack: float, release: float, hold: int) -> np.ndarray:
    """Raised-cosine attack, flat hold, raised-cosine release; n samples in total."""
    e = np.zeros(n, np.float32)
    a, r = int(attack * SR), int(release * SR)
    t = np.arange(n)
    e[: min(a, n)] = 0.5 - 0.5 * np.cos(np.pi * t[: min(a, n)] / max(a, 1))
    e[a:hold] = 1
    rel = t[hold : hold + r] - hold
    e[hold : hold + r] = 0.5 + 0.5 * np.cos(np.pi * rel / max(r, 1))
    return e


def add(buf: np.ndarray, at: float, sig: np.ndarray) -> None:
    i = int(at * SR)
    if i >= len(buf) or i + len(sig) <= 0:
        return
    j = min(len(buf), i + len(sig))
    buf[max(i, 0) : j] += sig[max(0, -i) : j - i]


def pad(notes, dur: float, level: float) -> np.ndarray:
    """A soft chord: a few decaying partials per note, detuned left and right for width."""
    n = int((dur + 2.2) * SR)
    t = np.arange(n) / SR
    out = np.zeros((n, 2), np.float32)
    e = env_adsr(n, 1.4, 2.2, int(dur * SR))
    for m in notes:
        f = midi(m)
        for ch, det in ((0, 0.9988), (1, 1.0012)):
            s = sum(a * np.sin(2 * np.pi * f * det * h * t + rng.uniform(0, 6.28)) for h, a in ((1, 1.0), (2, 0.28), (3, 0.09)))
            s *= 1 + 0.08 * np.sin(2 * np.pi * 0.23 * t + m)  # slow shimmer
            out[:, ch] += s * e
    return out * (level / max(1, len(notes)))


def pluck(m: float, level: float, decay: float = 0.45, pan: float = 0.0) -> np.ndarray:
    n = int((decay * 6) * SR)
    t = np.arange(n) / SR
    f = midi(m)
    s = np.sin(2 * np.pi * f * t) + 0.22 * np.sin(4 * np.pi * f * t) * np.exp(-t / (decay * 0.4)) + 0.06 * np.sin(6 * np.pi * f * t)
    s *= np.exp(-t / decay) * np.minimum(1, t / 0.004)
    return np.stack([s * (1 - pan) * level, s * (1 + pan) * level], axis=1).astype(np.float32)


def bell(m: float, level: float) -> np.ndarray:
    n = int(3.5 * SR)
    t = np.arange(n) / SR
    f = midi(m)
    s = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t / d) for r, a, d in ((1, 1, 1.6), (2.76, 0.35, 0.7), (5.4, 0.15, 0.35)))
    s *= np.minimum(1, t / 0.003) * level
    return np.stack([s, s], axis=1).astype(np.float32)


def thump(level: float) -> np.ndarray:
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 52 + 60 * np.exp(-t / 0.03)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.16) * level
    return np.stack([s, s], axis=1).astype(np.float32)


def swell(dur: float, level: float) -> np.ndarray:
    """Band-limited noise rising into a hit, the classic reveal riser."""
    n = int(dur * SR)
    x = rng.standard_normal((n, 2)).astype(np.float32)
    spec = np.fft.rfft(x, axis=0)
    fr = np.fft.rfftfreq(n, 1 / SR)
    spec *= (np.exp(-((np.log(fr + 1) - np.log(1800)) ** 2) / 1.4))[:, None]
    x = np.fft.irfft(spec, n=n, axis=0)
    x /= np.abs(x).max() + 1e-9
    e = (np.arange(n) / n) ** 2.5
    return (x * e[:, None] * level).astype(np.float32)


def click(level: float) -> np.ndarray:
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    s = (0.6 * rng.standard_normal(n) * np.exp(-t / 0.002) + np.sin(2 * np.pi * 2300 * t) * np.exp(-t / 0.012)) * level
    return np.stack([s, s], axis=1).astype(np.float32)


def reverb(x: np.ndarray, seconds: float = 2.6, wet: float = 0.3) -> np.ndarray:
    """Convolution with decaying, darkening stereo noise, block by block (overlap-add)."""
    m = int(seconds * SR)
    t = np.arange(m) / SR
    ir = rng.standard_normal((m, 2)).astype(np.float32) * np.exp(-t / (seconds / 6.5))[:, None]
    k = int(SR * 0.0004)
    ir = np.stack([np.convolve(ir[:, c], np.ones(k) / k, "same") for c in range(2)], axis=1)  # soften the tail
    ir[: int(0.012 * SR)] = 0
    ir /= np.sqrt((ir**2).sum(axis=0))
    block = 1 << 17
    size = 1 << int(np.ceil(np.log2(block + m)))
    H = np.fft.rfft(ir, n=size, axis=0)
    y = np.zeros((len(x) + m, 2), np.float32)
    for i in range(0, len(x), block):
        seg = np.fft.irfft(np.fft.rfft(x[i : i + block], n=size, axis=0) * H, n=size, axis=0)
        j = min(len(y), i + size)
        y[i:j] += seg[: j - i]
    return x * (1 - wet) + y[: len(x)] * wet * 3.2


def main() -> None:
    tl_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    tl = json.loads(tl_path.read_text())
    base = tl_path.parent
    dur = tl["duration"]
    n = int((dur + 0.5) * SR)
    start = {s["id"]: s["start"] for s in tl["scenes"]}
    t_logo, t_live, t_loop, t_end = start["logo"], start["live"], start["loop"], start["end"]

    # ---------- music ----------
    music = np.zeros((n, 2), np.float32)
    dark = [[50, 53, 57], [46, 50, 53], [43, 46, 50], [45, 50, 52]]  # Dm Bb Gm Asus4
    bright = [[53, 57, 60, 64], [48, 55, 60, 64], [50, 53, 57, 60], [46, 53, 57, 62]]  # Fmaj7 C Dm7 Bbmaj7
    beat = 60 / 80
    t = 0.0
    i = 0
    while t < t_logo - 0.2:  # the problem: slow and low
        d = min(4 * beat * 1.35, t_logo - t)
        add(music, t, pad(dark[i % 4], d, 0.16))
        add(music, t, pluck(dark[i % 4][0] - 12, 0.10, decay=1.4))
        i += 1
        t += d
    add(music, t_logo - 1.8, swell(1.8 + 0.4, 0.05))
    add(music, t_logo + 0.1, thump(0.35))
    t, i = t_logo, 0
    while t < t_end + 1.0:  # what we built, the live demo and the close
        add(music, t, pad(bright[i % 4], 4 * beat, 0.14))
        for b in range(4):
            if t_live <= t + b * beat < t_end:
                add(music, t + b * beat, pluck(bright[i % 4][0] - 24, 0.16, decay=0.35))  # bass pulse
        for s8 in range(8):
            at = t + s8 * beat / 2
            if at > t_logo + 2.2 and at < t_end + 0.5:
                notes = bright[i % 4]
                m = notes[[0, 1, 2, 3, 2, 1, 2, 3][s8] % len(notes)] + 12
                add(music, at, pluck(m, 0.075 if at < t_live else 0.06, decay=0.4, pan=0.35 * (1 if s8 % 2 else -1)))
        i += 1
        t += 4 * beat
    add(music, t_end + 1.0, pad([41, 53, 57, 60, 67], max(1.0, dur - t_end - 3.2), 0.2))  # F add9, held to the end
    for at, m in ((t_logo + 2.3, 77), (start.get("d-localized", t_live) + 0.4, 81), (t_end + 1.6, 77)):
        add(music, at, bell(m, 0.10))
    music = reverb(music)
    ramp = np.clip(np.arange(n) / (2.0 * SR), 0, 1) * np.clip((dur - 0.3 - np.arange(n) / SR) / 2.5, 0, 1)
    music *= ramp[:, None]

    # ---------- narration, and ducking the music under it ----------
    vo = np.zeros(n, np.float32)
    mask = np.zeros(n, np.float32)
    for s in tl["scenes"]:
        if not s.get("vo"):
            continue
        x = read_wav(base / s["vo"]["file"])
        add(vo, s["vo"]["start"], x)
        a = int(s["vo"]["start"] * SR)
        mask[a : a + len(x)] = 1
    win = int(0.35 * SR)
    duck = np.convolve(mask, np.ones(win) / win, "same")
    vo *= 0.5 / (np.abs(vo).max() + 1e-9)
    music *= 0.34 / (np.abs(music).max() + 1e-9)
    music *= (1 - 0.55 * duck)[:, None]

    sfx = np.zeros((n, 2), np.float32)
    for at in tl.get("taps", []):
        add(sfx, at, click(0.05))

    mix = music + sfx + vo[:, None]
    mix *= 0.89 / (np.abs(mix).max() + 1e-9)
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"audio: {out_path} ({len(pcm) / SR:.1f} s)")


if __name__ == "__main__":
    main()
