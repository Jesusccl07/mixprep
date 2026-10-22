"""Montaje de versiones para pinchar: LiveMashup, Extended, acapella e instrumental."""
import re
import subprocess

import numpy as np
import soundfile as sf
from scipy.signal import butter, fftconvolve, sosfilt

from analysis import NOTES, key_info

SR = 44100
RNG = np.random.default_rng(7)


# ---------------------------------------------------------------- utilidades

def seg(x, a, b):
    """Trozo [a, b) de x con relleno de ceros fuera de rango."""
    a, b = int(a), int(b)
    out = np.zeros((b - a, x.shape[1]), np.float32)
    lo, hi = max(a, 0), min(b, len(x))
    if hi > lo:
        out[lo - a: hi - a] = x[lo:hi]
    return out


def ramp(n, shape="equalpower"):
    t = np.linspace(0, 1, n, dtype=np.float32)
    return np.sin(t * np.pi / 2) if shape == "equalpower" else t


def highpass(x, hz):
    sos = butter(2, hz, "highpass", fs=SR, output="sos")
    return sosfilt(sos, x, axis=0).astype(np.float32)


# ---------------------------------------------------------------- batería sintética

def _noise(n):
    return RNG.standard_normal(n).astype(np.float32)


def kick():
    t = np.arange(int(0.42 * SR)) / SR
    f = 42 + 110 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) * np.exp(-t * 8.5) * 0.95 + np.sin(2 * np.pi * 1800 * t) * np.exp(-t * 400) * 0.15).astype(np.float32)


def snare():
    t = np.arange(int(0.26 * SR)) / SR
    n = sosfilt(butter(2, [1500, 9000], "bandpass", fs=SR, output="sos"), _noise(len(t)))
    return (n * np.exp(-t * 20) * 0.5 + np.sin(2 * np.pi * 190 * t) * np.exp(-t * 26) * 0.4).astype(np.float32)


def clap():
    t = np.arange(int(0.3 * SR)) / SR
    n = sosfilt(butter(2, [900, 7000], "bandpass", fs=SR, output="sos"), _noise(len(t)))
    env = sum(np.exp(-np.clip(t - d, 0, None) * 38) * (t >= d) for d in (0, 0.011, 0.023)) * 0.33 + np.exp(-t * 14) * 0.25
    return (n * env * 0.8).astype(np.float32)


def hat(open_=False):
    t = np.arange(int((0.22 if open_ else 0.06) * SR)) / SR
    n = sosfilt(butter(2, 7500, "highpass", fs=SR, output="sos"), _noise(len(t)))
    return (n * np.exp(-t * (14 if open_ else 90)) * 0.28).astype(np.float32)


PATTERNS = {
    # posiciones en semicorcheas (0..15) dentro del compás
    "house": {
        "A": {"kick": [0, 4, 8, 12], "hat": [2, 6, 10, 14]},
        "B": {"kick": [0, 4, 8, 12], "clap": [4, 12], "hat": [2, 6, 10, 14], "hat16": [1, 3, 5, 7, 9, 11, 13, 15]},
    },
    "dembow": {
        "A": {"kick": [0, 4, 8, 12], "hat": [2, 6, 10, 14]},
        "B": {"kick": [0, 4, 8, 12], "snare": [3, 6, 11, 14], "hat": [2, 6, 10, 14]},
    },
    "hiphop": {
        "A": {"kick": [0, 7, 10], "hat": [0, 2, 4, 6, 8, 10, 12, 14]},
        "B": {"kick": [0, 7, 10], "snare": [4, 12], "hat": [0, 2, 4, 6, 8, 10, 12, 14], "hat16": [15]},
    },
}


def drum_loop(bpm, bars, genre="house", change_every=4, fill=True):
    """Bucle de `bars` compases: patrón A los primeros `change_every`, patrón B después."""
    spb = 60.0 / bpm
    step = spb / 4
    n = int(round(bars * 4 * spb * SR))
    out = np.zeros(n + SR, np.float32)
    samples = {"kick": kick(), "snare": snare(), "clap": clap(), "hat": hat(), "hat16": hat() * 0.55}
    pats = PATTERNS.get(genre, PATTERNS["house"])
    for bar in range(bars):
        pat = pats["A" if (bar // change_every) % 2 == 0 else "B"]
        for name, steps in pat.items():
            for s in steps:
                pos = int(round((bar * 16 + s) * step * SR))
                smp = samples[name] * (0.85 if name == "hat16" else 1.0)
                out[pos: pos + len(smp)] += smp[: len(out) - pos]
        if fill and bar % change_every == change_every - 1:
            for k in range(4):  # redoble de caja en el último tiempo del bloque
                pos = int(round((bar * 16 + 12 + k) * step * SR))
                smp = samples["snare"] * (0.5 + 0.12 * k)
                out[pos: pos + len(smp)] += smp[: len(out) - pos]
    out = out[:n]
    return np.repeat(out[:, None], 2, axis=1) * 0.9


# ---------------------------------------------------------------- efectos de transición

def make_riser(n, beats_n):
    """Ruido que sube de filtro y de volumen."""
    t = np.linspace(0, 1, n, dtype=np.float32)
    nz = np.stack([_noise(n), _noise(n)], axis=1)
    parts = []
    for cut in (1500, 4000):
        parts.append(highpass(nz, cut))
    return (parts[0] * (1 - t[:, None]) + parts[1] * t[:, None]) * (t[:, None] ** 2.2) * 0.22


def transition(intro, bpm, beats=4, highpass_to=700, reverb=True, noise=True):
    """Barrido de paso alto + riser en el final de la intro. Devuelve (intro_con_fx, cola_de_reverb)."""
    n = int(round(beats * 60.0 / bpm * SR))
    n = min(n, len(intro))
    head, tail = intro[:-n], intro[-n:].copy()
    t = ramp(n, "linear")[:, None]
    tail = tail * (1 - t) + highpass(tail, highpass_to) * t
    if noise:
        tail = tail + make_riser(n, beats)
    wet = np.zeros((int(1.2 * SR), 2), np.float32)
    if reverb:
        src = intro[-int(0.5 * SR):] * 0.9
        ir_n = int(1.1 * SR)
        ir = (RNG.standard_normal((ir_n, 2)) * np.exp(-np.linspace(0, 7, ir_n))[:, None]).astype(np.float32)
        ir = highpass(ir, 300)
        for c in range(2):
            w = fftconvolve(src[:, c], ir[:, c] * 0.045)
            wet[: min(len(wet), len(w)), c] = w[: len(wet)]
    return np.concatenate([head, tail]), wet


# ---------------------------------------------------------------- montaje

def build(stems, analysis, o):
    """stems: dict mix/vocals/instrumental -> (n, 2) float32 a 44100.  Devuelve (audio, info)."""
    a = analysis
    bpm = a["bpm"]
    spbar = a["seconds_per_bar"]
    d0 = a["downbeat_times"][0]
    nb = len(a["downbeat_times"])
    mix, voc, ins = stems["mix"], stems["vocals"], stems["instrumental"]

    def pos(k):
        return int(round((d0 + k * spbar) * SR))

    version = o["version"]
    N = int(o["intro_bars"])
    E = int(o["vocal_entry_bar"]) if o.get("vocal_entry_bar", -1) >= 0 else int(a["vocal_entry_bar"])
    segs = [s for s in a["segments"]]
    choruses = [s for s in segs if s["label"] == "chorus"]

    # ---- intro
    if version == "extended":
        S = 0
        intro = drum_loop(bpm, N, o.get("drum_genre", "house"), change_every=4)
    else:
        S = max(0, E)
        a_bar = S - N if S - N >= 0 else S  # antes de la voz; si no cabe, se "repite" la melodía
        if o.get("intro_from_bar", -1) >= 0:
            a_bar = int(o["intro_from_bar"])
        intro = seg(ins, pos(a_bar), pos(a_bar + N))

    wet = None
    if o.get("fx", True):
        intro, wet = transition(
            intro, bpm, beats=int(o.get("fx_beats", 4)),
            highpass_to=float(o.get("fx_highpass", 700)),
            reverb=bool(o.get("fx_reverb", True)), noise=bool(o.get("fx_noise", True)),
        )

    # ---- cuerpo + final
    ending = o["ending"]
    if ending == "acapella":
        c = o.get("chorus_bar", -1)
        if c is None or c < 0:
            cand = [s for s in choruses if s["bar"] > S + 1]
            if version == "extended":
                c = (cand[-1]["bar"] if cand else max(S + 8, nb - 12))
                c_end = (cand[-1]["end_bar"] if cand else min(nb, c + 8))
            else:
                c = (cand[0]["bar"] if cand else S + 16)
                c_end = (cand[0]["end_bar"] if cand else c + 8)
        else:
            nxt = [s for s in segs if s["bar"] >= c and s["label"] == "chorus"]
            c_end = nxt[0]["end_bar"] if nxt else c + 8
        c = int(max(S + 2, c))
        c_end = int(min(max(c_end, c + 4), nb))
        body = seg(mix, pos(S), pos(c - 1))
        fade_n = pos(c) - pos(c - 1)
        f = ramp(fade_n)[::-1][:, None] if o.get("fade_shape", "equalpower") == "equalpower" else (1 - ramp(fade_n, "linear"))[:, None]
        fade = seg(voc, pos(c - 1), pos(c)) + seg(ins, pos(c - 1), pos(c)) * f
        acap = seg(voc, pos(c), pos(c_end))
        k = int(60.0 / bpm * SR)
        if len(acap) > k:
            acap[-k:] *= np.linspace(1, 0, k, dtype=np.float32)[:, None]
        song = np.concatenate([body, fade, acap])
        info = {"acapella_bar": c, "acapella_end_bar": c_end}
    elif ending == "outro":
        end_bar = nb - 1
        song = seg(mix, pos(S), pos(end_bar))
        out = drum_loop(bpm, 8, o.get("drum_genre", "house"), change_every=4, fill=False)
        out[-int(spbar * SR):] *= np.linspace(1, 0, int(spbar * SR), dtype=np.float32)[:, None]
        song = np.concatenate([song, out])
        info = {}
    else:
        song = seg(mix, pos(S), len(mix))
        info = {}

    if wet is not None:
        n = min(len(wet), len(song))
        song[:n] += wet[:n]
    out = np.concatenate([intro, song])
    info.update(song_start_bar=S, intro_bars=N, vocal_entry_bar=E, output_vocal_entry=round(len(intro) / SR, 3))
    return out, info


def render_simple(stems, which):
    return stems["vocals"] if which == "acapella" else stems["instrumental"]


# ---------------------------------------------------------------- salida

def safe(s):
    return re.sub(r'[\\/:*?"<>|]', "", s).strip()


def filename(artist, title, version_label, bpm, key, camelot, name_bpm=True, name_key=False):
    parts = [f"{artist} - {title}" if artist else title, version_label]
    if name_bpm:
        parts.append(f"{round(bpm)} BPM")
    k = (key.replace(" min", "m").replace(" maj", "") + " ") if name_key and key else ""
    if camelot:
        parts.append(f"{k}{camelot}".strip())
    parts.append("MixPrep")
    return safe(" - ".join(parts)) + ".mp3"


def encode_mp3(audio, out_path, tags, tempo_ratio=1.0, semitones=0, normalize_db=-1.0, bitrate="320k"):
    peak = float(np.abs(audio).max()) or 1.0
    if normalize_db is not None:
        audio = audio * (10 ** (normalize_db / 20) / peak)
    tmp = str(out_path) + ".tmp.wav"
    sf.write(tmp, audio, SR, subtype="FLOAT")
    af = []
    if tempo_ratio != 1.0 or semitones:
        af.append(f"rubberband=tempo={tempo_ratio:.6f}:pitch={2 ** (semitones / 12):.6f}:pitchq=quality")
    if normalize_db is not None and af:
        af.append(f"alimiter=limit={10 ** (normalize_db / 20):.4f}")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", tmp]
    if af:
        cmd += ["-af", ",".join(af)]
    cmd += ["-codec:a", "libmp3lame", "-b:a", bitrate, "-id3v2_version", "3"]
    for k, v in tags.items():
        if v not in (None, ""):
            cmd += ["-metadata", f"{k}={v}"]
    cmd.append(str(out_path))
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        try:
            import os
            os.remove(tmp)
        except OSError:
            pass
