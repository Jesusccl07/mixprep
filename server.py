"""MixPrep: servidor local. Sube una canción y obtén LiveMashup, Extended, acapella e instrumental."""
import json
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import analysis as an
import render as rd

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "projects"
DATA.mkdir(parents=True, exist_ok=True)
SR = rd.SR
KINDS = ("mix", "vocals", "instrumental")

app = FastAPI(title="MixPrep")
pool = ThreadPoolExecutor(max_workers=1)  # una tarea pesada a la vez
jobs: dict[str, dict] = {}
lock = threading.Lock()


# ---------------------------------------------------------------- almacén

def pdir(pid):
    p = DATA / pid
    if not p.is_dir() or ".." in pid:
        raise HTTPException(404, "Proyecto no encontrado")
    return p


def load(pid):
    return json.loads((pdir(pid) / "project.json").read_text("utf-8"))


def save(p):
    with lock:
        (DATA / p["id"] / "project.json").write_text(json.dumps(p, ensure_ascii=False), "utf-8")


def new_job(kind):
    jid = uuid.uuid4().hex[:12]
    jobs[jid] = {"id": jid, "kind": kind, "status": "queued", "progress": 0.0, "stage": "En cola", "error": None, "result": None}
    return jobs[jid]


def prog(job):
    def f(p, stage):
        job.update(status="running", progress=round(float(p), 3), stage=stage)
    return f


# ---------------------------------------------------------------- audio

def decode(src, dst):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(dst)],
                   check=True, capture_output=True)


def probe_tags(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
                             capture_output=True, text=True).stdout
        t = {k.lower(): v for k, v in (json.loads(out).get("format", {}).get("tags") or {}).items()}
        return t.get("artist"), t.get("title")
    except Exception:
        return None, None


def read(path):
    x, sr = sf.read(path, dtype="float32", always_2d=True)
    assert sr == SR
    return x


def separate_ai(mix, progress):
    """Demucs (htdemucs) en memoria, sin pasar por torchaudio. Devuelve (voz, instrumental) o None."""
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model
    except Exception:
        return None
    progress(0.12, "Cargando el modelo de separación")
    model = get_model("htdemucs")
    model.eval()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    x = torch.from_numpy(mix.T.copy()).float()
    ref = x.mean(0)
    x = (x - ref.mean()) / (ref.std() + 1e-8)
    progress(0.2, f"Separando voz e instrumental con IA ({dev}); puede tardar unos minutos")
    with torch.no_grad():
        src = apply_model(model, x[None], device=dev, split=True, overlap=0.25, shifts=0, progress=False)[0]
    src = src * (ref.std() + 1e-8) + ref.mean()
    vi = model.sources.index("vocals")
    voc = src[vi].cpu().numpy().T
    ins = (src.sum(0) - src[vi]).cpu().numpy().T
    return voc.astype(np.float32), ins.astype(np.float32)


def separate_dsp(mix):
    """Aproximación sin IA: cancelación del canal central. Calidad limitada."""
    import librosa
    L, R = mix[:, 0], mix[:, 1]
    mid = (L + R) / 2
    side = (L - R) / 2
    n_fft = 4096
    M = librosa.stft(mid, n_fft=n_fft)
    S_ = librosa.stft(side, n_fft=n_fft)
    mask = np.clip(np.abs(M) / (np.abs(M) + np.abs(S_) + 1e-9) - 0.5, 0, None) * 2
    freqs = librosa.fft_frequencies(sr=SR, n_fft=n_fft)
    mask *= ((freqs > 150) & (freqs < 8000))[:, None]
    voc_m = librosa.istft(M * mask, length=len(mid))
    voc = np.stack([voc_m, voc_m], 1).astype(np.float32)
    return voc, (mix - voc).astype(np.float32)


# ---------------------------------------------------------------- procesado

def process(pid, job, uploaded_stems):
    d = DATA / pid
    p = load(pid)
    progress = prog(job)
    try:
        progress(0.02, "Decodificando el audio")
        if uploaded_stems:
            voc, ins = read(d / "vocals.wav"), read(d / "instrumental.wav")
            n = min(len(voc), len(ins))
            voc, ins = voc[:n], ins[:n]
            mix = np.clip(voc + ins, -1, 1)
            sf.write(d / "mix.wav", mix, SR, subtype="PCM_16")
            backend = "uploaded"
        else:
            mix = read(d / "mix.wav")
            res = separate_ai(mix, progress)
            backend = "ai"
            if res is None:
                progress(0.2, "Separando con el método sin IA (instala demucs para más calidad)")
                res = separate_dsp(mix)
                backend = "dsp"
            voc, ins = res
            sf.write(d / "vocals.wav", voc, SR, subtype="PCM_16")
            sf.write(d / "instrumental.wav", ins, SR, subtype="PCM_16")
        progress(0.45, "Analizando BPM, rejilla y tonalidad")
        a = an.analyze(mix, ins, voc, SR, lambda f, s: progress(0.45 + f * 0.5, s))
        p.update(status="ready", analysis=a, duration=a["duration"], error=None,
                 separation={"backend": backend}, assets={k: f"{k}.wav" for k in KINDS})
        save(p)
        job.update(status="done", progress=1.0, stage="Listo", result={"project_id": pid})
    except Exception as e:
        traceback.print_exc()
        p.update(status="failed", error=str(e))
        save(p)
        job.update(status="failed", error=str(e), stage="Error")


@app.post("/api/projects")
async def upload(file: UploadFile | None = File(None), vocals: UploadFile | None = File(None),
                 instrumental: UploadFile | None = File(None), title: str = ""):
    stems = vocals is not None and instrumental is not None
    if not stems and file is None:
        raise HTTPException(400, "Sube una canción o la voz y el instrumental")
    pid = uuid.uuid4().hex[:16]
    d = DATA / pid
    d.mkdir(parents=True)
    raw = d / "original"
    first = vocals if stems else file
    name = first.filename or "cancion"
    try:
        if stems:
            for up, nm in ((vocals, "vocals"), (instrumental, "instrumental")):
                tmp = d / f"{nm}.upload"
                with open(tmp, "wb") as f:
                    shutil.copyfileobj(up.file, f)
                decode(tmp, d / f"{nm}.wav")
                tmp.unlink()
            tags = (None, None)
            stem_name = Path(name).stem
        else:
            with open(raw, "wb") as f:
                shutil.copyfileobj(file.file, f)
            decode(raw, d / "mix.wav")
            tags = probe_tags(raw)
            stem_name = Path(name).stem
    except subprocess.CalledProcessError:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "No se ha podido leer ese archivo de audio")
    artist, ttl = tags
    if not (artist and ttl) and " - " in stem_name:
        artist, ttl = (s.strip() for s in stem_name.split(" - ", 1))
    p = {
        "id": pid, "title": title or stem_name, "filename": name, "status": "processing", "error": None,
        "artist": artist or "", "track": ttl or title or stem_name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "exports": [], "analysis": None,
    }
    save(p)
    job = new_job("process")
    pool.submit(process, pid, job, stems)
    return {"project": p, "job": job}


@app.get("/api/projects")
def list_projects():
    out = []
    for d in sorted(DATA.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        f = d / "project.json"
        if f.exists():
            p = json.loads(f.read_text("utf-8"))
            a = p.get("analysis") or {}
            out.append({k: p.get(k) for k in ("id", "title", "artist", "track", "status", "created_at", "duration")}
                       | {"bpm": a.get("bpm"), "key": a.get("key"), "camelot": a.get("camelot")})
    return out


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return load(pid)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    shutil.rmtree(pdir(pid))
    return {"ok": True}


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    if jid not in jobs:
        raise HTTPException(404, "Trabajo no encontrado")
    return jobs[jid]


class Override(BaseModel):
    bpm: float | None = None
    first_bar: float | None = None
    beats_per_bar: int | None = None
    key_root: int | None = None
    key_mode: str | None = None


@app.patch("/api/projects/{pid}/analysis")
def override(pid: str, o: Override):
    p = load(pid)
    if not p.get("analysis"):
        raise HTTPException(409, "El proyecto aún no está analizado")
    if o.bpm is not None and not 40 <= o.bpm <= 250:
        raise HTTPException(400, "BPM fuera de rango (40-250)")
    p["analysis"] = an.regrid(p["analysis"], **o.model_dump())
    save(p)
    return p


@app.get("/api/projects/{pid}/audio/{kind}")
def audio(pid: str, kind: str):
    if kind not in KINDS:
        raise HTTPException(404)
    f = pdir(pid) / f"{kind}.wav"
    if not f.exists():
        raise HTTPException(404, "Audio no disponible")
    return FileResponse(f, media_type="audio/wav")


# ---------------------------------------------------------------- exportar

class ExportReq(BaseModel):
    target: str = "hybrid"  # hybrid | acapella | instrumental
    version: str = "livemashup"  # livemashup | extended
    ending: str = "acapella"  # acapella | outro | original
    intro_bars: int = 8
    vocal_entry_bar: int = -1
    intro_from_bar: int = -1
    chorus_bar: int = -1
    drum_genre: str = "house"
    fx: bool = True
    fx_beats: int = 4
    fx_highpass: float = 700
    fx_reverb: bool = True
    fx_noise: bool = True
    semitones: int = 0
    tempo_ratio: float = 1.0
    normalize: bool = True
    name_bpm: bool = True
    name_key: bool = False


VERSION_LABEL = {"livemashup": "LiveMashup", "extended": "Extended", "acapella": "Acapella", "instrumental": "Instrumental"}


def do_export(pid, req: ExportReq, job):
    progress = prog(job)
    try:
        p = load(pid)
        a = p["analysis"]
        d = pdir(pid)
        progress(0.05, "Cargando las pistas")
        stems = {k: read(d / f"{k}.wav") for k in KINDS}
        n = min(len(v) for v in stems.values())
        stems = {k: v[:n] for k, v in stems.items()}
        if req.target in ("acapella", "instrumental"):
            audio_, info = rd.render_simple(stems, req.target), {}
            label = VERSION_LABEL[req.target]
        else:
            if req.intro_bars not in (4, 8, 16, 32):
                raise ValueError("Compases de intro no válidos")
            progress(0.2, "Montando la intro, la transición y el final")
            audio_, info = rd.build(stems, a, req.model_dump())
            label = VERSION_LABEL[req.version]
        bpm = a["bpm"] * req.tempo_ratio
        key = an.key_info((a["key_root"] + req.semitones) % 12, a["key_mode"])
        fn = rd.filename(p["artist"], p["track"], label, bpm, key["key"], key["camelot"], req.name_bpm, req.name_key)
        eid = uuid.uuid4().hex[:10]
        out_dir = d / "exports"
        out_dir.mkdir(exist_ok=True)
        progress(0.6, "Codificando el MP3 a 320 kbps")
        rd.encode_mp3(
            audio_, out_dir / f"{eid}.mp3",
            {"artist": p["artist"], "title": f"{p['track']} ({label})", "TBPM": round(bpm), "TKEY": key["camelot"],
             "comment": f"{round(bpm, 2)} BPM {key['key']} {key['camelot']} · MixPrep"},
            tempo_ratio=req.tempo_ratio, semitones=req.semitones, normalize_db=-1.0 if req.normalize else None,
        )
        rec = {"id": eid, "filename": fn, "label": label, "bpm": round(bpm, 2), "camelot": key["camelot"], "key": key["key"],
               "options": req.model_dump(), "info": info,
               "duration": round(len(audio_) / SR / (req.tempo_ratio or 1), 2), "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        p = load(pid)
        p["exports"].insert(0, rec)
        save(p)
        job.update(status="done", progress=1.0, stage="Listo", result=rec)
    except Exception as e:
        traceback.print_exc()
        job.update(status="failed", error=str(e), stage="Error")


@app.post("/api/projects/{pid}/exports")
def create_export(pid: str, req: ExportReq):
    p = load(pid)
    if p["status"] != "ready":
        raise HTTPException(409, "El proyecto aún no está listo")
    job = new_job("export")
    pool.submit(do_export, pid, req, job)
    return job


@app.get("/api/projects/{pid}/exports/{eid}/file")
def export_file(pid: str, eid: str, download: bool = False):
    p = load(pid)
    rec = next((e for e in p["exports"] if e["id"] == eid), None)
    f = pdir(pid) / "exports" / f"{eid}.mp3"
    if not rec or not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/mpeg", filename=rec["filename"] if download else None,
                        content_disposition_type="attachment" if download else "inline")


@app.delete("/api/projects/{pid}/exports/{eid}")
def delete_export(pid: str, eid: str):
    p = load(pid)
    p["exports"] = [e for e in p["exports"] if e["id"] != eid]
    save(p)
    (pdir(pid) / "exports" / f"{eid}.mp3").unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/capabilities")
def capabilities():
    try:
        import torch
        import demucs  # noqa: F401
        sep = "ai"
        gpu = bool(torch.cuda.is_available())
    except Exception:
        sep, gpu = "dsp", False
    return {"separation": sep, "gpu": gpu, "formats": ["mp3", "wav", "flac", "m4a", "ogg", "aiff"],
            "genres": list(rd.PATTERNS), "version": 1}


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
