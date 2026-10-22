"""Prueba de extremo a extremo contra el servidor local (python tests/e2e.py)."""
import json, subprocess, sys, time, urllib.request, urllib.parse
B = "http://127.0.0.1:8765/api"
def call(path, data=None, method=None):
    req = urllib.request.Request(B + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(req))
def wait(jid):
    while True:
        j = call(f"/jobs/{jid}")
        if j["status"] in ("done", "failed"): return j
        time.sleep(0.5)
out = subprocess.run(["curl", "-s", "-F", "vocals=@tests/t_voc.wav", "-F", "instrumental=@tests/t_inst.wav", B + "/projects?title=Test%20Song"],
                     capture_output=True, text=True).stdout
r = json.loads(out); pid = r["project"]["id"]
j = wait(r["job"]["id"]); print("process:", j["status"], j["error"])
a = call(f"/projects/{pid}")["analysis"]
print({k: a[k] for k in ("bpm", "bpm_confidence", "first_bar", "key", "camelot", "vocal_onset", "vocal_entry_bar", "vocal_entry", "doubts")})
print("compases", len(a["downbeat_times"]), "segmentos", [(s["label"], s["bar"], s["end_bar"]) for s in a["segments"]])
for opts in ({"version": "livemashup", "ending": "acapella"}, {"version": "extended", "ending": "outro", "drum_genre": "dembow"}):
    j = wait(call(f"/projects/{pid}/exports", {"target": "hybrid", **opts}, "POST")["id"])
    print(opts, j["status"], j["error"], j["result"] and (j["result"]["filename"], j["result"]["info"], j["result"]["duration"]))
for t in ("acapella", "instrumental"):
    j = wait(call(f"/projects/{pid}/exports", {"target": t}, "POST")["id"]); print(t, j["status"], j["error"])
p = call(f"/projects/{pid}/analysis", {"bpm": a["bpm"] * 2}, "PATCH"); print("x2 ->", p["analysis"]["bpm"], len(p["analysis"]["downbeat_times"]))
print("PID", pid)
