"""Genera una canción sintética (118 BPM, 4/4, Am) con stems separados para probar MixPrep."""
import sys
import numpy as np, soundfile as sf
sr = 44100; bpm = 118.0; spb = 60 / bpm; bars = 48; off = 0.23
n = int((bars * 4 * spb + off + 1) * sr)
rng = np.random.default_rng(1)
inst = np.zeros(n, np.float32); voc = np.zeros(n, np.float32)
def add(buf, x, t):
    i = int(t * sr); buf[i:i + len(x)] += x[: len(buf) - i]
t = np.arange(int(.35 * sr)) / sr
kick = np.sin(2*np.pi*np.cumsum(45+110*np.exp(-t*28))/sr) * np.exp(-t*9)
t2 = np.arange(int(.05*sr))/sr
hat = rng.standard_normal(len(t2)) * np.exp(-t2*90) * .15
chords = [(57,60,64),(53,57,60),(48,52,55),(55,59,62)]
for bar in range(bars):
    b0 = off + bar * 4 * spb
    for k in range(4):
        if bar >= 1: add(inst, kick * .8, b0 + k * spb)
        if bar >= 2: add(inst, hat, b0 + k * spb + spb / 2)
    ch = chords[bar % 4]
    tt = np.arange(int(4 * spb * sr)) / sr
    pad = sum(np.sin(2*np.pi*440*2**((m-69)/12)*tt) for m in ch) * .07 * (1 - np.exp(-tt*8))
    add(inst, pad.astype(np.float32), b0)
    bass = np.sin(2*np.pi*440*2**((ch[0]-33)/12)*tt) * .18 * np.exp(-((tt % spb))*2)
    add(inst, bass.astype(np.float32), b0)
    if bar >= 8 and bar % 8 < 6 or bar >= 40:
        tv = np.arange(int(1.6*spb*sr)) / sr
        f = 330 * 2**((ch[1]-60)/12) * (1 + .01*np.sin(2*np.pi*5.5*tv))
        v = np.sin(np.cumsum(2*np.pi*f/sr)) + .4*np.sin(np.cumsum(4*np.pi*f/sr)); v *= .22*np.exp(-tv*1.3)*(1-np.exp(-tv*40))
        for k in (0, 2): add(voc, v.astype(np.float32), b0 + k * 2 * spb)
st = lambda x: np.stack([x, x], 1)
sf.write("tests/t_inst.wav", st(inst), sr); sf.write("tests/t_voc.wav", st(voc), sr); sf.write("tests/t_mix.wav", st(inst + voc), sr)
print("ok", n / sr, "s; downbeat0 =", off, "; voz entra en compás 9 =", off + 8 * 4 * spb)
