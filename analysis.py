"""Análisis musical: BPM, rejilla de beats/compases, tonalidad, entrada de voz y estructura."""
import math

import librosa
import numpy as np
from scipy.ndimage import gaussian_filter1d

ANALYSIS_SR = 22050
HOP = 256

KS_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
CAMELOT_MAJ = {0: "8B", 1: "3B", 2: "10B", 3: "5B", 4: "12B", 5: "7B", 6: "2B", 7: "9B", 8: "4B", 9: "11B", 10: "6B", 11: "1B"}
CAMELOT_MIN = {0: "5A", 1: "12A", 2: "7A", 3: "2A", 4: "9A", 5: "4A", 6: "11A", 7: "6A", 8: "1A", 9: "8A", 10: "3A", 11: "10A"}


def key_info(root, mode):
    root = int(root) % 12
    minor = mode == "minor"
    return {
        "key": f"{NOTES[root]} {'min' if minor else 'maj'}",
        "camelot": (CAMELOT_MIN if minor else CAMELOT_MAJ)[root],
        "root": root,
        "mode": "minor" if minor else "major",
    }


def to_mono(x, sr_in):
    m = x.mean(axis=1) if x.ndim == 2 else x
    if sr_in != ANALYSIS_SR:
        m = librosa.resample(m, orig_sr=sr_in, target_sr=ANALYSIS_SR)
    return m.astype(np.float32)


# ---------------------------------------------------------------- rejilla

def make_grid(bpm, first_bar, beats_per_bar, duration):
    """Rejilla uniforme: primer compás >= 0 y todos los beats / compases hasta el final."""
    spb = 60.0 / bpm
    spbar = spb * beats_per_bar
    t0 = first_bar - math.floor(first_bar / spbar + 1e-6) * spbar
    n_bars = int((duration - t0) // spbar) + 1
    downs = t0 + np.arange(n_bars) * spbar
    downs = downs[downs < duration]
    m = int(t0 // spb)
    beats = t0 + np.arange(-m, n_bars * beats_per_bar) * spb
    beats = beats[(beats >= 0) & (beats < duration)]
    return beats, downs, spb, spbar


def _comb_score(env, bpm, fps):
    period = fps * 60.0 / bpm
    n = int((len(env) - 1) // period)
    k = np.arange(n)
    x = np.arange(len(env))
    best, best_ph = -1.0, 0.0
    for ph in np.arange(0, period, 1.0):
        s = np.interp(ph + k * period, x, env).mean()
        if s > best:
            best, best_ph = s, ph
    return best, best_ph


def _estimate_tempo(env, sr):
    try:
        fn = getattr(librosa.feature, "tempo", None) or librosa.feature.rhythm.tempo
        t = float(np.atleast_1d(fn(onset_envelope=env, sr=sr, hop_length=HOP))[0])
    except Exception:
        t = 120.0
    while t < 78:
        t *= 2
    while t >= 176:
        t /= 2
    return t


def _refine_offset(y, sr, first_beat, spb, hop=64, win=0.03):
    """Afina la fase por debajo de un frame: desplazamiento mediano del pico real respecto a la rejilla."""
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop, n_fft=1024)
    fps = sr / hop
    n = int((len(y) / sr - first_beat) / spb)
    offs = []
    w = int(win * fps)
    for k in range(n):
        c = int(round((first_beat + k * spb) * fps))
        if c - w < 0 or c + w >= len(env):
            continue
        seg_ = env[c - w: c + w + 1]
        if seg_.max() > env.mean() * 1.5:
            offs.append((int(seg_.argmax()) - w) / fps)
    return float(np.median(offs)) if len(offs) > 8 else 0.0


def detect_grid(y, sr):
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP))
    db = librosa.amplitude_to_db(S, ref=np.max)
    env = librosa.onset.onset_strength(S=db, sr=sr, hop_length=HOP)
    fps = sr / HOP
    env_n = env / (env.max() + 1e-9)
    env_n = np.clip(env_n - gaussian_filter1d(env_n, fps * 0.8), 0, None)
    env_s = gaussian_filter1d(env_n, 1.0)

    base = _estimate_tempo(env, sr)
    # búsqueda en dos pasos: gruesa (±3 %) y fina
    coarse = np.arange(base * 0.97, base * 1.03, base * 0.002)
    scores = [(_comb_score(env_s, b, fps)[0], b) for b in coarse]
    b0 = max(scores)[1]
    fine = np.arange(b0 - 0.15, b0 + 0.15, 0.005)
    best = max((_comb_score(env_s, b, fps)[0], b) for b in fine)
    bpm = round(float(best[1]), 2)
    # la fase (dónde caen los beats) se decide dando más peso a los graves: el bombo marca el
    # beat, mientras que los hi-hats suelen caer a contratiempo y confundirían la rejilla
    lo_cut = int(160 / (sr / 2048))
    lo_env = librosa.onset.onset_strength(S=db[:lo_cut], sr=sr, hop_length=HOP)
    lo_n = lo_env / (lo_env.max() + 1e-9)
    lo_n = np.clip(lo_n - gaussian_filter1d(lo_n, fps * 0.8), 0, None)
    _, phase = _comb_score(gaussian_filter1d(env_n + 1.5 * lo_n, 1.0), bpm, fps)
    # confianza: cuánto destaca el pico frente a la media de la envolvente
    conf = float(np.clip(best[0] / (env_s.mean() + 1e-9) / 6.0, 0, 1))

    # ---------- qué beat es el "1" (de 0 a 3)
    spb = 60.0 / bpm
    first_beat = phase / fps
    first_beat += _refine_offset(y, sr, first_beat, spb)
    n_beats = int((len(y) / sr - first_beat) / spb)
    beat_t = first_beat + np.arange(n_beats) * spb
    bf = np.clip(np.round(beat_t * fps).astype(int), 0, len(env) - 1)


    def around(a, idx, w=2):
        return np.array([a[max(0, i - w): i + w + 1].max() for i in idx])

    lo_b = around(lo_env, bf)
    en_b = around(env, bf)
    chroma = librosa.feature.chroma_stft(S=S ** 2, sr=sr)
    sync = librosa.util.sync(chroma, bf, aggregate=np.mean)  # una columna por tramo entre beats
    sync = sync / (np.linalg.norm(sync, axis=0, keepdims=True) + 1e-9)
    change = np.zeros(len(bf))
    if sync.shape[1] > 1:
        c = 1 - (sync[:, 1:] * sync[:, :-1]).sum(axis=0)
        # columna j+1 empieza en el beat j: el cambio que entra en el beat j es c[j]
        m = min(len(c), len(change))
        change[:m] = c[:m]

    def z(a):
        return (a - a.mean()) / (a.std() + 1e-9)

    score = z(lo_b) + 0.7 * z(en_b) + 0.8 * z(change)
    per = np.array([score[r::4].mean() for r in range(4)])
    r = int(per.argmax())
    srt = np.sort(per)
    margin = float((srt[-1] - srt[-2]) / (np.abs(srt[-1]) + 1e-9))
    return {
        "bpm": bpm,
        "bpm_confidence": round(conf, 3),
        "first_bar": float(beat_t[r]) if len(beat_t) > r else 0.0,
        "downbeat_margin": round(margin, 3),
        "env": env,
        "S": S,
        "chroma": chroma,
    }


# ---------------------------------------------------------------- tonalidad

def detect_key(y, sr):
    """Krumhansl-Schmuckler sobre cromagrama con corrección de afinación."""
    try:
        tuning = float(librosa.estimate_tuning(y=y, sr=sr))
    except Exception:
        tuning = 0.0
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, tuning=tuning)
    prof = chroma.mean(axis=1)
    cands = []
    for root in range(12):
        for mode, ks in (("major", KS_MAJ), ("minor", KS_MIN)):
            r = np.corrcoef(prof, np.roll(ks, root))[0, 1]
            cands.append((float(r), root, mode))
    cands.sort(reverse=True)
    conf = float(np.clip((cands[0][0] - cands[1][0]) * 4 + 0.2, 0, 1))
    alts = [{**key_info(r, m), "score": round(s, 4)} for s, r, m in cands[:4]]
    best = alts[0]
    return best, round(conf, 3), alts, round(tuning * 100, 1)


# ---------------------------------------------------------------- voz

def detect_vocal_onset(vocals, sr):
    """Primer instante con voz sostenida (segundos)."""
    hop = int(0.05 * sr)
    vocals = np.ascontiguousarray(vocals.mean(axis=1) if vocals.ndim == 2 else vocals)
    rms = librosa.feature.rms(y=vocals, frame_length=hop * 2, hop_length=hop)[0]
    db = 20 * np.log10(rms + 1e-6)
    ref = np.percentile(db, 95)
    on = db > ref - 24
    need = 8  # 0,4 s seguidos
    for i in range(len(on) - need):
        if on[i: i + need].all():
            return float(i * 0.05)
    return 0.0


def vocal_entry_bar(onset, downbeats, spbar):
    """Compás en el que 'entra' la voz; los anacrusis se asignan al compás siguiente."""
    if not len(downbeats):
        return 0
    pos = (onset - downbeats[0]) / spbar
    k = math.floor(pos)
    if pos - k > 0.7:
        k += 1
    return int(max(0, min(k, len(downbeats) - 1)))


# ---------------------------------------------------------------- estructura

def segment(S, chroma, sr, downbeats, spbar, duration, vocal_onset):
    if len(downbeats) < 12:
        return []
    fps = sr / HOP
    frames = np.clip(np.round(downbeats * fps).astype(int), 0, chroma.shape[1] - 1)
    ch = librosa.util.sync(chroma, frames, aggregate=np.mean)
    mf = librosa.feature.mfcc(S=librosa.power_to_db(librosa.feature.melspectrogram(S=S ** 2, sr=sr)), n_mfcc=13)
    mf = librosa.util.sync(mf, frames, aggregate=np.mean)
    rms = librosa.util.sync(librosa.feature.rms(S=S), frames, aggregate=np.mean)
    # la columna 0 es el trozo anterior al primer compás; la j+1 empieza en el compás j
    ch, mf, rms = ch[:, 1:], mf[:, 1:], rms[:, 1:]
    n = min(ch.shape[1], mf.shape[1], rms.shape[1], len(downbeats))
    feat = np.vstack([ch[:, :n] / (np.linalg.norm(ch[:, :n], axis=0) + 1e-9) * 2, mf[1:, :n] / 40.0])
    feat = librosa.util.normalize(feat, axis=1)
    k = int(np.clip(round(duration / 22), 4, 10))
    try:
        b = librosa.segment.agglomerative(feat, min(k, n - 1))
    except Exception:
        return []
    bounds = sorted(set([0, *[int(x) for x in b], n]))
    bounds = [x for i, x in enumerate(bounds) if i == 0 or x - bounds[i - 1] >= 2] or [0, n]
    if bounds[-1] != n:
        bounds.append(n)
    segs = []
    for a, bnd in zip(bounds[:-1], bounds[1:]):
        v = feat[:, a:bnd].mean(axis=1)
        segs.append({"a": a, "b": bnd, "v": v / (np.linalg.norm(v) + 1e-9), "e": float(rms[:, a:bnd].mean())})
    groups = []
    for s in segs:
        for gi, g in enumerate(groups):
            if float(np.dot(g["v"], s["v"])) > 0.94:
                s["g"] = gi
                g["n"] += 1
                break
        else:
            s["g"] = len(groups)
            groups.append({"v": s["v"], "n": 1})
    ge = {}
    for s in segs:
        ge.setdefault(s["g"], []).append(s["e"])
    rep = [g for g in ge if groups[g]["n"] >= 2] or list(ge)
    chorus_g = max(rep, key=lambda g: np.mean(ge[g]))
    out = []
    seen_first_vocal = False
    for s in segs:
        t0 = float(downbeats[s["a"]])
        t1 = float(downbeats[s["b"]]) if s["b"] < len(downbeats) else duration
        if s["g"] == chorus_g:
            label = "chorus"
        elif t1 <= vocal_onset + 1e-3 and not seen_first_vocal:
            label = "intro"
        else:
            label = "verse" if groups[s["g"]]["n"] >= 2 or t0 > vocal_onset else "section"
        if t1 > vocal_onset:
            seen_first_vocal = True
        out.append({
            "start": round(t0, 4), "end": round(t1, 4), "label": label,
            "bar": int(s["a"]), "end_bar": int(s["b"]),
            "confidence": round(float(np.clip(0.55 + 0.1 * groups[s["g"]]["n"], 0, 0.97)), 3),
        })
    return out


# ---------------------------------------------------------------- todo junto

def analyze(mix, inst, vocals, sr, progress=lambda p, s: None):
    """mix/inst/vocals: arrays (n, 2) float32 a `sr`."""
    duration = len(mix) / sr
    y = to_mono(mix, sr)
    progress(0.1, "Buscando el tempo y la rejilla")
    g = detect_grid(y, ANALYSIS_SR)
    bpm, first_bar = g["bpm"], g["first_bar"]
    beats, downs, spb, spbar = make_grid(bpm, first_bar, 4, duration)

    progress(0.45, "Detectando la tonalidad")
    key_src = to_mono(inst if inst is not None else mix, sr)
    key, kconf, alts, tuning = detect_key(key_src, ANALYSIS_SR)

    progress(0.6, "Buscando la entrada de la voz")
    onset = detect_vocal_onset(vocals, sr) if vocals is not None else 0.0
    vbar = vocal_entry_bar(onset, downs, spbar)

    progress(0.75, "Estructura de la canción")
    segs = segment(g["S"], g["chroma"], ANALYSIS_SR, downs, spbar, duration, onset)

    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=max(1, len(y) // 400))[0][:400]
    energy = (rms / (rms.max() + 1e-9)).round(4).tolist()

    doubts = []
    if g["downbeat_margin"] < 0.15:
        doubts.append("uno")
    if g["bpm_confidence"] < 0.35:
        doubts.append("bpm")
    if kconf < 0.45:
        doubts.append("tono")

    return {
        "duration": round(duration, 3),
        "sample_rate": sr,
        "bpm": bpm,
        "bpm_confidence": g["bpm_confidence"],
        "beats_per_bar": 4,
        "time_signature": "4/4",
        "first_bar": round(float(downs[0]), 4),
        "beat_times": [round(float(t), 4) for t in beats],
        "downbeat_times": [round(float(t), 4) for t in downs],
        "seconds_per_beat": round(spb, 6),
        "seconds_per_bar": round(spbar, 6),
        **{k: key[k] for k in ("key", "camelot")},
        "key_root": key["root"],
        "key_mode": key["mode"],
        "key_confidence": kconf,
        "key_alternatives": alts,
        "tuning_offset_cents": tuning,
        "vocal_onset": round(onset, 3),
        "vocal_entry_bar": vbar,
        "vocal_entry": round(float(downs[vbar]), 4) if len(downs) else 0.0,
        "segments": segs,
        "energy_curve": energy,
        "doubts": doubts,
    }


def regrid(a, bpm=None, first_bar=None, beats_per_bar=None, key_root=None, key_mode=None):
    """Aplica correcciones manuales y rehace la rejilla."""
    bpm = float(bpm if bpm is not None else a["bpm"])
    bpb = int(beats_per_bar if beats_per_bar is not None else a["beats_per_bar"])
    fb = float(first_bar if first_bar is not None else a["first_bar"])
    beats, downs, spb, spbar = make_grid(bpm, fb, bpb, a["duration"])
    a = dict(a)
    a.update(
        bpm=round(bpm, 2), beats_per_bar=bpb, time_signature=f"{bpb}/4",
        first_bar=round(float(downs[0]), 4),
        beat_times=[round(float(t), 4) for t in beats],
        downbeat_times=[round(float(t), 4) for t in downs],
        seconds_per_beat=round(spb, 6), seconds_per_bar=round(spbar, 6),
        bpm_confidence=1.0 if bpm != a["bpm"] else a["bpm_confidence"],
    )
    if key_root is not None or key_mode is not None:
        k = key_info(key_root if key_root is not None else a["key_root"], key_mode or a["key_mode"])
        a.update(key=k["key"], camelot=k["camelot"], key_root=k["root"], key_mode=k["mode"], key_confidence=1.0)
    a["vocal_entry_bar"] = vocal_entry_bar(a["vocal_onset"], downs, spbar)
    a["vocal_entry"] = round(float(downs[a["vocal_entry_bar"]]), 4)
    segs = []
    for s in a["segments"]:
        s = dict(s)
        s["bar"] = int(round((s["start"] - downs[0]) / spbar))
        s["end_bar"] = int(round((s["end"] - downs[0]) / spbar))
        segs.append(s)
    a["segments"] = segs
    a["doubts"] = [d for d in a.get("doubts", []) if d == "tono"]
    return a
