#!/usr/bin/env python3
"""Prove the Studio works on this machine. Standard library only; touches nothing but a temp folder.

    python tool/selftest.py

It builds a throwaway studio, files a batch of each file kind, lets the checks refuse a bad
one, judges over HTTP as the page does, then imports and closes as Claude Code does.
Exit code 0 means every step held.
"""
from __future__ import annotations

import json
import math
import shutil
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import wave
import zlib
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from studiolib import bake, board, server, setup  # noqa: E402
from studiolib.store import Studio, StudioError  # noqa: E402

FAILED = []


def check(ok: bool, what: str) -> None:
    print(("  PASS  " if ok else "  FAIL  ") + what)
    if not ok:
        FAILED.append(what)


def make_wav(path: Path, peak_dbfs: float, seconds: float) -> None:
    rate, amp = 22050, 10 ** (peak_dbfs / 20) * 32767
    frames = b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * 220 * i / rate))) for i in range(int(rate * seconds)))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate); out.writeframes(frames)


def make_png(path: Path, size: int, shade: int) -> None:
    row = b"\x00" + bytes([shade, shade, min(255, shade + 30)]) * size
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b""))


def make_glb(path: Path, height: float) -> None:
    pos = struct.pack("<9f", -0.3, 0, 0, 0.3, 0, 0, 0, height, 0)
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
                           "min": [-0.3, 0, 0], "max": [0.3, height, 0]}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos)}], "buffers": [{"byteLength": len(pos)}]}
    text = json.dumps(gltf).encode()
    text += b" " * (-len(text) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(text) + len(pos)) + struct.pack("<II", len(text), 0x4E4F534A)
                     + text + struct.pack("<II", len(pos), 0x004E4942) + pos)


def make_skinned_glb(path: Path) -> None:
    """Two joints, the second one metre above the first, and a triangle on the second."""
    ident = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    down = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -1, 0, 1)  # column by column: the inverse of "one metre up"
    parts = [struct.pack("<9f", -0.2, 1, 0, 0.2, 1, 0, 0, 1.5, 0), struct.pack("<12H", *([1, 0, 0, 0] * 3)),
             struct.pack("<12f", *([1, 0, 0, 0] * 3)), struct.pack("<32f", *(ident + down))]
    views, offset = [], 0
    for part in parts:
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(part)})
        offset += len(part)
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [2]}],
            "nodes": [{"name": "low", "children": [1]}, {"name": "high", "translation": [0, 1, 0]},
                      {"name": "rig", "children": [0, 3]}, {"name": "body", "mesh": 0, "skin": 0}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "JOINTS_0": 1, "WEIGHTS_0": 2}}]}],
            "skins": [{"joints": [0, 1], "inverseBindMatrices": 3}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [-0.2, 1, 0], "max": [0.2, 1.5, 0]},
                          {"bufferView": 1, "componentType": 5123, "count": 3, "type": "VEC4"},
                          {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC4"},
                          {"bufferView": 3, "componentType": 5126, "count": 2, "type": "MAT4"}],
            "bufferViews": views, "buffers": [{"byteLength": offset}]}
    text = json.dumps(gltf).encode()
    text += b" " * (-len(text) % 4)
    blob = b"".join(parts)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(text) + len(blob)) + struct.pack("<II", len(text), 0x4E4F534A)
                     + text + struct.pack("<II", len(blob), 0x004E4942) + blob)


def http(method: str, url: str, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=dict({"Content-Type": "application/json"} if data else {}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    print(f"Studio self-test, Python {sys.version.split()[0]}")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        os.environ["STUDIO_CLAUDE_SETTINGS"] = str(tmp / "claude" / "settings.json")  # never the user's own
        os.environ["STUDIO_CODEX_HOOKS"] = str(tmp / "codex" / "hooks.json")
        home, proj, src = tmp / "studio", tmp / "proj", tmp / "src"
        proj.mkdir(); src.mkdir()
        studio = Studio.init(home, "Self-test", str(proj))
        studio.set_slot("test.shot", title="Shot", kind="audio", group="Test", status="placeholder")
        check(studio.slot("test.shot")["status"] == "placeholder", "a slot is recorded")

        make_wav(src / "quiet_a.wav", -20.0, 0.4); make_wav(src / "quiet_b.wav", -26.0, 0.6)
        make_wav(src / "loud.wav", -6.0, 0.4); make_png(src / "tex.png", 64, 90); make_glb(src / "tall.glb", 2.28)
        make_glb(src / "right.glb", 1.8)

        batch = studio.new_batch("shot", title="Shot", kind="audio", slot="test.shot", ask="Which shot?",
                                 look_at=["Listen"], dest="content/audio/shot.wav")
        studio.add_candidate(batch["id"], [src / "quiet_a.wav"], title="A", made_with={"tool": "selftest"})
        studio.add_candidate(batch["id"], [src / "quiet_b.wav"], title="B", made_with={"tool": "selftest"})
        report = studio.publish(batch["id"])
        check(report["ready"] and not report["errors"], "a clean batch is filed")
        facts = studio.load_batch(batch["id"])["candidates"][0]["facts"]
        check(abs(facts["peak_dbfs"] + 20.0) < 0.2 and abs(facts["seconds"] - 0.4) < 0.01, "sound level and length are measured from the file")
        check(studio.slot("test.shot")["status"] == "in_review", "filing marks the slot in review")

        bad = studio.new_batch("loud", kind="audio", mode="rate", slot="test.shot", ask="Too loud?", look_at=["x"])
        studio.add_candidate(bad["id"], [src / "loud.wav"], made_with={"tool": "selftest"})
        report = studio.publish(bad["id"])
        check(not report["ready"] and any("dBFS" in e for e in report["errors"]), "a sound over the limit is refused")
        check(all(b["id"] != bad["id"] for b in studio.state()["batches"]) and studio.state()["held"][0]["id"] == bad["id"],
              "a refused batch is held back from the inbox")

        # a batch's own target: it can make a sound limit stricter than the project's, never looser, and one that is no number is not used
        from studiolib import checks as limits
        make_wav(src / "five.wav", -6.0, 5.0); make_wav(src / "two.wav", -24.0, 2.0)
        project = {"audio": {"max_peak_dbfs": -20.0, "max_seconds": 3.0}}
        faults = lambda name, targets, rules=project: sorted(c["id"] for c in limits.check_audio(src / name, rules, targets)[1])  # noqa: E731
        loose = [{"max_seconds": None, "max_peak_dbfs": None}, {"max_seconds": 0, "max_peak_dbfs": 0}, {"max_seconds": 90, "max_peak_dbfs": 6},
                 {"max_seconds": float("inf"), "max_peak_dbfs": float("nan")}, {"max_seconds": True, "max_peak_dbfs": False},
                 {"max_seconds": "90s", "max_peak_dbfs": "-6dB"}, {"max_seconds": "1:30"}, {"max_seconds": [1]}, {"max_seconds": -5}, {"max_seconds": 10 ** 400}]
        check(faults("five.wav", None) == ["audio.length", "audio.peak"] and all(faults("five.wav", t) == ["audio.length", "audio.peak"] for t in loose)
              and all(faults("two.wav", t) == [] for t in loose),
              "a target that is looser than the project's limit, nothing, 0, or not a number leaves the project's limit as it is, and breaks nothing")
        check(faults("two.wav", {"max_seconds": 1.5}) == ["audio.length"] and faults("two.wav", {"max_peak_dbfs": -30}) == ["audio.peak"]
              and faults("two.wav", {"max_seconds": 2, "max_peak_dbfs": -24}) == []
              and faults("five.wav", {"max_seconds": 4, "max_peak_dbfs": -10}, {"audio": {"max_seconds": 0}}) == ["audio.length", "audio.peak"]
              and faults("five.wav", {"max_seconds": "4"}, {"audio": {"max_seconds": 0}}) == [],
              "a stricter target is held to, for length and for level alike, and a project with no limit of its own takes the batch's")
        said = {c["id"]: c["msg"] for c in limits.check_audio(src / "five.wav", project, {"max_seconds": 90})[1]}
        check(said["audio.length"] == "5.00 s long; the limit is 3 s (the project's, in studio.toml: a batch's own target cannot raise it)"
              and said["audio.peak"] == "peaks at -6.0 dBFS; the limit is -20"
              and limits.check_audio(src / "two.wav", project, {"max_seconds": 1.5})[1][0]["msg"] == "2.00 s long; the limit is 1.5 s",
              "a sound over the limit in a batch that asked for a looser one is told the project's limit stands")
        said = {c["id"]: c["msg"] for c in limits.check_audio(src / "five.wav", project, {"max_seconds": "2s", "max_peak_dbfs": "-30dB"})[1]}
        check(said["audio.length"].endswith("the batch's target '2s' was not used, as it is not a length above 0 in seconds)")
              and said["audio.peak"].endswith("the batch's target '-30dB' was not used, as it is not a level in dBFS)"),
              "a target that is not a number is said to be not used, not to be looser")
        tool_cli = lambda *args: subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "studio.py"), "--home", str(home), *args],  # noqa: E731
                                                capture_output=True, text=True, encoding="utf-8")
        odd = tool_cli("new", "odd", "--kind", "audio", "--mode", "rate", "--ask", "Approve?", "--look", "x",
                       "--target", "max_seconds=90s", "--target", "max_peak_dbfs=null").stdout.strip()
        tool_cli("add", odd, str(src / "five.wav"), "--tool", "selftest")
        refused = tool_cli("file", odd)
        check(refused.returncode == 1 and "Traceback" not in refused.stderr and "5.00 s long; the limit is 3 s" in refused.stdout
              and "peaks at -6.0 dBFS; the limit is -20" in refused.stdout and "NOT filed" in refused.stdout,
              "filing a batch whose target is not a number ends in the checks' own words, not in a fault of the tool, and the sound is held back")
        shutil.rmtree(studio.batch_dir(odd))

        model = studio.new_batch("creature", kind="model", slot="test.model", ask="Which?", look_at=["Height"], targets={"height_m": 1.8})
        studio.add_candidate(model["id"], [src / "tall.glb"], made_with={"tool": "selftest"})
        studio.add_candidate(model["id"], [src / "right.glb"], made_with={"tool": "selftest"})
        report = studio.publish(model["id"])
        check(any("2.28 m tall" in e for e in report["errors"]) and len(report["errors"]) == 1, "a model at the wrong height is refused, the right one passes")

        tex = studio.new_batch("tex", kind="texture", mode="rate", ask="Approve?", look_at=["Tile it"])
        studio.add_candidate(tex["id"], [src / "tex.png"], slot="test.tex", made_with={"tool": "selftest"})
        check(studio.publish(tex["id"])["ready"] and studio.load_batch(tex["id"])["candidates"][0]["facts"]["width"] == 64, "a texture is measured and filed")

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = httpd.server_address[1]
        httpd.RequestHandlerClass = server.make_handler(studio.home, {f"127.0.0.1:{port}", f"localhost:{port}"}, quiet=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        status, state = http("GET", base + "/api/state")
        check(status == 200 and len(state["batches"]) == 2, "the page's data loads over HTTP")
        with urllib.request.urlopen(base + "/") as res:
            page = res.read()
            check(b"app.js" in page and b'="/' not in page, "the page itself is served, with addresses that also work under a path")
        with urllib.request.urlopen(base + f"/files/{batch['id']}/files/a/quiet_a.wav") as res:
            check(res.headers["Content-Type"] == "audio/wav", "a candidate file is served")
        status, _ = http("GET", base + f"/files/{batch['id']}/..%2F..%2Fstudio.toml")
        check(status == 404, "a path outside the batch is refused")
        status, _ = http("POST", base + f"/api/batch/{batch['id']}/submit", {"action": "ship", "candidates": {}}, {"Origin": "http://elsewhere.example"})
        check(status == 403, "a request from another site is refused")
        status, _ = http("PUT", base + f"/api/batch/{batch['id']}/draft", {"candidates": {"a": {"score": 7}}})
        check(status == 200 and studio.load_batch(batch["id"])["status"] == "draft", "a half-made verdict is saved")
        status, body = http("POST", base + f"/api/batch/{batch['id']}/submit", {"action": "ship", "candidates": {}})
        check(status == 400 and "Nothing is marked" in body["error"], "a verdict that ships nothing is refused, with the reason")
        status, body = http("POST", base + f"/api/batch/{batch['id']}/submit",
                            {"action": "ship_and_iterate", "note": "closer, but drier", "candidates": {"a": {"call": "winner", "score": 8, "note": "this one"}, "b": {"call": "redo", "note": "too soft"}}})
        check(status == 200 and body["pending"] == 1, "the user's verdict is submitted")

        # marks: parts of a picture painted in colours, a note for each; Claude gets the picture and where each colour is
        marked = studio.new_batch("marked", kind="texture", mode="rate", ask="Approve?", look_at=["The rust"])
        studio.add_candidate(marked["id"], [src / "tex.png"], made_with={"tool": "selftest"})
        studio.publish(marked["id"])
        def put_pic(cid, data):
            req = urllib.request.Request(base + f"/api/batch/{marked['id']}/marks/{cid}", data=data, method="PUT", headers={"X-Studio-File": "1"})
            try:
                with urllib.request.urlopen(req, timeout=10) as res:
                    return res.status
            except urllib.error.HTTPError as err:
                return err.code
        png = (src / "tex.png").read_bytes()
        refused = [put_pic("a", b"not a picture"), put_pic("zz", png)]
        stored = put_pic("a", png)
        marks = {"kind": "image", "notes": {"red": "too shiny here", "blue": "", "pink": "dropped"},
                 "where": {"red": "x 2–30, y 4–20 px of the 64 × 64 picture (upper left)", "blue": "x 40–60, y 40–60 px"},
                 "strokes": [{"c": "red", "r": 3, "p": [[2, 4], [30, 20]]}, {"c": "blue", "r": 3, "p": [[40, 40]]}, {"c": "pink", "r": 3, "p": [[1, 1]]}], "size": [64, 64]}
        status, body = http("POST", base + f"/api/batch/{marked['id']}/submit", {"action": "another_round", "candidates": {"a": {"marks": marks}}})
        kept = studio.load_batch(marked["id"])["verdict"]["candidates"]["a"]["marks"]
        item = next(x for x in studio.todo() if x["batch"] == marked["id"])
        row = item["unmarked"][0]["marks"]
        brief = studio.brief(marked["id"])
        listed = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "studio.py"), "--home", str(home), "todo"],
                                capture_output=True, text=True, encoding="utf-8").stdout
        check(refused == [400, 400] and stored == 200 and status == 200
              and set(kept["notes"]) == {"red", "blue"} and [s["c"] for s in kept["strokes"]] == ["red", "blue"]
              and row["picture"] == str(studio.marks_picture(marked["id"], "a")) and Path(row["picture"]).read_bytes() == png
              and [c["colour"] for c in row["colours"]] == ["red", "blue"] and row["colours"][0]["note"] == "too shiny here"
              and any("marked parts of a" in s for s in item["steps"])
              and "**red** (x 2–30, y 4–20 px" in brief and "> too shiny here" in brief and f"batches/{marked['id']}/marks/a.png" in brief
              and "marked in colours; the picture of it: " + row["picture"] in listed and '"too shiny here"' in listed,
              "marks in colours reach Claude: the picture, each colour's note exactly, and where it is; a colour's note alone gives another round its direction")
        from studiolib.store import clean_marks
        moved = clean_marks({"kind": "model", "notes": {"red": "the elbow folds back"}, "where": {"red": 'in the motion "walk" at 0.42 s of 1.20 s; 6 faces on "arm_l"'},
                             "faces": {"3": {"red": [9, 4, 4, -1, "x"]}}, "meshes": {"3": "arm_l"},
                             "moments": {"red": {"clip": "walk", "t": 0.4204, "length": 1.2}, "blue": {"clip": "walk", "t": 0.1, "length": 1.2}, "green": {"t": 1}}})
        check(moved["faces"] == {"3": {"red": [4, 9]}} and moved["meshes"] == {"3": "arm_l"}
              and moved["moments"] == {"red": {"clip": "walk", "t": 0.42, "length": 1.2}, "blue": {"clip": "walk", "t": 0.1, "length": 1.2}},
              "marks on a moving model keep the faces, and for each colour the motion and the second it was painted at")
        # paint over a model: strokes of points in the mesh's own space, six numbers each, beside any marks made by faces
        from studiolib.store import MARK_LIMIT
        point = [0.12345678, 1.5, -0.25, 0.004, 0.999, 0]
        painted = clean_marks({"kind": "model", "notes": {"red": "the seam shows"}, "where": {"red": 'on "body"; high; centre at (0.12, 1.50, -0.25) m'},
                               "faces": {"0": {"red": [2]}}, "meshes": {"0": "body", "1": "head", "9": "gone"},
                               "strokes": [{"c": "red", "r": 0.0123456, "m": "1", "p": point + [0.13, 1.5, -0.25, 0, 1, 0, 7]},
                                           {"c": "erase", "r": 0.01, "m": "1", "j": 1, "p": [0.1, 1.5, -0.2, 0, 1, 0]},
                                           {"c": "pink", "r": 0.01, "m": "1", "p": point}, {"c": "blue", "r": -1, "m": "1", "p": point},
                                           {"c": "blue", "r": 0.01, "m": "1", "p": [0, 0, "x", 0, 1, 0]}, {"c": "blue", "r": 0.01, "p": point}]})
        check(painted["strokes"] == [{"c": "red", "r": 0.01235, "m": "1", "p": [0.1234568, 1.5, -0.25, 0, 1, 0, 0.13, 1.5, -0.25, 0, 1, 0]},
                                     {"c": "erase", "r": 0.01, "m": "1", "p": [0.1, 1.5, -0.2, 0, 1, 0], "j": 1}]
              and painted["faces"] == {"0": {"red": [2]}} and painted["meshes"] == {"0": "body", "1": "head"},
              "paint over a model is kept as strokes: each point in the mesh's own space with the way it faced, rounded, beside marks made by faces")
        long = clean_marks({"kind": "model", "notes": {"red": "all of it"}, "strokes": [{"c": "red", "r": 1, "m": "0", "p": [0, 0, 0, 0, 1, 0] * (MARK_LIMIT + 1)},
                                                                                      {"c": "red", "r": 1, "m": "0", "p": [0, 0, 0, 0, 1, 0]}]})
        check(len(long["strokes"]) == 1 and len(long["strokes"][0]["p"]) == 6 * MARK_LIMIT, "paint past the limit of points is cut off")
        status, _ = http("PUT", base + f"/api/batch/{marked['id']}/draft", {"candidates": {"a": {"score": 7, "marks": {"kind": "model", "notes": {}, "where": {"green": 'on "body"'},
                         "strokes": [{"c": "green", "r": 0.02, "m": "0", "p": [0, 1, 0, 0, 0, 1, 0.01, 1, 0, 0, 0, 1]}], "meshes": {"0": "body"}}}}})
        drafted = (json.loads((studio.batch_dir(marked["id"]) / "draft.json").read_text(encoding="utf-8"))["candidates"]["a"].get("marks") or {})
        check(status == 200 and drafted.get("strokes") == [{"c": "green", "r": 0.02, "m": "0", "p": [0, 1, 0, 0, 0, 1, 0.01, 1, 0, 0, 0, 1]}] and drafted.get("meshes") == {"0": "body"},
              "paint on a model is kept in the draft as the page sent it, so it is there when the closer look opens again")
        studio.reopen(marked["id"])
        check(put_pic("a", b"") == 200 and not studio.marks_picture(marked["id"], "a").exists(), "an empty picture takes the marks away")
        shutil.rmtree(studio.batch_dir(marked["id"]))

        # marks on a timeline: moments and stretches of a sound or a clip, each with its own note, colour and kind
        from studiolib.store import clean_tempo, clock, marks_say
        junk = {"kind": "sound", "file": "tune.wav", "length": 12.0, "fps": 30, "size": [640, 360], "notes": {"red": "not used here"}, "extra": 1,
                "tempo": {"bpm": 120, "beats": 4, "first": 0, "guess": True},
                "spans": [{"id": "m2", "c": "green", "tag": "keep", "t0": 5.0004, "t1": 3.2, "note": " the good part ", "where": "w" * 900,
                           "facts": {"peak": -3.14159, "clips": True, "bands": [1, 2, 3, 4, 90], "name": "dropped", "Bad Key": 1}, "strokes": [{"c": "red", "r": 4, "p": [[1, 1]]}]},
                          {"id": "m1", "c": "pink", "tag": "explode", "t0": 7.52, "note": "n" * 5000},
                          {"id": "m1", "c": "red", "tag": "cut", "t0": 1, "t1": 2}, {"id": "x9", "t0": 1}, {"id": "m4", "t0": "soon"}, "junk",
                          {"id": "m5", "c": "blue", "tag": "cut", "t0": -4, "t1": 99, "note": 7}]}
        kept = clean_marks(junk)
        check(set(kept) == {"kind", "file", "length", "tempo", "spans"} and kept["tempo"] == {"bpm": 120.0, "beats": 4, "first": 0.0}
              and [s["id"] for s in kept["spans"]] == ["m5", "m2", "m1"]
              and kept["spans"][0] == {"id": "m5", "c": "blue", "tag": "cut", "t0": 0.0, "t1": 12.0, "note": "", "where": ""}
              and (kept["spans"][1]["t0"], kept["spans"][1]["t1"], kept["spans"][1]["note"], len(kept["spans"][1]["where"])) == (3.2, 5.0, "the good part", 800)
              and kept["spans"][1]["facts"] == {"peak": -3.142, "clips": True, "bands": [1.0, 2.0, 3.0, 4.0, 90.0]} and "strokes" not in kept["spans"][1]
              and kept["spans"][2] == {"id": "m1", "c": "red", "tag": "change", "t0": 7.52, "t1": 7.52, "note": "n" * 4000, "where": ""},
              "marks on a sound keep each mark's times, note, colour and kind, in time order; a moment is a mark that ends where it starts; the rest is dropped")
        many = clean_marks({"kind": "sound", "length": 60, "spans": [{"id": f"m{i}", "t0": i} for i in range(1, 60)]})
        clip = clean_marks({"kind": "video", "file": "cut.mp4", "length": 4, "fps": 29.97, "size": [640, 360], "tempo": {"bpm": 9000},
                            "spans": [{"id": "m1", "c": "red", "t0": 1.5, "facts": {"peak": -3},
                                       "strokes": [{"c": "red", "r": 12, "p": [[10, 20], [30.6, 40], ["x", 1]]}, {"c": "pink", "r": 3, "p": [[1, 1]]}]}]})
        check(len(many["spans"]) == 40 and clean_marks({"kind": "sound", "length": 3, "spans": []}) is None and clean_marks({"kind": "film", "spans": [{"id": "m1", "t0": 1}]}) is None
              and (clip["fps"], clip["size"]) == (29.97, [640, 360]) and "tempo" not in clip and "facts" not in clip["spans"][0]
              and clip["spans"][0]["strokes"] == [{"c": "red", "r": 12.0, "p": [[10, 20], [30, 40]]}],
              "one sound or clip takes 40 marks; none at all is no marks; a mark on a clip keeps the paint on its frame, and the clip its frames a second and size")
        check(clean_tempo({"bpm": 96, "beats": 3, "first": 0.5}) == {"bpm": 96.0, "beats": 3, "first": 0.5} and clean_tempo({"bpm": 5}) is None
              and clock(3.2) == "0:03.20" and clock(67.523) == "1:07.52" and clock(59.999) == "1:00.00"
              and marks_say({"spans": [{"tag": "keep", "note": ""}]}) and marks_say({"spans": [{"tag": "change", "note": "x"}]})
              and not marks_say({"spans": [{"tag": "change", "note": ""}]}) and not marks_say({"notes": {"red": "x"}}),
              "a tempo is kept only when it is one; a time reads 0:03.20; a mark says something when it has a note, or is a Cut or a Keep")
        tool_py = str(Path(__file__).resolve().parent / "studio.py")
        def cli(*args):
            return subprocess.run([sys.executable, tool_py, "--home", str(home), *args], capture_output=True, text=True, encoding="utf-8")
        tune = studio.new_batch("tune", kind="audio", mode="rate", ask="Approve the tune?", look_at=["The second bar"], targets={"max_seconds": 5})
        make_wav(src / "tune.wav", -22.0, 4.0)
        added = cli("add", tune["id"], str(src / "tune.wav"), "--title", "Tune", "--tool", "selftest", "--bpm", "96", "--beats", "3", "--first-beat", "0.5")
        lone, slow = cli("add", tune["id"], str(src / "tune.wav"), "--beats", "3"), cli("add", tune["id"], str(src / "tune.wav"), "--bpm", "4")
        held = studio.publish(tune["id"])
        studio.config["checks"]["audio"]["max_seconds"] = 5.0  # the user lets sounds run longer, as they would in studio.toml
        filed = studio.publish(tune["id"])
        studio.config["checks"]["audio"]["max_seconds"] = 3.0
        cand = studio.load_batch(tune["id"])["candidates"]
        check(added.returncode == 0 and len(cand) == 1 and cand[0]["tempo"] == {"bpm": 96.0, "beats": 3, "first": 0.5}
              and lone.returncode == 2 and "--bpm" in lone.stderr and slow.returncode == 2 and "20 to 400" in slow.stderr,
              "a sound is filed with its tempo by --bpm, --beats and --first-beat; beats without a tempo, or a tempo that is not one, is refused")
        check(not held["ready"] and any("4.00 s long; the limit is 3 s" in e for e in held["errors"]) and filed["ready"] and cand[0]["facts"]["seconds"] == 4.0,
              "a batch's own target does not let a sound run longer than the project's limit; it is filed once the user makes the limit longer")
        def put_mark(cid, span, data, batch_id=tune["id"]):
            req = urllib.request.Request(base + f"/api/batch/{batch_id}/marks/{cid}" + (f"/{span}" if span else ""), data=data, method="PUT", headers={"X-Studio-File": "1"})
            try:
                with urllib.request.urlopen(req, timeout=10) as res:
                    return res.status
            except urllib.error.HTTPError as err:
                return err.code
        spans = [{"id": "m1", "c": "red", "tag": "change", "t0": 0.4, "t1": 0.4, "note": "a click here", "where": "at 0:00.40; before bar 1"},
                 {"id": "m2", "c": "yellow", "tag": "keep", "t0": 1.2, "t1": 2.5, "note": "", "where": "0:01.20 to 0:02.50 (1.30 s); bar 1 beat 2 to bar 2 beat 1; peak -22.0 dBFS"},
                 {"id": "m3", "c": "green", "tag": "cut", "t0": 3.0, "t1": 3.5, "note": "drags\non", "where": "0:03.00 to 0:03.50 (0.50 s)"}]
        timed = {"kind": "sound", "file": "tune.wav", "length": 4.0, "tempo": cand[0]["tempo"], "spans": spans}
        status, _ = http("PUT", base + f"/api/batch/{tune['id']}/draft", {"candidates": {"a": {"marks": timed}}})
        sent = [put_mark("a", "", png), put_mark("a", "m1", png), put_mark("a", "m2", png), put_mark("a", "m3", png)]
        refused = [put_mark("a", "m1", b"not a picture"), put_mark("zz", "m1", png), put_mark("a", "sheet", png), put_mark("a", "..", png)]
        own = lambda span: studio.mark_picture(tune["id"], "a", span)  # noqa: E731
        check(status == 200 and sent == [200] * 4 and refused == [400] * 4 and own("m2").read_bytes() == png
              and own("m2") == studio.batch_dir(tune["id"]) / "marks" / "a" / "m2.png",
              "each mark can have its own picture beside the sheet, sent as the sheet is; anything but a PNG, an unknown candidate or a name that is no mark is refused")
        timed["spans"] = spans[:2]
        http("PUT", base + f"/api/batch/{tune['id']}/draft", {"candidates": {"a": {"marks": timed}}})
        check(own("m1").exists() and own("m2").exists() and not own("m3").exists() and studio.marks_picture(tune["id"], "a").exists()
              and put_mark("a", "m2", b"") == 200 and not own("m2").exists(),
              "saving a draft throws away the picture of a mark that is gone and keeps the rest; an empty picture takes one away")
        timed["spans"] = [dict(spans[0], note="")]
        status, body = http("POST", base + f"/api/batch/{tune['id']}/submit", {"action": "another_round", "candidates": {"a": {"marks": timed}}})
        check(status == 400 and "direction" in body["error"], "a mark with no note that is neither a Cut nor a Keep gives another round no direction")
        timed["spans"] = [dict(s, note="") if s["id"] == "m1" else s for s in spans]
        put_mark("a", "m3", png)
        status, body = http("POST", base + f"/api/batch/{tune['id']}/submit", {"action": "another_round", "candidates": {"a": {"marks": timed}}})
        item = next((x for x in studio.todo() if x["batch"] == tune["id"]), {"unmarked": [{}], "steps": []})
        row = item["unmarked"][0].get("marks") or {"spans": []}
        check(status == 200 and row.get("on") == "sound" and row["picture"] == str(studio.marks_picture(tune["id"], "a"))
              and (row["file"], row["length"], row["tempo"]["bpm"]) == ("tune.wav", 4.0, 96.0)
              and [(m["number"], m["id"], m["colour"], m["tag"], m["moment"]) for m in row["spans"]]
              == [(1, "m1", "red", "change", True), (2, "m2", "yellow", "keep", False), (3, "m3", "green", "cut", False)]
              and [bool(m["picture"]) for m in row["spans"]] == [True, False, True] and row["spans"][2]["picture"] == str(own("m3"))
              and row["spans"][2]["note"] == "drags\non" and row["spans"][1]["where"].startswith("0:01.20 to 0:02.50"),
              "a Keep with no note is direction enough; Claude gets the sheet, then each mark in time order: number, colour, kind, moment or stretch, note, where, its own picture")
        steps = " ".join(item["steps"])
        check("marks on the timeline of a" in steps and "KEEP is a fence" in steps and "CUT means that stretch goes" in steps
              and "open the pictures" in steps and "in colours" not in steps,
              "the steps say how to read marks on a timeline: the pictures first, a Keep is a fence, a Cut goes, a note is about its own part")
        listed = cli("todo").stdout
        check("marks on the timeline of the sound (tune.wav, 4.00 s, 96 beats a minute, 3 to the bar); the sheet: " + row["picture"] in listed
              and "1. change, at 0:00.40, red: (no note)" in listed and "2. KEEP, 0:01.20 to 0:02.50 (1.30 s), yellow: (no note)" in listed
              and '3. CUT, 0:03.00 to 0:03.50 (0.50 s), green: "drags\non"' in listed
              and "where: 0:01.20 to 0:02.50 (1.30 s); bar 1 beat 2 to bar 2 beat 1; peak -22.0 dBFS" in listed
              and "its own picture: " + str(own("m3")) in listed and "marked in colours" not in listed.split(tune["id"])[1].split("do:")[0],
              "todo prints them so: the sheet, then a line a mark with KEEP and CUT in capitals, its times, the note exactly, where, and its picture")
        brief = studio.brief(tune["id"])
        check("marks on the timeline of the sound `tune.wav` (4.00 s, 96 beats a minute, 3 to the bar)" in brief and f"`batches/{tune['id']}/marks/a.png`" in brief
              and "- **2. KEEP, 0:01.20 to 0:02.50 (1.30 s), yellow** (0:01.20 to 0:02.50 (1.30 s); bar 1 beat 2" in brief and "(no note for this mark)" in brief
              and "- **3. CUT, 0:03.00 to 0:03.50 (0.50 s), green**" in brief and "  > drags\n  > on" in brief
              and f"Its own picture: `batches/{tune['id']}/marks/a/m3.png`" in brief and "KEEP is a fence" in brief and "in colours" not in brief,
              "the brief for the next round says the same: every mark, the user's words quoted, the pictures by their paths")
        status, _ = http("PUT", base + f"/api/batch/{tune['id']}/draft", {"action": "another_round", "candidates": {"a": {"note": "typed in a tab that never saw the marks"}}})
        check(status == 200 and studio.load_batch(tune["id"])["status"] == "submitted" and own("m1").exists() and own("m3").exists()
              and "its own picture: " + str(own("m3")) in cli("todo").stdout,
              "a draft saved on a batch whose verdict was sent leaves the pictures of that verdict's marks where they are")
        (studio.batch_dir(tune["id"]) / "result.json").write_text('{"action": "another_round"}', encoding="utf-8")
        check(put_mark("a", "m1", png) == 400 and put_mark("a", "", png) == 400, "a closed batch takes no more pictures of marks")
        shutil.rmtree(studio.batch_dir(tune["id"]))
        schema = json.loads((Path(__file__).resolve().parent / "schemas" / "verdict.schema.json").read_text(encoding="utf-8"))
        in_schema = schema["properties"]["candidates"]["additionalProperties"]["properties"]["marks"]["properties"]
        of_span = in_schema["spans"]["items"]["properties"]
        check({"sound", "video"} <= set(in_schema["kind"]["enum"]) and set(kept) | set(clip) <= set(in_schema)
              and set().union(*(set(s) for s in kept["spans"] + clip["spans"])) <= set(of_span)
              and of_span["tag"]["enum"] == ["change", "cut", "keep"] and in_schema["spans"]["maxItems"] == 40,
              "the verdict's schema names every field kept for marks on a sound and a clip")
        from studiolib import checks as filechecks
        clips = Path(__file__).resolve().parent / "samples_src" / "video"
        (src / "odd.webm").write_bytes(b"\x1a\x45\xdf\xa3" + b"\0" * 64)
        (src / "cut_short.mp4").write_bytes((clips / "clip_bars.mp4").read_bytes()[:700])
        (src / "not_one.mp4").write_bytes(b"\0\0\0\x08moov" + b"junk" * 9)
        seen = {n: filechecks.check_video(clips / f"clip_{n}.mp4", {}) for n in ("bars", "zoom", "cells")}
        check(seen["bars"] == ({"seconds": 4.0, "fps": 30.0, "width": 640, "height": 360, "frames": 120}, []) and seen["zoom"] == seen["bars"]
              and seen["cells"] == ({"seconds": 4.0, "fps": 15.0, "width": 640, "height": 360, "frames": 60}, []),
              "a clip's length, frames a second, size and count of frames are read from the MP4 itself")
        check(all(filechecks.check_video(src / n, {}) == ({}, []) for n in ("odd.webm", "cut_short.mp4", "not_one.mp4", "tex.png")),
              "a WebM, or an MP4 that cannot be read, has no facts and is no fault")
        # marks on a clip: Claude is told the frames and where the paint is, and gets the picture of a mark's first frame
        cut = studio.new_batch("cut", kind="video", mode="rate", ask="Approve the cut?", look_at=["The wipe"])
        studio.add_candidate(cut["id"], [clips / "clip_bars.mp4"], title="Bars", made_with={"tool": "selftest"})
        studio.publish(cut["id"])
        painted = "at 1.52 s (frame 45 of 120, 30 fps); paint in the upper left (x 0 to 125, y 0 to 54 of 640 x 360), about 1% of the frame"
        on_clip = {"kind": "video", "file": "clip_bars.mp4", "length": 4.0, "fps": 30, "size": [640, 360], "spans": [
            {"id": "m2", "c": "yellow", "tag": "cut", "t0": 2.017, "t1": 2.683, "note": "this drags",
             "where": "from 2.02 s to 2.68 s (frames 60 to 80 of 120, 30 fps), 0.67 s long"},
            {"id": "m1", "c": "red", "tag": "change", "t0": 1.517, "t1": 1.517, "note": "", "where": painted,
             "strokes": [{"c": "red", "r": 10.3, "p": [[8, 44], [112, 44]]}, {"c": "erase", "r": 4, "p": [[60, 44]]}]}]}
        saved, _ = http("PUT", base + f"/api/batch/{cut['id']}/draft", {"candidates": {"a": {"marks": on_clip}}})
        sent = [put_mark("a", "", png, cut["id"]), put_mark("a", "m1", png, cut["id"])]
        status, _ = http("POST", base + f"/api/batch/{cut['id']}/submit", {"action": "another_round", "candidates": {"a": {"marks": on_clip}}})
        item = next((x for x in studio.todo() if x["batch"] == cut["id"]), {"unmarked": [{}], "steps": []})
        row = item["unmarked"][0].get("marks") or {"spans": [{}, {}]}
        own = studio.mark_picture(cut["id"], "a", "m1")
        kept_paint = studio.load_batch(cut["id"])["verdict"]["candidates"]["a"]["marks"]["spans"][0].get("strokes")
        check(saved == 200 and sent == [200, 200] and status == 200 and row.get("on") == "video" and (row["fps"], row["size"]) == (30.0, [640, 360])
              and [(m["number"], m["id"], m["tag"], m["moment"]) for m in row["spans"]] == [(1, "m1", "change", True), (2, "m2", "cut", False)]
              and row["spans"][0]["picture"] == str(own) and not row["spans"][1]["picture"] and row["spans"][0]["where"] == painted
              and kept_paint == [{"c": "red", "r": 10.3, "p": [[8, 44], [112, 44]]}, {"c": "erase", "r": 4.0, "p": [[60, 44]]}],
              "marks on a clip go through as on a sound: in time order, with the frames a second, the size, the paint and what was rubbed out, and a mark's own picture")
        check("On a clip the frames count from 0" in " ".join(item["steps"]) and "KEEP is a fence" in " ".join(item["steps"]),
              "the steps for a clip also say that frames count from 0 and that paint is on a mark's first frame")
        listed = cli("todo").stdout
        check("marks on the timeline of the clip (clip_bars.mp4, 4.00 s, 30 frames a second, 640 x 360); the sheet: " + row.get("picture", "?") in listed
              and "1. change, at 1.52 s, red: (no note)" in listed and '2. CUT, 2.02 s to 2.68 s (0.67 s), yellow: "this drags"' in listed
              and "where: " + painted in listed and "its own picture: " + str(own) in listed,
              "todo prints a clip's marks with its frames a second and size, times in seconds, where the paint is, and the picture")
        brief = studio.brief(cut["id"])
        check("marks on the timeline of the clip `clip_bars.mp4` (4.00 s, 30 frames a second counted from 0, 640 x 360)" in brief
              and "Paint is on a mark's first frame" in brief and f"- **1. change, at 1.52 s, red** ({painted}):" in brief
              and "- **2. CUT, 2.02 s to 2.68 s (0.67 s), yellow**" in brief and f"Its own picture: `batches/{cut['id']}/marks/a/m1.png`" in brief,
              "the brief for the next round says the same of a clip")
        shutil.rmtree(studio.batch_dir(cut["id"]))
        unboxed_steps = " ".join(item["steps"])
        # a box on a clip: a part of the picture, on screen for the whole of its mark; Claude gets its place, its times and its frames
        from studiolib.store import clean_box
        logo = {"left": 0.125, "top": 0.25, "width": 0.5, "height": 0.4}
        boxed = clean_marks({"kind": "video", "file": "clip_bars.mp4", "length": 4.0, "fps": 30, "size": [640, 360], "spans": [
            {"id": "m1", "c": "blue", "tag": "change", "t0": 1.0, "t1": 2.0, "note": "the logo", "box": dict(logo, extra=1)},
            {"id": "m2", "c": "red", "t0": 3.0, "box": {"left": -0.2, "top": 0.9, "width": 0.5, "height": 0.5}},
            {"id": "m3", "c": "green", "t0": 3.5, "box": {"left": 0.5, "top": 0.5, "width": 0, "height": 0.2}},
            {"id": "m4", "c": "yellow", "t0": 3.6, "box": [0.1, 0.1, 0.2, 0.2]}]})
        on_sound = clean_marks({"kind": "sound", "length": 4, "spans": [{"id": "m1", "t0": 1, "note": "x", "box": logo}]})
        check(boxed["spans"][0]["box"] == logo and boxed["spans"][1]["box"] == {"left": 0.0, "top": 0.9, "width": 0.3, "height": 0.1}
              and "box" not in boxed["spans"][2] and "box" not in boxed["spans"][3] and "box" not in on_sound["spans"][0]
              and clean_box(dict(logo, width=float("nan"))) is None and clean_box(dict(logo, left=True)) is None
              and clean_box({"left": 1.2, "top": 0.1, "width": 0.3, "height": 0.3}) is None,
              "a box on a clip is kept as sent, in shares of the frame; one that runs off the frame is cut to it; one with no size, "
              "one off the frame, one that is not a box and one on a sound are dropped")
        boxcut = studio.new_batch("boxcut", kind="video", mode="rate", ask="Approve the cut?", look_at=["The logo"])
        studio.add_candidate(boxcut["id"], [clips / "clip_bars.mp4"], title="Bars", made_with={"tool": "selftest"})
        studio.publish(boxcut["id"])
        in_box = {"kind": "video", "file": "clip_bars.mp4", "length": 4.0, "fps": 30, "size": [640, 360], "spans": [
            {"id": "m1", "c": "blue", "tag": "change", "t0": 1.017, "t1": 2.017, "note": "the logo jumps", "where": "from 1.02 s to 2.02 s", "box": logo},
            {"id": "m2", "c": "red", "tag": "keep", "t0": 3.017, "t1": 3.017, "note": "", "where": "at 3.02 s",
             "box": {"left": 0.5, "top": 0.5, "width": 0.25, "height": 0.25}}]}
        saved, _ = http("PUT", base + f"/api/batch/{boxcut['id']}/draft", {"candidates": {"a": {"marks": in_box}}})
        own = lambda span: studio.mark_picture(boxcut["id"], "a", span)  # noqa: E731
        sent = [put_mark("a", n, png, boxcut["id"]) for n in ("", "m1", "m1-middle", "m1-end", "m2")]
        refused = [put_mark("a", n, png, boxcut["id"]) for n in ("m1-start", "m1-middle-end", "-end")]
        check(saved == 200 and sent == [200] * 5 and refused == [400] * 3 and own("m1-end") == studio.batch_dir(boxcut["id"]) / "marks" / "a" / "m1-end.png"
              and own("m1-middle").read_bytes() == png,
              "a stretch with a box takes pictures of its middle and last frames beside its first; any other name is refused")
        http("PUT", base + f"/api/batch/{boxcut['id']}/draft", {"candidates": {"a": {"marks": dict(in_box, spans=[{k: v for k, v in in_box["spans"][0].items() if k != "box"}, in_box["spans"][1]])}}})
        check(own("m1").exists() and not own("m1-middle").exists() and not own("m1-end").exists() and own("m2").exists(),
              "taking a box away throws away the pictures of its middle and last frames, and keeps the mark's first")
        http("PUT", base + f"/api/batch/{boxcut['id']}/draft", {"candidates": {"a": {"marks": in_box}}})
        sent = [put_mark("a", n, png, boxcut["id"]) for n in ("m1-middle", "m1-end")]
        status, _ = http("POST", base + f"/api/batch/{boxcut['id']}/submit", {"action": "another_round", "candidates": {"a": {"marks": in_box}}})
        item = next((x for x in studio.todo() if x["batch"] == boxcut["id"]), {"unmarked": [{}], "steps": []})
        row = item["unmarked"][0].get("marks") or {"spans": [{}, {}]}
        check(status == 200 and sent == [200, 200] and row["spans"][0].get("box") == logo and row["spans"][0]["picture"] == str(own("m1"))
              and row["spans"][0].get("box_pictures") == [{"frame": "middle", "picture": str(own("m1-middle"))}, {"frame": "last", "picture": str(own("m1-end"))}]
              and row["spans"][1].get("box") == {"left": 0.5, "top": 0.5, "width": 0.25, "height": 0.25} and row["spans"][1].get("box_pictures") == [],
              "Claude gets each box as it was sent, with the pictures of its first, middle and last frames; a box on a moment has its one frame")
        steps = " ".join(item["steps"])
        check("A mark on a clip may carry a box" in steps and "shares of the frame" in steps and "carry a box" not in unboxed_steps,
              "the steps say what a box is when a mark has one, and say nothing of boxes when none has")
        listed = cli("todo").stdout
        check("box: left 0.125, top 0.250, width 0.500, height 0.400 of the frame (x 80 to 400, y 90 to 234 of 640 x 360); "
              "on screen from 1.02 s to 2.02 s, the whole of the mark" in listed
              and "the box on its middle frame: " + str(own("m1-middle")) in listed and "the box on its last frame: " + str(own("m1-end")) in listed
              and "box: left 0.500, top 0.500, width 0.250, height 0.250 of the frame (x 320 to 480, y 180 to 270 of 640 x 360); on screen at 3.02 s only" in listed,
              "todo names each box with its place in shares of the frame and in pixels, the times it is on screen, and the pictures of it")
        brief = studio.brief(boxcut["id"])
        check("A mark on a clip may carry a box" in brief and "  Box: left 0.125, top 0.250, width 0.500, height 0.400 of the frame" in brief
              and f"the box on its last frame: `batches/{boxcut['id']}/marks/a/m1-end.png`" in brief,
              "the brief for the next round names each box, its times and its pictures")
        in_schema = json.loads((Path(__file__).resolve().parent / "schemas" / "verdict.schema.json").read_text(encoding="utf-8"))["properties"]["candidates"]["additionalProperties"]["properties"]["marks"]["properties"]
        check(set(in_schema["spans"]["items"]["properties"]["box"]["properties"]) == set(logo), "the verdict's schema names the box and its four shares")
        shutil.rmtree(studio.batch_dir(boxcut["id"]))

        # the overview: the road, the build in hand, what only the user can do
        studio.set_milestone("M1", name="One room", status="current")
        studio.set_now(headline="Built.", next=["The user's picks"])
        studio.set_hand("walk", title="Walk the build", status="open")
        before = next(x for x in studio.hands() if x["id"] == "walk")
        http("POST", base + "/api/hand", {"id": "walk", "action": "done", "note": "by mistake"})
        status, _ = http("POST", base + "/api/hand", {"id": "walk", "action": "undo"})
        back = next(x for x in studio.hands() if x["id"] == "walk")
        again, _ = http("POST", base + "/api/hand", {"id": "walk", "action": "undo"})
        check(status == 200 and back == before and studio.unseen_hands() == [] and again == 400,
              "Undo puts an answered ask back as it was, out of Claude's queue, and only once")
        status, state = http("GET", base + "/api/state")
        ov = state["overview"]
        check(ov["milestones"][0]["status"] == "current" and ov["now"]["next"] == ["The user's picks"] and ov["hands"][0]["id"] == "walk",
              "the overview holds the road, the build in hand and what only the user can do")
        status, _ = http("POST", base + "/api/hand", {"id": "walk", "action": "done", "note": "walked it"})
        check(status == 200 and studio.unseen_hands()[0]["his_note"] == "walked it", "what the user marks done on the page reaches Claude's queue")
        studio.see_hand("walk")
        check(studio.unseen_hands() == [], "and leaves it once read")
        left = [x["id"] for x in ov["setup"] if not x["done"] and not x.get("optional")]
        hid, _ = http("POST", base + "/api/setup", {"hidden": True})
        _, hidden = http("GET", base + "/api/state")
        back, _ = http("POST", base + "/api/setup", {"hidden": False})
        _, shown = http("GET", base + "/api/state")
        check(left and not ov.get("setup_hidden") and hid == 200 and hidden["overview"]["setup_hidden"] is True
              and back == 200 and shown["overview"]["setup_hidden"] is False and (home / "overview" / "page.json").is_file(),
              "the Getting organised box is hidden from the page and brought back, kept in the Studio so the phone copy has it too")
        said = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "studio.py"), "--home", str(home), "status"],
                              capture_output=True, text=True, encoding="utf-8").stdout
        check(Path(ov["move_in"]).is_file() and ov["move_in"].endswith("MOVE-IN.md") and "Getting organised:" in said
              and all(f"] {x}" in said for x in left),
              "the box's one line names the move-in guide, which is there, and status lists the same unticked lines")
        taught = tmp / "taught"
        taught.mkdir()
        (taught / "CLAUDE.md").write_text("# Notes\n\nNothing about the Studio.\n", encoding="utf-8")
        before_merge = setup.taught(taught, home)
        (taught / "AGENTS.md").write_text("S is py -3.11 studio.py --home \"" + str(home).replace("\\", "/").upper() + "\"\n", encoding="utf-8")
        check(not before_merge and setup.taught(taught, home),
              "the skill line is ticked only once an instructions file names the Studio, whatever its slashes and case")
        cli = lambda *args: subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "studio.py"), "--home", str(home), *args],  # noqa: E731
                                           capture_output=True, text=True, encoding="utf-8")
        written = tmp / "skillout" / "SKILL.md"
        cli("skill", "--out", str(written))
        check(written.read_bytes().decode("utf-8") == cli("skill").stdout.replace("\r\n", "\n"),
              "skill --out writes the skill as UTF-8, the same as it prints")

        # buttons: a session files a line to run or a file to open; the user's click does it on the PC
        from studiolib import buttons
        tool = Path(__file__).resolve().parent / "studio.py"
        def ask_cli(*args, env=None):
            return subprocess.run([sys.executable, str(tool), "--home", str(home), "hand", "set", *args], capture_output=True,
                                  text=True, encoding="utf-8", env=dict(os.environ, **(env or {})))
        made = ask_cli("build", "--title", "Build it", "--button", "Build", "--run", "echo built-it > here.txt; echo built-it; exit 3",
                       "--cwd", str(proj), env={"STUDIO_SESSION": "s-btn"})
        row = next((x for x in studio.hands() if x["id"] == "build"), {})
        check(made.returncode == 0 and row.get("button") == "Build" and Path(row.get("cwd", "")) == proj.resolve() and row.get("session") == "s-btn",
              "a session files a button with one command: its words, the line, the folder, and which session filed it")
        bad = ask_cli("both", "--title", "Both", "--button", "X", "--run", "echo x", "--open", str(proj))
        loose = ask_cli("loose", "--title", "Loose", "--open", str(proj))
        check(bad.returncode == 2 and loose.returncode == 2 and not any(x["id"] in ("both", "loose") for x in studio.hands()),
              "a button runs a line or opens a file, not both, and a file to open needs a button")
        status, state = http("GET", base + "/api/state")
        shown = next(x for x in state["overview"]["hands"] if x["id"] == "build")
        check(shown["can_run"] is True and shown["ran"] is None and "can_run" not in next(x for x in state["overview"]["hands"] if x["id"] == "walk"),
              "the page is told which asks have a button it can press")
        status, _ = http("POST", base + "/api/button", {"id": "build"}, {"Origin": "http://elsewhere.example"})
        refused = [status]
        req = urllib.request.Request(base + "/api/button", data=b"id=build", method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            urllib.request.urlopen(req, timeout=10); refused.append(200)
        except urllib.error.HTTPError as err:
            refused.append(err.code)
        status, said = http("POST", base + "/api/button", {"id": "walk", "run": "echo hacked > hacked.txt"})
        refused.append(status)
        status, _ = http("GET", base + "/api/button/..%2F..%2Fstudio")
        refused.append(status)
        check(refused == [403, 415, 400, 404] and "no button" in said.get("error", "") and not (proj / "hacked.txt").exists()
              and not (home / "hacked.txt").exists(), "only a button a session filed runs: another site, a plain form, a line sent from the page are all refused")
        clock = time.time()
        status, pressed = http("POST", base + "/api/button", {"id": "build"})
        quick = time.time() - clock
        ran = {}
        for _ in range(300):
            ran = http("GET", base + "/api/button/build")[1].get("ran") or {}
            if ran.get("state") != "running":
                break
            time.sleep(0.1)
        check(status == 200 and pressed["ran"]["state"] == "running" and quick < 3 and ran.get("state") == "done" and ran.get("code") == 3
              and "built-it" in ran.get("tail", []) and (proj / "here.txt").exists(),
              "pressing it runs the line in its folder, and the page reads its exit code and its last lines")
        ask_cli("wait", "--title", "A long build", "--button", "Build slowly", "--run", "sleep 20", "--cwd", str(proj))
        clock = time.time()
        status, _ = http("POST", base + "/api/button", {"id": "wait"})
        quick, again = time.time() - clock, http("POST", base + "/api/button", {"id": "wait"})
        state_now = http("GET", base + "/api/state")[1]
        status_stop, _ = http("POST", base + "/api/button", {"id": "wait", "action": "stop"})
        for _ in range(100):
            ran = http("GET", base + "/api/button/wait")[1].get("ran") or {}
            if ran.get("state") != "running":
                break
            time.sleep(0.1)
        check(status == 200 and quick < 3 and again[0] == 400 and "still running" in again[1]["error"] and status_stop == 200
              and next(x for x in state_now["overview"]["hands"] if x["id"] == "wait")["ran"]["state"] == "running" and ran.get("state") == "stopped",
              "a long run leaves the page free, is not started twice, and stops when the user says")
        opened = []
        buttons.OPENER = opened.append
        (proj / "notes.txt").write_text("read me", encoding="utf-8")
        ask_cli("look", "--title", "Read the notes", "--button", "Open the notes", "--open", str(proj / "notes.txt"))
        status, pressed = http("POST", base + "/api/button", {"id": "look"})
        check(status == 200 and opened == [proj.resolve() / "notes.txt"] and pressed["ran"]["state"] == "opened",
              "a button that opens a file opens it in its default app")
        studio.answer_hand("look", "done")
        status, said = http("POST", base + "/api/button", {"id": "look"})
        studio.see_hand("look")
        check(status == 400 and len(opened) == 1, "a button on an ask that is done does nothing")
        far_copy = Studio.init(tmp / "site-copy", "Site copy", str(proj))
        (far_copy.home / "studio.local.toml").write_text('site = "p"\n', encoding="utf-8")
        far_copy = Studio(far_copy.home)
        far_copy.set_hand("build", title="Build it", button="Build", run="echo built > far.txt", cwd=str(proj))
        far = ThreadingHTTPServer(("127.0.0.1", 0), None)
        far.RequestHandlerClass = server.make_handler(far_copy.home, {f"127.0.0.1:{far.server_address[1]}"}, quiet=True)
        threading.Thread(target=far.serve_forever, daemon=True).start()
        fbase = f"http://127.0.0.1:{far.server_address[1]}"
        status, _ = http("POST", fbase + "/api/button", {"id": "build"})
        shown = next(x for x in http("GET", fbase + "/api/state")[1]["overview"]["hands"] if x["id"] == "build")
        far.RequestHandlerClass = server.make_handler(far_copy.home, {f"127.0.0.1:{far.server_address[1]}"}, quiet=True, launch="/ignition")
        asked = http("GET", fbase + "/api/state")[1]["launch"]
        far.shutdown(); far.server_close()
        spaced = Studio.init(tmp / "site-copy-2", "Spaced", str(tmp / "Two Words"))
        (spaced.home / "studio.local.toml").write_text('site = "p"\ngame_repo = ""\n', encoding="utf-8")  # the old key name, still read
        spaced_info = server.launch_info(Studio(spaced.home), "/ignition/")
        odd = Studio.init(tmp / "site-copy-3", "Odd", str(tmp / "Kite & Lab"))
        (odd.home / "studio.local.toml").write_text('site = "p"\nproject_repo = ""\n', encoding="utf-8")
        odd_info = server.launch_info(Studio(odd.home), "/ignition/")
        check(asked == {"url": "/ignition/", "folder": proj.name, "repo": "p:" + proj.name, "why": ""}
              and spaced_info["repo"] == "p:Two Words" and odd_info["repo"] == "" and "Kite & Lab" in odd_info["why"]
              and server.launch_info(studio, "/ignition/") is None and server.launch_info(far_copy, "") is None,
              "a server copy's page is told where to start Claude for its project folder; never the PC's, and not a name the launcher refuses")
        try:
            buttons.press(far_copy, "build"); direct = True
        except StudioError:
            direct = False
        time.sleep(0.5)
        check(status == 403 and shown["can_run"] is False and not direct and not (proj / "far.txt").exists(),
              "the server's copy for the phone runs nothing: it is not the PC")

        # the board: progress counted from steps, work in progress, the log, a snapshot a day
        studio.set_milestone("M2", name="Two rooms", status="next", weight=3)
        board.set_step(studio, "M1", "walls", name="Walls", status="done", date="2026-01-02")
        board.set_step(studio, "M1", "door", name="A door", status="tested")
        board.set_step(studio, "M1", "light", name="Light")
        board.set_step(studio, "M1", "cut", name="A cut idea", status="dropped")
        view = board.view(studio)
        m1 = view["milestones"][0]
        check(abs(m1["pct"] - 100 * (1 + 0.85 + 0) / 3) < 0.1 and abs(view["pct"] - m1["pct"] / 4) < 0.1 and view["counts"]["done"] == 1
              and view["steps"] == 3, "progress is counted from the steps: a dropped step is left out, a heavier milestone weighs more")
        check(view["days"][0]["date"] <= "2026-10-01" or len(view["days"]) == board.CHART_DAYS, "a step that landed on an earlier day is on the chart")
        lane = board.set_lane(studio, "light", name="Lighting the room", milestone="M1", step="light", eta="16:30")
        check(lane["state"] == "building" and board.view(studio)["milestones"][0]["steps"][2]["status"] == "building"
              and board.events(studio)[-1]["kind"] == "start", "a lane that starts on a planned step marks it building, and says so in the log")
        board.log(studio, "setback", "The lamp flickers on the laptop")
        board.end_lane(studio, "light", step_status="done")
        view = board.view(studio)
        check(not view["lanes"] and view["events"][0]["kind"] == "done" and view["events"][1]["kind"] == "setback"
              and view["days"][-1]["setbacks"] == 1 and view["days"][-1]["pct"] == view["pct"],
              "a lane that lands leaves the board; the log and today's point on the chart follow")
        try:
            board.set_lane(studio, "x", name="X", milestone="M1", step="nope"); check(False, "a lane on a step that does not exist is refused")
        except StudioError:
            check(True, "a lane on a step that does not exist is refused")
        plan = board.plan(studio)
        plan["milestones"].append({"id": "M3", "name": "Three rooms", "status": "later", "steps": [{"id": "roof", "name": "A roof"}]})
        made = board.apply_plan(studio, dict(plan, goal="A house.", counters=["Rooms=1/3"],
                                             asks=[{"id": "paint", "kind": "decision", "title": "Paint it?", "default": "Leave it bare", "urgent": True}]))
        ask = next(x for x in studio.hands() if x["id"] == "paint")
        check(made["milestones"] == 3 and len(studio.roadmap()) == 3 and studio.now()["goal"] == "A house." and studio.now()["counters"][0]["of"] == 3
              and ask["kind"] == "decision" and ask["urgent"] and ask["status"] == "open", "a whole plan is written in at once: milestones, steps, the goal, counters, asks")
        studio.close_hand("paint", "Bare is fine.")
        check(next(x for x in studio.hands() if x["id"] == "paint")["his_note"] == "Bare is fine." and studio.unseen_hands() == [],
              "an ask the user answered in chat is closed with their words")
        board.set_step(studio, "M1", "door", status="done")
        check(any("M1" in line for line in board.advice(studio)) and [x["id"] for x in state["overview"]["setup"] if not x["done"]],
              "a board that is not true is pointed out: every step done on a milestone still open")

        # the sessions, as Claude Code's hooks report them
        hooks = tmp / "hooks.json"
        setup.register("Self-test", home, proj, 1, hooks)
        hook_env = dict(os.environ, STUDIO_REGISTRY=str(hooks), LOCALAPPDATA=str(tmp / "local"))

        def hook(**event) -> None:
            run = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "hook.py")], input=json.dumps(event).encode(),
                                 capture_output=True, env=hook_env)
            assert run.returncode == 0 and not run.stdout and not run.stderr, run

        deep = proj / "content"
        deep.mkdir(exist_ok=True)
        hook(session_id="s-1", cwd=str(deep), hook_event_name="SessionStart", source="startup")
        run = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "hook.py")], capture_output=True, env=hook_env,
                             input=json.dumps(dict(session_id="s-1", cwd=str(deep), hook_event_name="UserPromptSubmit", prompt="Light the room\nand test it")).encode())
        given = json.loads(run.stdout or b"{}").get("hookSpecificOutput", {}).get("additionalContext", "")
        check(batch["id"] in given and "shipped" in given and "S todo" in given and "Answer what the user just asked first" in given,
              "a verdict reaches the session with the user's next message, after what they asked, and says to run S todo")
        check(all(not json.loads(subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "hook.py")], capture_output=True, env=hook_env,
                                                input=json.dumps(dict(session_id=sid, cwd=str(deep), hook_event_name=ev)).encode()).stdout or b"{}")
                  for sid, ev in (("s-1", "Stop"), ("s-1", "PostToolUse"))),
              "a verdict is handed over once, and never between tool calls")
        hook(session_id="s-1", cwd=str(deep), hook_event_name="PreToolUse", tool_name="Edit", tool_input={"file_path": str(deep / "room.scene")})
        hook(session_id="s-1", cwd=str(deep), hook_event_name="SubagentStart", agent_id="a1", agent_type="Explore")
        hook(session_id="s-2", cwd=str(tmp), hook_event_name="SessionStart")  # a folder with no Studio
        status, live = http("GET", base + "/api/live")
        one = live["sessions"][0] if status == 200 and live["sessions"] else {}
        check(len(live["sessions"]) == 1 and one["state"] == "working" and one["prompt"] == "Light the room and test it"
              and one["doing"] == "Editing room.scene" and one["agents"][0]["type"] == "Explore" and one["where"] == "content"
              and one["agent"] == "claude",
              "a session's hooks say what it is doing, and the page can ask; a folder with no Studio is left alone")
        hook(session_id="s-1", cwd=str(deep), hook_event_name="SubagentStop", agent_id="a1")
        hook(session_id="s-1", cwd=str(deep), hook_event_name="Stop", last_assistant_message="The room is lit.",
             background_tasks=[{"type": "workflow", "status": "running", "description": "review"}])
        one = board.sessions(studio)[0]
        check(one["state"] == "background" and not one["agents"] and one["said"] == "The room is lit." and one["background"][0]["type"] == "workflow",
              "a session that stops with work still running in the background says so")
        hook(session_id="s-1", cwd=str(deep), hook_event_name="SessionEnd")
        check(board.sessions(studio)[0]["state"] == "ended" and (home / "live" / ".gitignore").exists(), "a session that ends is marked ended, and none of this is history")

        # Send verdicts: a session idle at its prompt is woken only when the user presses it, through the waiter hook
        from studiolib import wake

        def waiter(sid: str):
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / "hook.py"), "--wait"], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=hook_env)
            proc.stdin.write(json.dumps(dict(session_id=sid, cwd=str(deep), hook_event_name="Stop")).encode()); proc.stdin.close()
            for _ in range(100):
                if sid in wake.awake(home) and (home / "live" / "wake" / f"{sid}.wait").read_text(encoding="utf-8").startswith(f"{proc.pid}:"):
                    break
                time.sleep(0.1)
            return proc

        hook(session_id="s-w", cwd=str(deep), hook_event_name="SessionStart")
        hook(session_id="s-w", cwd=str(deep), hook_event_name="Stop")
        first = waiter("s-w")
        second = waiter("s-w")
        first.wait(10)
        status, seen = http("GET", base + "/api/wake")
        check(first.returncode == 0 and not first.stderr.read() and status == 200 and [s["id"] for s in seen["sessions"]] == ["s-w"]
              and seen["waiting"] >= 1 and seen["unseen"] == 0,
              "a newer waiter for a session takes over from the older one, and the page sees who can be told and what waits")
        status, refused = http("POST", base + "/api/wake", {"session": "s-1"})
        check(status == 400 and "cannot be reached" in refused.get("error", ""), "a session with no waiter is not told, and the page says why")
        status, sent = http("POST", base + "/api/wake", {"session": "s-w"})
        second.wait(10)
        told = second.stderr.read().decode("utf-8")
        check(status == 200 and sent["how"] == "woken" and second.returncode == 2 and "pressed Send verdicts" in told and batch["id"] in told
              and "S todo" in told and "s-w" not in wake.awake(home) and not (home / "live" / "wake" / "s-w.go").exists(),
              "pressing Send verdicts wakes that session with what waits for it (exit 2 for asyncRewake), and the waiter is gone")
        hook(session_id="s-w", cwd=str(deep), hook_event_name="SessionEnd")

        # the hooks go into Claude Code's settings beside whatever is there, and come out again
        settings = setup.claude_settings()
        settings.parent.mkdir(parents=True)
        theirs = {"model": "opus", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}
        settings.write_text(json.dumps(theirs), encoding="utf-8")
        check(setup.hooks_installed() == [], "hooks are not there until they are installed")
        setup.install_hooks(); setup.install_hooks()
        data = json.loads(settings.read_text(encoding="utf-8"))
        check(set(setup.hooks_installed()) == set(setup.HOOK_EVENTS) and data["model"] == "opus" and len(data["hooks"]["Stop"]) == 2
              and data["hooks"]["Stop"][0] == theirs["hooks"]["Stop"][0] and "async" not in data["hooks"]["SessionStart"][0]["hooks"][0]
              and data["hooks"]["PreToolUse"][0]["hooks"][0]["async"] is True and setup.hooks_hand_over() and setup.hooks_wake()
              and data["hooks"]["Stop"][-1]["hooks"][1]["asyncRewake"] is True and data["hooks"]["Stop"][-1]["hooks"][1]["args"][-1] == "--wait"
              and len(data["hooks"]["PostToolUse"][-1]["hooks"]) == 1
              and all("async" not in data["hooks"][e][-1]["hooks"][0] and data["hooks"][e][-1]["hooks"][0]["timeout"] for e in ("Stop", "PostToolUse"))
              and json.loads(Path(str(settings) + ".before-nocstudio").read_text(encoding="utf-8")) == theirs,
              "installing twice leaves one hook per event, the user's own settings as they were, and a copy from before")
        setup.install_hooks(remove=True)
        check(json.loads(settings.read_text(encoding="utf-8")) == theirs, "removing them puts the settings back")
        settings.write_text("{ not json", encoding="utf-8")
        try:
            setup.install_hooks(); check(False, "a settings file that does not parse is refused, not rewritten")
        except StudioError:
            check(settings.read_text(encoding="utf-8") == "{ not json", "a settings file that does not parse is refused, not rewritten")
        settings.unlink()

        # the notes box: typed on the page, handed to a session by the hooks, sorted, confirmed, worked in
        def handed(**event) -> str:
            run = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "hook.py")], input=json.dumps(event).encode(),
                                 capture_output=True, env=hook_env)
            assert run.returncode == 0 and not run.stderr, run
            return json.loads(run.stdout)["hookSpecificOutput"]["additionalContext"] if run.stdout else ""

        def note_cli(*args, session: str = "") -> str:
            run = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "studio.py"), "--home", str(home), "note", *args],
                                 capture_output=True, text=True, encoding="utf-8", env=dict(hook_env, STUDIO_SESSION=session))
            return run.stdout + run.stderr

        for sid in ("s-3", "s-4"):
            hook(session_id=sid, cwd=str(deep), hook_event_name="SessionStart")
        board.set_lane(studio, "walls", name="Walls", session="s-4")
        said = "door width to 0.9, same as the hall.  Could the roof be flat instead, how much work?"
        status, made = http("POST", base + "/api/note", {"text": said})
        nid = (made.get("note") or {}).get("id", "")
        check(status == 200 and made["note"]["status"] == "new" and made["note"]["text"] == said
              and handed(session_id="s-3", cwd=str(deep), hook_event_name="PostToolUse", tool_name="Read") == "",
              "a note typed on the page is kept as typed, and does not break into work the moment it is typed")
        text = handed(session_id="s-3", cwd=str(deep), hook_event_name="Stop")
        check(nid in text and "> door width to 0.9" in text and "TO SORT (1)" in text and "walls (Walls)" in text
              and handed(session_id="s-4", cwd=str(deep), hook_event_name="Stop") == ""
              and handed(session_id="s-3", cwd=str(deep), hook_event_name="Stop") == "",
              "a session that finishes a turn is handed the note in the user's words, once, and no other session is handed it too")
        part = note_cli("split", nid, "Could the roof be flat instead, how much work?", session="s-3")
        qid = part.split(":")[0]
        refused = note_cli("split", nid, "Could the roof be made of glass?", session="s-3")
        note_cli("sort", nid, "--kind", "directive", "--reading", "Set the door's width to 0.9 m, the width of the hall.", "--lane", "walls", session="s-3")
        note_cli("reply", qid, "A day: the rafters go, the walls rise 30 cm.", session="s-3")
        early = note_cli("done", nid, "--result", "Done.", session="s-4")
        notes = {n["id"]: n for n in http("GET", base + "/api/state")[1]["notes"]}
        check(qid.startswith("N-") and "own words" in refused and notes[nid]["status"] == "confirm" and notes[nid]["waits"] == "you"
              and notes[qid]["kind"] == "discussion" and notes[qid]["waits"] == "you" and notes[qid]["from"] == nid and "waits on the user" in early
              and handed(session_id="s-4", cwd=str(deep), hook_event_name="Stop") == "",
              "a session sorts a note and splits one that holds two things; a change waits on the user, and nothing is done before they confirm")
        http("POST", base + f"/api/note/{nid}", {"action": "confirm"})
        http("POST", base + f"/api/note/{qid}", {"action": "reply", "text": "And if it leaks?"})
        mine, theirs = handed(session_id="s-3", cwd=str(deep), hook_event_name="Stop"), handed(session_id="s-4", cwd=str(deep), hook_event_name="Stop")
        check("TO ANSWER (1)" in mine and "And if it leaks?" in mine and nid not in mine and "TO DO (1)" in theirs and nid in theirs and qid not in theirs,
              "a confirmed change goes to the session on that work, and a reply goes to the session in the conversation")
        closed = note_cli("done", nid, "--result", "The door is 0.9 m wide.", "--ref", "abc1234", session="s-4")
        ruling = studio.decisions()[-1]
        check("on the record as " + ruling["id"] in closed and ruling["his_words"] == said and ruling["source"] == {"type": "note", "ref": nid}
              and studio.note(nid)["status"] == "done", "closing a change the user ordered records it as a decision in their words")
        status, made = http("POST", base + "/api/note", {"text": "The latch sticks", "kind": "bug", "urgent": True})
        bug = made["note"]["id"]
        wrong = note_cli("sort", bug, "--kind", "later", session="s-3")
        check(handed(session_id="s-3", cwd=str(deep), hook_event_name="PostToolUse", tool_name="Read", agent_id="a7") == ""
              and bug in handed(session_id="s-3", cwd=str(deep), hook_event_name="PostToolUse", tool_name="Read") and "themselves" in wrong,
              "an urgent note reaches a session between tool calls, never a subagent; the kind the user chose stands")
        note_cli("sort", bug, "--kind", "bug", "--reading", "The front door's latch does not release.", session="s-3")
        status, made = http("POST", base + "/api/note", {"text": "A weathervane someday?", "kind": "later"})
        notes = {n["id"]: n for n in http("GET", base + "/api/state")[1]["notes"]}
        check(notes[bug]["status"] == "go" and notes[bug]["to"] == "" and notes[made["note"]["id"]]["waits"] == ""
              and handed(session_id="s-3", cwd=str(deep), hook_event_name="Stop") == ""
              and http("POST", base + f"/api/note/{bug}", {"action": "send", "session": "s-3"})[0] == 200
              and "TO DO (1)" in handed(session_id="s-3", cwd=str(deep), hook_event_name="Stop"),
              "a note no session is on waits until the user sends it; an idea for later waits on nobody")

        # the Category menu and Close: the same category changes nothing, Unsorted hands a note back, a new category brings a Later note back
        def seen(nid: str) -> dict:
            return next(n for n in http("GET", base + "/api/state")[1]["notes"] if n["id"] == nid)

        later = made["note"]["id"]
        status, same = http("POST", base + f"/api/note/{bug}", {"action": "kind", "kind": "bug"})
        check(status == 200 and same["note"]["status"] == "go" and same["note"]["session"] == "s-3" and same["note"]["reading"],
              "choosing the category a note already has changes nothing, and no session is handed it again")
        status, back = http("POST", base + f"/api/note/{bug}", {"action": "kind", "kind": ""})
        text = handed(session_id="s-4", cwd=str(deep), hook_event_name="Stop")
        check(status == 200 and (back["note"]["kind"], back["note"]["kind_by"], back["note"]["status"], back["note"]["reading"]) == ("", "", "new", "")
              and "TO SORT (1)" in text and bug in text and "the user marked it" not in text and '--option "<name> :: <what it means>"' in text,
              "a note set to Unsorted goes back to a session to sort as it sees fit, and the session is told how to give choices")
        asked = note_cli("sort", bug, "--kind", "bug", "--reading", "The front door's latch does not release.", "--mine",
                         "--option", "Oil it :: Ten minutes; it may stick again.", "--option", "Replace it :: A new latch, an hour.", session="s-4")
        row, quiet = seen(bug), handed(session_id="s-4", cwd=str(deep), hook_event_name="Stop")
        http("POST", base + f"/api/note/{bug}", {"action": "reply", "text": "Replace it"})
        text = handed(session_id="s-4", cwd=str(deep), hook_event_name="Stop")
        check("picks one of the 2 choices" in asked and row["status"] == "go" and row["waits"] == "you" and row["choice_at"] == "reading" and quiet == ""
              and seen(bug)["waits"] == "claude" and seen(bug)["choice_at"] is None
              and "TO DO (1)" in text and "- Replace it: A new latch, an hour." in text and "They said: Replace it" in text,
              "a bug sorted with choices waits on the user, and reaches the session only with their pick on it")
        status, woke = http("POST", base + f"/api/note/{later}", {"action": "kind", "kind": "discussion"})
        shut = http("POST", base + f"/api/note/{later}", {"action": "done"})[1]["note"]
        again = http("POST", base + f"/api/note/{later}", {"action": "reopen"})[1]["note"]
        check(status == 200 and woke["note"]["status"] == "new" and woke["note"]["kind_by"] == "you"
              and shut["status"] == "done" and shut["closed_by"] == "you" and again["status"] == "new" and again["kind"] == "discussion",
              "a new category brings a note kept for later back; Close closes a note from the page, and it opens again")

        # choices: a session gives them apart from its text, the page shows a card each, and the user's pick comes back as their reply
        few = note_cli("reply", later, "Yes.", "--option", "Copper :: Lasts longest.", session="s-3")
        long = note_cli("reply", later, "Yes.", "--option", "x" * 61 + " :: too long a name", "--option", "Tin :: Cheap.", session="s-3")
        wordy = note_cli("reply", later, "Yes.", "--option", "Copper :: " + "y" * 301, "--option", "Tin :: Cheap.", session="s-3")
        twin = note_cli("reply", later, "Yes.", "--option", "Tin :: Cheap.", "--option", "tin :: Light.", session="s-3")
        check("2 to 6" in few and "at most 60" in long and "at most 300" in wordy and "both named" in twin and studio.note(later)["thread"] == [],
              "one choice alone, a name over 60 characters, a meaning over 300 and two choices of one name are refused, and nothing is written")
        said = note_cli("reply", later, "Yes, and there are three ways to make it.", "--option", "Copper :: Lasts longest, costs most.",
                        "--option", "Tin::Cheap and light.", "--option", "Wood", session="s-3")
        row = seen(later)
        first = dict(row["thread"][0])
        check("3 choices" in said and first["text"] == "Yes, and there are three ways to make it." and row["waits"] == "you" and row["choice_at"] == 0
              and first["options"] == [{"name": "Copper", "what": "Lasts longest, costs most."}, {"name": "Tin", "what": "Cheap and light."}, {"name": "Wood", "what": ""}],
              "a session's answer keeps its choices apart from its text, a name and a meaning each, and the note waits on the user's pick")
        http("POST", base + f"/api/note/{later}", {"action": "reply", "text": "Tin"})
        row, text = seen(later), handed(session_id="s-3", cwd=str(deep), hook_event_name="Stop")
        check(row["thread"][0] == first and row["thread"][1]["who"] == "you" and row["thread"][1]["text"] == "Tin" and row["choice_at"] is None
              and row["waits"] == "claude" and "TO ANSWER (1)" in text and "- Tin: Cheap and light." in text and "They: Tin" in text and "--option" in text,
              "the user's pick is their reply: it reaches the session with the choices it was picked from, and the session's own entry is not changed")
        gate = http("POST", base + "/api/note", {"text": "make the gate wider"})[1]["note"]["id"]
        note_cli("sort", gate, "--kind", "directive", "--reading", "Widen one of the two gates.",
                 "--option", "Front gate :: To 1.2 m.", "--option", "Back gate :: To 1.0 m.", session="s-3")
        row = seen(gate)
        status, _ = http("POST", base + f"/api/note/{gate}", {"action": "confirm"})
        check(row["status"] == "confirm" and row["choice_at"] == "reading" and [o["name"] for o in row["reading_options"]] == ["Front gate", "Back gate"]
              and status == 400 and studio.note(gate)["status"] == "confirm",
              "a reading given with choices waits on the user's pick, and is not confirmed as it stands")
        http("POST", base + f"/api/note/{gate}", {"action": "back", "text": "Back gate"})
        text = handed(session_id="s-4", cwd=str(deep), hook_event_name="Stop")
        note_cli("sort", gate, "--kind", "directive", "--reading", "Widen the back gate to 1.0 m.", session="s-4")
        row = seen(gate)
        check("TO SORT (1)" in text and "- Back gate: To 1.0 m." in text and "They then said: Back gate" in text
              and row["status"] == "confirm" and row["choice_at"] is None and row["reading_options"] == []
              and http("POST", base + f"/api/note/{gate}", {"action": "confirm"})[0] == 200,
              "a pick on a reading to confirm sends the note back to be sorted as what was picked; the plain reading that follows is confirmed as before")

        # a session is told what happened to a note and no more: a pick is not the user's own category, a note closed before
        # its pick asks nothing when it is opened again, and a pick sends a bug nowhere the sort did not send it
        from studiolib import notes as notebox
        fence = http("POST", base + "/api/note", {"text": "paint the fence"})[1]["note"]["id"]
        ruled = http("POST", base + "/api/note", {"text": "fences are green from now on", "kind": "rule"})[1]["note"]["id"]
        note_cli("sort", fence, "--kind", "directive", "--reading", "Paint the fence one of two colours.",
                 "--option", "Green :: As the gate.", "--option", "White :: As the house.", session="s-3")
        http("POST", base + f"/api/note/{fence}", {"action": "back", "text": "Green"})
        told = notebox.wording([studio.note(fence), studio.note(ruled)], home)
        check("the user marked it" not in text and f"  {fence}\n" in told and f"  {ruled}  (the user marked it: a standing rule; sort it as `rule`)" in told
              and told.count("the user marked it") == 1 and "An earlier reading, which they sent back: Paint the fence" in told,
              "after a pick on a reading the session is not told the user marked the note; it is told so only of a kind the user chose themselves")
        note_cli("sort", fence, "--kind", "bug", "--reading", "The fence's paint peels.", "--option", "Strip it :: A day.", "--option", "Paint over :: An hour.", session="s-3")
        live = seen(fence)
        http("POST", base + f"/api/note/{fence}", {"action": "done"})
        http("POST", base + f"/api/note/{fence}", {"action": "reopen"})
        opened, told = seen(fence), notebox.wording([studio.note(fence)], home)
        note_cli("reply", fence, "Which side of the fence?", session="s-3")
        talk = seen(fence)
        check((live["status"], live["waits"], live["choice_at"]) == ("go", "you", "reading") and (opened["status"], opened["waits"], opened["choice_at"]) == ("new", "claude", None)
              and "An earlier reading: The fence's paint peels." in told and "sent back" not in told and "- Strip it: A day." in told
              and (talk["status"], talk["waits"], talk["choice_at"]) == ("talk", "you", None) and len(opened["reading_options"]) == 2,
              "a note closed before its pick and opened again asks nothing: the old reading's choices take no click, then or under the answer that follows, and it is not said to be sent back")
        hinge = http("POST", base + "/api/note", {"text": "the hinge squeaks"})[1]["note"]["id"]
        lone = note_cli("sort", hinge, "--kind", "bug", "--reading", "The gate's top hinge squeaks.", "--option", "Oil it :: A minute.", "--option", "New hinge :: An hour.", session="s-3")
        http("POST", base + f"/api/note/{hinge}", {"action": "reply", "text": "Oil it"})
        row, how = seen(hinge), notebox.wording([studio.note(ruled)], home)
        check("picks one of the 2 choices" in lone and "it still goes to no session" in lone and "page says so" in lone and "then it is yours to do, with their pick on it" in asked
              and (row["status"], row["waits"], row["to"]) == ("go", "claude", "") and "to no session if you gave neither" in how and "goes on to the session" not in how,
              "a bug sorted with choices and sent to nobody is said to go to no session after the pick, as it does; sorted as --mine it is said to be the session's own")
        for nid_ in (fence, ruled, hinge):
            http("POST", base + f"/api/note/{nid_}", {"action": "done"})

        # files on a note: streamed to disk out of git, handed to a session by path, archived on close, back on reopen
        def put_file(nid: str, name: str, blob: bytes):
            req = urllib.request.Request(base + f"/api/note/{nid}/file?name=" + urllib.parse.quote(name), data=blob, method="PUT", headers={"X-Studio-File": "1"})
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read())

        def until(test, seconds: float = 8.0) -> bool:
            end = time.time() + seconds
            while time.time() < end:
                if test():
                    return True
                time.sleep(0.1)
            return test()

        status, made = http("POST", base + "/api/note", {"text": "the screenshot shows where it breaks"})
        fid, blob = made["note"]["id"], os.urandom(3 * 1024 * 1024 + 7)  # bigger than any JSON body may be
        up = put_file(fid, "../shot 1.png", blob)
        kept = home / "notes" / "files" / fid / "shot 1.png"
        check(up["note"]["files"][0]["name"] == "shot 1.png" and kept.read_bytes() == blob,
              "a file put on a note is kept beside it, whatever its size, under a name that cannot leave its folder")
        req = urllib.request.Request(base + f"/api/note/{fid}/file?name=x.txt", data=b"x", method="PUT")
        try:
            urllib.request.urlopen(req, timeout=10)
            refused = False
        except urllib.error.HTTPError as err:
            refused = err.code == 415
        check(refused, "a file sent without the page's own header is refused, as another site's form would be")
        check(put_file(fid, "shot 1.png", b"again")["note"]["files"][1]["name"] == "shot 1 (2).png",
              "a second file of the same name is kept as well, not written over the first")
        check((home / "notes" / "files" / ".gitignore").read_text(encoding="utf-8").splitlines()[-1] == "*",
              "files on notes stay out of the Studio's git")
        with urllib.request.urlopen(base + f"/notefile/{fid}/" + urllib.parse.quote("shot 1.png")) as res:
            check(res.read() == blob, "the page shows a note's file")
        check(str(kept) in note_cli("waiting"), "a session handed the note is given each file's full path")
        status, after = http("POST", base + f"/api/note/{fid}", {"action": "unfile", "name": "shot 1 (2).png"})
        check(status == 200 and [f["name"] for f in after["note"]["files"]] == ["shot 1.png"]
              and not (kept.parent / "shot 1 (2).png").exists(), "a file put on a note by mistake can be taken off it")
        shelf = tmp / "archive"
        (home / "studio.local.toml").write_text(f'[files]\narchive = "{shelf.as_posix()}"\n', encoding="utf-8")
        http("POST", base + f"/api/note/{fid}", {"action": "done"})
        check(until(lambda: not kept.exists() and (shelf / fid / "shot 1.png").is_file()),
              "a closed note's files move to the archive and leave this copy")
        with urllib.request.urlopen(base + f"/notefile/{fid}/" + urllib.parse.quote("shot 1.png")) as res:
            check(res.read() == blob, "a closed note's file still opens, brought back from the archive")
        status, _ = http("PUT", base + f"/api/note/{fid}/file?name=x.txt", headers={"X-Studio-File": "1", "Content-Length": "0"})
        check(status == 400 or status == 411, "a closed note takes no new files")
        http("POST", base + f"/api/note/{fid}", {"action": "reopen"})
        check(until(lambda: kept.is_file() and kept.read_bytes() == blob), "opening the note again brings its files back")
        (home / "studio.local.toml").unlink()

        # talking to a session from the page: a stand-in for Claude Code asks to run a command, the page answers
        os.environ["STUDIO_CLAUDE"] = json.dumps([sys.executable, str(Path(__file__).resolve().parent / "selftest_claude.py")])

        def talk_until(key: str, test, seconds: float = 10.0):
            end, seen = time.time() + seconds, None
            while time.time() < end:
                status, seen = http("GET", base + f"/api/talk/{key}")
                if status == 200 and test(seen):
                    return seen
                time.sleep(0.1)
            return seen

        status, began = http("POST", base + "/api/talk", {"text": "make the thing"})
        key = began.get("key", "")
        seen = talk_until(key, lambda v: v["asks"])
        check(status == 200 and seen["asks"] and seen["asks"][0]["line"] == "Bash: make thing" and seen["state"] == "asking",
              "a session started from the page asks there before it runs something auto mode would not")
        status, _ = http("POST", base + f"/api/talk/{key}", {"action": "allow", "ask": seen["asks"][0]["id"]})
        seen = talk_until(key, lambda v: v["state"] == "idle")
        said = [e["text"] for e in seen["events"] if e["kind"] == "claude"]
        check(status == 200 and said == ["made it: make the thing"] and seen["id"] and seen["key"] == seen["id"],
              "allowed on the page, the session goes on and its answer shows, under the session's own id")
        studio.set_hand("talk-btn", title="Try it", button="Run it", run="echo hi", cwd=str(proj), session=seen["id"])
        studio.set_hand("other-btn", title="Not this one", button="Run that", run="echo no", cwd=str(proj), session="s-other")
        shown = [b["id"] for b in http("GET", base + f"/api/talk/{key}")[1].get("buttons", [])]
        check(shown == ["talk-btn"], "the Talk page shows the buttons its own session filed, beside the talk")
        waits = lambda: [t["waits"] for t in http("GET", base + "/api/talk")[1]["talks"]]
        before = waits()
        http("GET", base + f"/api/talk/{key}?after=0&seen=1")
        check(before == ["reply"] and waits() == [""], "a reply waits on the user until the page shows it in front of them")
        status, _ = http("POST", base + f"/api/talk/{key}", {"action": "say", "text": "and again"})
        seen = talk_until(key, lambda v: v["asks"])
        http("POST", base + f"/api/talk/{seen['id']}", {"action": "deny", "ask": seen["asks"][0]["id"], "text": "not now"})
        seen = talk_until(key, lambda v: v["state"] == "idle" and any(e["text"] == "did not: and again" for e in v["events"]))
        check(any(e["text"] == "did not: and again" for e in seen["events"]) and any(e["text"].startswith("Denied: ") for e in seen["events"]),
              "denied on the page, the session is told no and says so")
        status, listed = http("GET", base + "/api/talk")
        check(status == 200 and [t["id"] for t in listed["talks"]] == [seen["id"]], "the page lists the conversations it has going")

        # stop, and stop and send; and closing the app waits for a session in the middle of a turn
        from studiolib import app as app_mod, talk as talk_mod
        http("POST", base + f"/api/talk/{key}", {"action": "say", "text": "a third thing"})
        seen = talk_until(key, lambda v: v["asks"])
        lingered = threading.Thread(target=app_mod.linger, args=(types.SimpleNamespace(seen=0.0), 0.05), daemon=True)
        idle_was, app_mod.IDLE_SECONDS = app_mod.IDLE_SECONDS, 0
        lingered.start(); time.sleep(0.4)
        check(lingered.is_alive() and talk_mod.busy(), "with the window closed, the app stays while a session is in the middle of a turn")
        status, _ = http("POST", base + f"/api/talk/{key}", {"action": "say", "text": "do this instead", "stop": True})
        seen = talk_until(key, lambda v: v["asks"] and any(e["text"] == "do this instead" for e in v["events"]))
        notes = [e["text"] for e in seen["events"] if e["kind"] == "note"]
        check(status == 200 and "Stopped." in notes and not any("error" in n for n in notes) and len(seen["asks"]) == 1,
              "stop and send stops the turn, says it stopped (not an error), and starts the next turn with the message")
        status, _ = http("POST", base + f"/api/talk/{key}", {"action": "interrupt"})
        seen = talk_until(key, lambda v: v["state"] == "idle")
        lingered.join(2)
        check(status == 200 and seen["state"] == "idle" and not seen["asks"] and not lingered.is_alive(),
              "Stop ends the turn and the question it left open, and then the app with no window may close")
        app_mod.IDLE_SECONDS = idle_was
        status, said = http("POST", base + f"/api/talk/{key}", {"action": "interrupt"})
        check(status == 400 and "not doing anything" in said["error"], "Stop on a session that is not working says so")
        status, used = http("GET", base + "/api/usage?fresh=1")
        check(status == 200 and used["limits"] == [{"name": "Current session", "pct": 12.0, "resets": "3pm"},
                                                   {"name": "Current week (all models)", "pct": 40.0, "resets": "Nov 6, 8am (America/Chicago)"}],
              "the page reads the plan's usage from /usage, each limit with its share and when it resets")
        http("POST", base + f"/api/talk/{key}", {"action": "stop"})
        check(talk_until(key, lambda v: v["state"] == "ended")["state"] == "ended", "a conversation can be stopped, and says it stopped")
        moved = talk_until(key, lambda v: True)["id"]
        status, _ = http("POST", base + "/api/talk/desktop", {"id": moved})
        repo_dir = Path(studio.repo_root())
        check(status == 200 and (repo_dir / ".desktop-opened").read_text(encoding="utf-8") == moved,
              "a session moves to the Claude desktop app: claude --desktop --resume <its id>, in the project's folder")
        (repo_dir / ".desktop-opened").unlink()
        status, said = http("POST", base + "/api/talk/desktop", {"id": "../not-an-id"})
        check(status == 400, "only a session id is passed on to Claude Code")
        del os.environ["STUDIO_CLAUDE"]

        # an asset the user can open: what the project holds, by file, folder or glob
        (proj / "content/audio/core").mkdir(parents=True); (proj / "content/audio/tape").mkdir(parents=True)
        make_wav(proj / "content/audio/core/step_1.wav", -24.0, 0.2); make_wav(proj / "content/audio/tape/step_1.wav", -24.0, 0.2)
        (proj / "content/audio/core/step.toml").write_text("kind = 'audio.sfx'", encoding="utf-8")
        studio.set_slot("test.step", title="Step", kind="audio", group="Test", status="placeholder", project_path="content/audio/*/step_*.wav")
        status, state = http("GET", base + "/api/state")
        files = next(x for x in state["slots"] if x["id"] == "test.step")["files"]
        check([f["url"] for f in files] == ["/repo/content/audio/core/step_1.wav", "/repo/content/audio/tape/step_1.wav"],
              "a slot lists the project's own files for it")
        with urllib.request.urlopen(base + files[0]["url"]) as res:
            check(res.headers["Content-Type"] == "audio/wav", "a project file is served to the Library")
        status, _ = http("GET", base + "/repo/content/audio/core/step.toml")
        check(status == 404, "a project file that is not a picture, model or sound is refused")

        # a home saved under the names from when the tool served one game: read as today's, then rewritten
        old = Studio.init(tmp / "old-home", "Old", str(proj))
        (old.home / "studio.toml").write_text(f'project = "Old"\ngame_repo = "{proj.as_posix()}"\n\n[playtests]\ndirs = ["pt"]\n\n'
                                              '[recipes.ingame]\ntool = "by hand"\n', encoding="utf-8")
        (old.home / "slots" / "old.thing.json").write_text(json.dumps({"schema": 1, "id": "old.thing", "title": "Thing", "kind": "ingame",
            "group": "Old", "status": "in_game", "previous_status": "in_game", "game_path": "content/audio/core/"}), encoding="utf-8")
        old = Studio(old.home)
        feel_old = old.new_batch("feel", kind="in_app", ask="Which?", look_at=["It"], launch="app.exe")["id"]
        bj = old.batch_dir(feel_old) / "batch.json"
        bj.write_text(bj.read_text(encoding="utf-8").replace('"in_app"', '"ingame"'), encoding="utf-8")
        (old.home / "playtests").mkdir()
        (old.home / "playtests" / "triage.json").write_text('{"s/f8-1": {"status": "fixed"}}', encoding="utf-8")
        old = Studio(old.home)
        thing = old.slot("old.thing")
        check(thing["status"] == "in_use" and thing["kind"] == "in_app" and thing["previous_status"] == "in_use" and thing["project_path"] == "content/audio/core/"
              and "game_path" not in thing and old.load_batch(feel_old)["kind"] == "in_app" and old.repo_root() == proj.resolve()
              and old.test_run_dirs() == [(old.home / "pt").resolve()] and old.triage()["s/f8-1"]["status"] == "fixed"
              and old.config["recipes"]["in_app"]["tool"] == "by hand",
              "a home saved under the old names (in_game, game_path, ingame, game_repo, playtests) reads under today's")
        planned = old.migrate(dry_run=True)
        moved = old.migrate()
        again = Studio(old.home)
        raw_slot = json.loads((old.home / "slots" / "old.thing.json").read_text(encoding="utf-8"))
        toml = (old.home / "studio.toml").read_text(encoding="utf-8")
        check(planned == moved and len(moved) == 4 and raw_slot["status"] == "in_use" and "game_path" not in raw_slot and raw_slot["kind"] == "in_app"
              and '"ingame"' not in bj.read_text(encoding="utf-8") and "project_repo =" in toml and "[test_runs]" in toml
              and "[recipes.in_app]" in toml and not (old.home / "playtests").exists()
              and again.triage()["s/f8-1"]["status"] == "fixed" and again.migrate() == [],
              "migrate rewrites a home under today's names once, and finds nothing the second time")
        make_png(src / "old.png", 64, 40)
        studio.set_slot("test.concept", title="Concept", kind="image", group="Test", status="needed")
        adopted = studio.adopt("test.concept", [src / "old.png"], note="Perfect 10/10", score=10, date="2026-10-04")
        check(adopted["status"] == "approved" and (home / adopted["current"]["library"] / "old.png").exists(),
              "a master approved before the Studio is adopted with its provenance")

        # a test-run folder in the shape one project writes
        pt = tmp / "pt" / "2026-10-08-0.0.1+abc-cs-desktop"
        (pt / "f8-1").mkdir(parents=True)
        (pt / "results.json").write_text(json.dumps({"items": [{"id": "a.b", "feature": "Labels", "state": "pass"}]}), encoding="utf-8")
        (pt / "sliders.json").write_text(json.dumps({"sliders": [{"label": "Movement", "value": 3}], "text": "feels goofy"}), encoding="utf-8")
        (pt / "f8-1" / "note.txt").write_text("the hose breaks", encoding="utf-8")
        (pt / "f8-1" / "stats.json").write_text(json.dumps({"checklist_item": {"id": "a.b", "feature": "Labels"}}), encoding="utf-8")
        make_png(pt / "f8-1" / "screenshot.png", 8, 10)
        studio.config["test_runs"] = {"dirs": [str(tmp / "pt")]}
        sess = studio.test_runs()[0]
        check(sess["checklist"][0]["result"] == "pass" and sess["sliders"] == {"Movement": 3} and sess["end_note"] == "feels goofy"
              and sess["reports"][0]["screenshot"] == "screenshot.png" and sess["machine"] == "cs-desktop",
              "a test-run folder as the project writes it is read whole")
        httpd.shutdown()

        todo = studio.todo()
        check(len(todo) == 1 and todo[0]["winners"][0]["candidate"] == "a" and any("import" in s for s in todo[0]["steps"]), "the verdict is in Claude's queue with its steps")
        brief = studio.brief(batch["id"])
        check("> too soft" in brief and "> closer, but drier" in brief, "the next round's brief quotes the user exactly")
        rows = studio.import_batch(batch["id"])
        check((proj / "content/audio/shot.wav").read_bytes() == (src / "quiet_a.wav").read_bytes(), "the winner is copied into the project folder")
        check((home / rows[0]["library"] / "provenance.json").exists(), "the master and where it came from are in the library")
        try:
            studio.import_batch(batch["id"]); check(False, "a second import is refused")
        except StudioError:
            check(True, "a second import is refused")
        nxt = studio.new_batch("shot", parent=batch["id"])
        studio.carry(nxt["id"], batch["id"], "a")
        check(nxt["round"] == 2 and nxt["slot"] == "test.shot" and studio.load_batch(nxt["id"])["candidates"][0]["carried_from"].endswith("/a"), "the next round inherits the ask and carries the user's pick")
        result = studio.mark_done(batch["id"], ruling="Shot A ships; one more round for a drier one.", next_batch=nxt["id"], in_use=True)
        decisions = studio.decisions()
        check(decisions[-1]["id"] == result["decision"] and "closer, but drier" in decisions[-1]["his_words"] and "this one" in decisions[-1]["his_words"], "the ruling is logged in the user's words")
        check(studio.slot("test.shot")["status"] == "in_use" and studio.slot("test.shot")["current"]["version"] == 1, "the slot shows the shipped version")
        check(studio.todo() == [] and studio.load_batch(batch["id"])["status"] == "processed", "the queue is empty again")
        check(all(p.exists() for p in studio.write_index()), "the plain-text index is written")

        # motions baked from the project's own samples, looped beside a label and on an asset
        def at(x, y, z):  # a bone's posed model matrix, column by column, with no turn
            return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]
        make_skinned_glb(src / "puppet.glb")
        samples = {"format": bake.FORMAT, "rig": "test.puppet", "scale": 0.5, "ticks_per_second": 60, "bones": ["low", "high"],
                   "rest": [at(0, 0, 0), at(0, 0.5, 0)],
                   "clips": [{"name": "sway", "label": "sway 1 wide", "loop": True,
                              "frames": [[at(0, 0, 0), at(0, 0.5, 0)], [at(0.1, 0, 0), at(0.1, 0.5, 0.2)], [at(0, 0, 0), at(0, 0.5, 0)]]}]}
        made = bake.bake(src / "puppet.glb", samples, src / "puppet_baked.glb")
        doc, blob = bake._read_glb(src / "puppet_baked.glb")
        chan = next(c for c in doc["animations"][0]["channels"] if c["target"] == {"node": 1, "path": "translation"})
        acc = doc["accessors"][doc["animations"][0]["samplers"][chan["sampler"]]["output"]]
        moved = struct.unpack_from("<3f", blob, doc["bufferViews"][acc["bufferView"]]["byteOffset"] + 12)
        check(made["clips"][0]["seconds"] == 0.05 and acc["count"] == 4 and doc["nodes"][1]["scale"] == [0.5] * 3
              and all(abs(a - b) < 1e-6 for a, b in zip(moved, (-0.1, 0.5, -0.2))),
              "the project's samples become a clip: at the project's size, in the file's axes, the loop closed")
        try:
            bake.bake(src / "puppet.glb", dict(samples, scale=1.0), src / "wrong.glb"); check(False, "samples at the wrong scale are refused")
        except StudioError as err:
            check("at rest" in str(err), "samples at the wrong scale are refused, with the reason")
        entry = studio.set_motion("test.puppet", src / "puppet_baked.glb")
        check(entry["clips"][0]["name"] == "sway" and (home / "motions/test.puppet.glb").exists(), "a baked model is kept with its clips")
        # a script the user edits on the card: their version is the one that ships
        (src / "script.md").write_text("# Take one\n\nHello there.\n", encoding="utf-8")
        make_wav(src / "scratch.wav", -20.0, 0.2)
        script = studio.new_batch("script", kind="text", mode="rate", slot="test.script", ask="Ready to record?",
                                  look_at=["Say it out loud"], dest="content/scripts/one.md")
        studio.add_candidate(script["id"], [src / "script.md"], title="Script")
        studio.add_candidate(script["id"], [src / "scratch.wav"], title="Not text")
        studio.publish(script["id"])
        studio.save_draft(script["id"], {"candidates": {"a": {"edited": "# Take one\r\n\r\nHi.\r\n"}, "b": {"edited": "no"}}})
        draft = json.loads((studio.batch_dir(script["id"]) / "draft.json").read_text(encoding="utf-8"))["candidates"]
        check(draft == {"a": {"call": None, "score": None, "note": "", "edited": "# Take one\n\nHi.\n"}},
              "an edit on a text card is kept in the draft, and only a text candidate takes one")
        studio.submit(script["id"], {"action": "ship", "candidates": {"a": {"call": "approve", "edited": "# Take one\n\nHi.\n"}}})
        item = next(i for i in studio.todo() if i["batch"] == script["id"])
        mine = f"batches/{script['id']}/edited/a/script.md"
        check(item["winners"][0].get("edited") == mine and (home / mine).read_text(encoding="utf-8") == "# Take one\n\nHi.\n"
              and any(mine in s and "git diff" in s for s in item["steps"]),
              "the submitted edit is a file Claude reads, and todo says so with how to see the change")
        studio.import_batch(script["id"])
        check((proj / "content/scripts/one.md").read_text(encoding="utf-8") == "# Take one\n\nHi.\n"
              and (home / "library/test.script/v1/script.md").read_text(encoding="utf-8") == "# Take one\n\nHi.\n"
              and json.loads((home / "library/test.script/v1/provenance.json").read_text(encoding="utf-8"))["edited_by_user"] is True,
              "import ships the user's version, not the first draft")
        studio.mark_done(script["id"], ruling="test")

        # share links: only the files named, only from the library, only until they run out or are stopped
        from studiolib import share
        (home / "library/test.script/v1/page.html").write_text("<script>alert(1)</script>", encoding="utf-8")
        for bad in (["batches/" + script["id"] + "/files/a/script.md"], ["library/../studio.toml"], [str(src / "script.md")], []):
            try:
                share.make(studio, bad); check(False, f"sharing {bad} is refused")
            except StudioError:
                pass
        check(True, "a share never takes a file named inside a batch, a path out of the library, or nothing")
        os.environ["STUDIO_SHARE_URL"] = "https://example.test/share"
        rec = share.make(studio, ["library/test.script/v1"], title="Take one", hours="2d")
        other = share.make(studio, ["/library/test.script/v1/script.md"], hours="1h")
        names = sorted(f["name"] for f in rec["files"])
        check(names == ["page.html", "script.md"] and rec["url"] == "https://example.test/share/" + rec["token"] + "/" and len(rec["token"]) >= 43
              and rec["state"] == "live", "a folder shares its files, not its provenance, with a long random token in the link")
        sh = ThreadingHTTPServer(("127.0.0.1", 0), share.make_share_handler([tmp]))
        threading.Thread(target=sh.serve_forever, daemon=True).start()
        sbase = f"http://127.0.0.1:{sh.server_address[1]}/"
        def sget(path, method="GET", headers=None):
            req = urllib.request.Request(sbase + path, method=method, headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=10) as res:
                    return res.status, dict(res.headers), res.read()
            except urllib.error.HTTPError as err:
                return err.code, dict(err.headers), err.read()
        idx = {f["name"]: n for n, f in enumerate(rec["files"])}
        st, hd, body = sget(rec["token"] + "/")
        check(st == 200 and b"Take one" in body and b"script.md" in body and "default-src 'none'" in hd.get("Content-Security-Policy", "")
              and hd.get("Cache-Control") == "no-store", "the link opens a page of just its files, with no script allowed")
        st, hd, body = sget(f"share/{rec['token']}/{idx['script.md']}/script.md", headers={"Range": "bytes=2-5"})
        check(st == 206 and body == b"Take" and hd.get("Content-Security-Policy", "").startswith("sandbox"),
              "a shared file is served in parts (video seeks), sandboxed, with or without the /share prefix")
        st, hd, _ = sget(f"{rec['token']}/{idx['page.html']}/page.html")
        check(st == 200 and hd.get("Content-Type") == "application/octet-stream" and hd.get("Content-Disposition", "").startswith("attachment"),
              "a file that could run in the browser is only ever a download")
        refused = [sget(p)[0] for p in (f"{rec['token']}/9/x.md", f"{rec['token']}/{idx['script.md']}/other.md", "x" * 43 + "/",
                                        f"{rec['token'][:-1]}/", "", f"{rec['token']}/../studio.toml")]
        posted = sget(rec["token"] + "/", method="POST")[0]
        check(set(refused) == {404} and posted == 405, "anything else, a near token, a file not named, or a write, gets nothing")
        share.stop(studio, rec["id"])
        rec_file = home / "shares" / f"{other['id']}.json"
        old = json.loads(rec_file.read_text(encoding="utf-8")); old["expires"] = "2020-01-01T00:00:00Z"
        rec_file.write_text(json.dumps(old), encoding="utf-8")
        check(sget(rec["token"] + "/")[0] == 404 and sget(other["token"] + "/")[0] == 404
              and sorted(x["state"] for x in share.listing(studio)) == ["expired", "stopped"],
              "a stopped link and a run-out link both answer as if they never were")
        try:
            share.make(studio, ["library/test.script/v1"], hours="91d"); check(False, "a link longer than 90 days is refused")
        except StudioError:
            check(True, "every link ends: 90 days at most")

        # share links from the inbox: a batch's or one candidate's own files, under its name, and nothing else in the batch
        shot = studio.load_batch(batch["id"])
        bfolder, sid = studio.batch_dir(shot["id"]), shot["id"]
        whole = share.make(studio, [sid], hours="12h")
        one = share.make(studio, [f"batches/{sid}/b"], title="Just B")
        check([(f["path"], f["group"]) for f in whole["files"]] == [(f"batches/{sid}/files/a/quiet_a.wav", "A"), (f"batches/{sid}/files/b/quiet_b.wav", "B")]
              and whole["title"] == "Shot" and whole["batches"] == [sid] and whole["hours"] == 12
              and [(f["path"], f["group"]) for f in one["files"]] == [(f"batches/{sid}/files/b/quiet_b.wav", "B")] and one["title"] == "Just B",
              "a batch shares every candidate's own files under the candidate's name and the batch's title, and <batch>/<candidate> shares one")
        fake = studio.new_batch("lent", kind="audio", ask="x", look_at=["x"], sample=True)
        studio.add_candidate(fake["id"], [src / "quiet_a.wav"])
        (bfolder / "marks").mkdir(exist_ok=True); make_png(bfolder / "marks" / "a.png", 8, 10)
        (bfolder / "files" / "a" / "extra.txt").write_text("not listed", encoding="utf-8")
        for bad in ([f"{sid}/z"], [fake["id"]], [f"samples/{fake['id']}/a"], [f"batches/{sid}/batch.json"], [f"batches/{sid}/files/a/quiet_a.wav"],
                    [f"{sid}/../studio.toml"], [f"{sid}/.."], ["../library"], ["slots"], [f"{sid}/marks"]):
            try:
                share.make(studio, bad); check(False, f"sharing {bad} is refused")
            except StudioError:
                pass
        check(True, "a sample, a candidate not in the batch, a file named inside a batch, its record, its marks, or a path that climbs out are refused")
        wip = studio.new_batch("wip", title="Work in progress", kind="audio")
        studio.add_candidate(wip["id"], [src / "quiet_a.wav"], title="Half done")
        refused = []
        for bad in ([wip["id"]], [f"{wip['id']}/a"], [sid.upper()], [f"{sid.upper()}/a"]):
            try:
                share.make(studio, bad)
            except StudioError as e:
                refused.append(str(e))
        check(len(refused) == 4 and "not filed yet" in refused[0] and "not filed yet" in refused[1]
              and share.candidate_file(home, f"batches/{wip['id']}/files/a/quiet_a.wav") is None
              and share.candidate_file(home, f"batches/{sid.upper()}/files/a/quiet_a.wav") is None
              and share.candidate_file(home, f"batches/{sid}/files/a/QUIET_A.wav") is None
              and share.candidate_file(home, f"batches/{sid}/files/a/quiet_a.wav") is not None,
              "a batch not yet filed is never shared, and a batch or file named in the wrong case is refused, so a link never names a path the server's copy lacks")
        shutil.rmtree(studio.batch_dir(wip["id"]))
        kept = (bfolder / "batch.json").read_text(encoding="utf-8")
        raw = json.loads(kept)
        raw["candidates"][0]["files"] += [{"path": p} for p in ("files/a/../../batch.json", "verdict.json", "files/_context/x.png", "marks/a.png", "files/a/link.wav")]
        (bfolder / "batch.json").write_text(json.dumps(raw), encoding="utf-8")
        try:
            os.symlink(home / "studio.toml", bfolder / "files" / "a" / "link.wav"); linked = True
        except OSError:
            linked = False  # Windows without the right to make links: the check below runs without one
        climbed = share.make(studio, [f"{sid}/a"])
        inside = [share.candidate_file(home, f"batches/{sid}/{p}") for p in ("files/a/../../batch.json", "batch.json", "verdict.json", "marks/a.png",
                                                                             "files/a/extra.txt", "files/a/link.wav", "files/a/quiet_a.wav")]
        check([f["name"] for f in climbed["files"]] == ["quiet_a.wav"] and inside[:-1] == [None] * 6 and inside[-1] == bfolder / "files" / "a" / "quiet_a.wav"
              and share.candidate_file(home, f"samples/{fake['id']}/files/a/quiet_a.wav") is None
              and share.candidate_file(home, f"batches/{fake['id']}/files/a/quiet_a.wav") is None,
              "only a file batch.json lists in the candidate's own folder is shared: one it names that climbs out, its internals, a file it does not list"
              + (", a link" if linked else "") + " and a sample's file are left out")
        (bfolder / "batch.json").write_text(kept, encoding="utf-8")
        (bfolder / "files" / "a" / "extra.txt").unlink()
        if linked:
            (bfolder / "files" / "a" / "link.wav").unlink()
        shutil.rmtree(studio.batch_dir(fake["id"]))
        st, hd, body = sget(whole["token"] + "/")
        text = body.decode("utf-8")
        check(st == 200 and "<h1>Shot</h1>" in text and text.index("<h2>A</h2>") < text.index("quiet_a.wav") < text.index("<h2>B</h2>") < text.index("quiet_b.wav")
              and "<audio" in text and "Which shot?" not in text and "Listen" not in text and "verdict" not in text.lower() and "<script" not in text,
              "the link opens the batch's title, then each candidate's files under its name, with no ask, look-at points or verdict")
        st, hd, body = sget(f"{whole['token']}/1/quiet_b.wav")
        refused = [sget(p)[0] for p in (f"{whole['token']}/1/batch.json", f"{whole['token']}/2/quiet_b.wav", f"{one['token']}/0/quiet_a.wav")]
        check(st == 200 and body == (bfolder / "files/b/quiet_b.wav").read_bytes() and hd.get("Content-Type") == "audio/wav" and set(refused) == {404},
              "the public server hands a batch link's files and nothing beside them")
        forged = dict(whole, id="sh-0000beef", token="f" * 43, files=[{"path": f"batches/{sid}/{p}", "name": Path(p).name, "size": 1}
                                                                      for p in ("batch.json", "marks/a.png", "files/a/../../batch.json")])
        share.write_json(home / "shares" / "sh-0000beef.json", forged)
        check([sget(p)[0] for p in ("f" * 43 + "/", "f" * 43 + "/0/batch.json", "f" * 43 + "/1/a.png")] == [404, 404, 404],
              "a record that names a batch's own record or marks reaches nothing, as a stopped link")
        (home / "shares" / "sh-0000beef.json").unlink()
        (bfolder / "files/b/quiet_b.wav").rename(bfolder / "quiet_b.away")
        st, _, body = sget(whole["token"] + "/")
        half = st == 200 and b"quiet_a.wav" in body and b"<h2>B</h2>" not in body and b"One file in this link is no longer here." in body
        (bfolder / "files/a/quiet_a.wav").rename(bfolder / "quiet_a.away")
        check(half and sget(whole["token"] + "/")[0] == 404 and sget(f"{whole['token']}/0/quiet_a.wav")[0] == 404,
              "a batch deleted since: its link shows the files still there and says how many are gone, and stops once none are left")
        (bfolder / "quiet_a.away").rename(bfolder / "files/a/quiet_a.wav"); (bfolder / "quiet_b.away").rename(bfolder / "files/b/quiet_b.wav")
        lib = share.make(studio, ["library/test.script/v1/script.md"], title="Old kind")
        st, _, body = sget(lib["token"] + "/")
        check(st == 200 and "group" not in lib["files"][0] and "batches" not in lib and b"<section>" not in body and b"<h2>" not in body
              and b"<ul><li>" in body and b"no longer here" not in body, "a library link opens as before: one list of its files, no headings")
        said = tool_cli("share", "make", f"{sid}/a", "--for", "12h")
        check(said.returncode == 0 and ": 1 file(s) until " in said.stdout and tool_cli("share", "make", fake["id"]).returncode == 2,
              "the command takes <batch>/<candidate>, and refuses a sample")
        for x in share.listing(studio):
            if x["state"] == "live":
                share.stop(studio, x["id"])
        sh.shutdown(); sh.server_close(); del os.environ["STUDIO_SHARE_URL"]
        (home / "library/test.script/v1/page.html").unlink()
        # a video's parts in its own Library group: working copies the user hears, and a script they edit there
        studio.set_slot("test.vid.script", title="Script", kind="text", group="Video: test", status="in_review")
        (src / "vo.md").write_text("# Shot 1\n\nHello there.\n", encoding="utf-8")
        studio.put("test.vid.script", [src / "vo.md", src / "scratch.wav"], source="selftest")
        again = studio.put("test.vid.script", [src / "vo.md", src / "scratch.wav"])
        check(again.get("unchanged") and studio.slot("test.vid.script")["current"]["version"] == 1
              and studio.slot("test.vid.script")["current"]["working"] is True
              and studio.slot("test.vid.script")["status"] == "in_review",
              "a working copy goes in the Library once, keeps its status, and the same files again add nothing")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = httpd.server_address[1]
        httpd.RequestHandlerClass = server.make_handler(studio.home, {f"127.0.0.1:{port}"}, quiet=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        status, body = http("POST", base + "/api/slot/test.vid.script/text", {"file": "vo.md", "text": "# Shot 1\r\n\r\nHi.\r\n"})
        lib = home / "library/test.vid.script"
        check(status == 200 and body["version"] == 2 and (lib / "v2/vo.md").read_bytes() == b"# Shot 1\n\nHi.\n"
              and (lib / "v2/scratch.wav").is_file() and (lib / "v1/vo.md").read_text(encoding="utf-8") == "# Shot 1\n\nHello there.\n",
              "the user's edit in the Library is a new version with the other files carried over; the old one stays")
        status, _ = http("POST", base + "/api/slot/test.vid.script/text", {"file": "scratch.wav", "text": "no"})
        check(status == 400, "only a text file of the latest version can be edited")
        http("POST", base + "/api/slot/test.vid.script/text", {"file": "vo.md", "text": "# Shot 1\n\nHi you.\n"})
        rows = studio.library_edits()
        from studiolib import verdicts
        check(len(rows) == 1 and rows[0]["file"] == "library/test.vid.script/v3/vo.md" and rows[0]["before"] == "library/test.vid.script/v1/vo.md"
              and rows[0]["times"] == 2 and any(r["id"] == "edit:test.vid.script" for r in verdicts.waiting(home)),
              "sessions are told of the edit, from the last version they saw to the newest, and the hook hands it on")
        httpd.shutdown()
        studio.see_edits("test.vid.script")
        check(studio.library_edits() == [] and not any(r["id"].startswith("edit:") for r in verdicts.waiting(home)),
              "and it leaves the queue once a session marks it seen")
        feel = studio.new_batch("sway", kind="in_app", slot="test.sway", ask="Which sway?", look_at=["The hips"], launch="app.exe")
        studio.add_candidate(feel["id"], [], label="sway 1 wide", title="Wide", motion="test.puppet:sway")
        studio.add_candidate(feel["id"], [], label="sway 2 tight", title="Tight")
        studio.link_motion(feel["id"], "b", "test.puppet:sway")
        studio.set_slot("test.sway", title="Sway", kind="in_app", group="Test", status="placeholder", motion="test.puppet:sway")
        check(all(c["motion"] == "test.puppet:sway" for c in studio.load_batch(feel["id"])["candidates"])
              and studio.state()["motions"]["test.puppet"]["clips"][0]["name"] == "sway", "a motion is shown beside a candidate and on a slot")
        try:
            studio.link_motion(feel["id"], "a", "test.puppet:leap"); check(False, "a clip that was not baked is refused")
        except StudioError as err:
            check("sway" in str(err), "a clip that was not baked is refused, and the ones that were are named")

        # samples: made-up batches to try the page on, kept apart from everything that counts
        from studiolib import samples
        before = (len(studio.state()["batches"]), len(studio.todo()), len(studio.decisions()), len(studio.slots()))
        made = samples.build(studio, model=str(src / "puppet.glb"))
        state = studio.state()
        kinds = {b["kind"] for b in state["samples"]}
        check(len(made) == 11 and {"image", "texture", "model", "audio", "video", "text", "in_app", "question"} <= kinds
              and all(b["sample"] and b["status"] == "open" for b in state["samples"])
              and [b["id"] for b in state["samples"]][:2] == ["sample-motions", "sample-models"],
              "the samples are made, one for each thing the user can be asked to judge")
        check(state["samples_held"] and state["samples_held"][0]["id"] == "sample-held" and all(not b["id"].startswith("sample-") for b in state["held"] + state["batches"]),
              "one sample is refused by the checks, and shows as held among the samples only")
        moves = studio.load_batch("sample-motions")
        check(all(c.get("motion", "").startswith("sample.figure:") for c in moves["candidates"])
              and state["motions"]["sample.figure"].get("sample") is True, "the motion sample loops a figure with made-up clips")
        long_one = studio.load_batch("sample-tune")
        check(long_one["status"] == "open" and long_one["candidates"][0]["tempo"] == {"bpm": 120.0, "beats": 4, "first": 0.0}
              and long_one["candidates"][0]["facts"]["seconds"] == 12.0 and long_one["candidates"][0]["facts"]["peak_dbfs"] <= -20.0
              and not list((Path(__file__).resolve().parent / "samples_src").rglob("tune*")),
              "one sample is a longer sound written by script and filed with its tempo, to try marks on")
        check(studio.config["checks"]["audio"]["max_seconds"] == 3.0 and not long_one["targets"] and long_one["candidates"][0]["checks"] == []
              and Studio(home).config["checks"]["audio"]["max_seconds"] == 3.0,
              "the long sample is filed in a Studio whose sounds may run 3 s, with no target of its own, and the project's limit is as it was")
        from copy import deepcopy
        from types import SimpleNamespace
        from studiolib import store as store_mod
        shared = store_mod.DEFAULT_CONFIG["checks"]  # what a Studio with no [checks.audio] of its own reads
        kept = deepcopy(shared)
        fake = SimpleNamespace(config={"checks": shared})
        fake.publish = lambda bid: (fake.config["checks"]["audio"]["max_seconds"], shared["audio"]["max_seconds"])
        check(samples._file(fake, "x", any_length=True) == (0, 3.0) and shared == kept and fake.config["checks"] is shared,
              "and in a Studio with no limits of its own, the tool's own defaults are not touched while it is filed")
        check([c["facts"].get("fps") for c in studio.load_batch("sample-video")["candidates"]] == [30.0, 30.0, 15.0]
              and all(c["facts"]["frames"] == c["facts"]["fps"] * 4 for c in studio.load_batch("sample-video")["candidates"]),
              "filing a clip keeps its facts on it, as a sound's are kept")
        clip_look = " ".join(studio.load_batch("sample-video")["look_at"])
        check("Mark" in clip_look and "frame" in clip_look and "browser" not in clip_look,
              "the clip sample says how to mark a clip, and no longer that the controls are the browser's own")
        studio.save_draft("sample-tune", {"candidates": {"a": {"marks": {"kind": "sound", "length": 12.0, "spans": [{"id": "m1", "t0": 8, "t1": 10, "tag": "cut"}]}}}})
        studio.put_marks_picture("sample-tune", "a", (src / "tex.png").read_bytes())
        studio.put_mark_picture("sample-tune", "a", "m1", (src / "tex.png").read_bytes())
        studio.reset_sample("sample-tune")
        check(studio.load_batch("sample-tune")["status"] == "open" and not (studio.batch_dir("sample-tune") / "marks").exists(),
              "a sample started over loses the pictures of its marks with them")
        studio.save_draft("sample-pictures", {"candidates": {"a": {"call": "keep"}}})
        studio.submit("sample-pictures", {"action": "ship", "candidates": {"a": {"call": "winner", "score": 8, "note": "this one"}}})
        after = (len(studio.state()["batches"]), len(studio.todo()), len(studio.decisions()), len(studio.slots()))
        check(studio.load_batch("sample-pictures")["status"] == "submitted" and before == after,
              "a verdict on a sample is taken, and nothing that counts sees it")
        for act, what in ((lambda: studio.import_batch("sample-pictures"), "imported"), (lambda: studio.mark_done("sample-pictures"), "closed"),
                          (lambda: studio.link_motion(feel["id"], "a", "sample.figure:" + moves["candidates"][0]["motion"].split(":")[1]), "given a made-up motion")):
            try:
                act(); check(False, f"a sample is never {what}")
            except StudioError as err:
                check("sample" in str(err), f"{'a real batch is never ' if 'motion' in what else 'a sample is never '}{what}")
        studio.reset_sample("sample-pictures")
        check(studio.load_batch("sample-pictures")["status"] == "open" and not (home / "samples/sample-pictures/verdicts.log.jsonl").exists(),
              "a sample starts over with the user's marks cleared")
        try:
            studio.reset_sample(feel["id"]); check(False, "a real batch cannot be started over")
        except StudioError:
            check(True, "a real batch cannot be started over")
        try:
            studio.new_batch("sneak", kind="image", ask="x", date="sample"); check(False, "a real batch cannot take a sample's name")
        except StudioError:
            check(True, "a real batch cannot take a sample's name")
        again = samples.build(studio)
        check(all(r["note"] == "kept" for r in again), "making the samples again keeps the ones that are there")

        # the page's size is the user's, and is remembered in the home
        from studiolib import store
        store.PREFS = tmp / "ui.json"  # never the user's own
        check(studio.set_ui(scale=1.25)["scale"] == 1.25 and studio.state()["ui"]["scale"] == 1.25
              and studio.set_ui(scale=9)["scale"] == 2.0, "the page size the user sets is kept, within sane bounds")
        check(studio.set_ui(theme="light") == {"scale": 2.0, "theme": "light"} and Studio.ui()["theme"] == "light",
              "the theme the user picks is kept with it, one answer for every Studio")

        # the play bar's volume is kept with them, so every project and address on this PC plays as loud
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        httpd.RequestHandlerClass = server.make_handler(studio.home, {f"127.0.0.1:{httpd.server_address[1]}"}, quiet=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        status, body = http("POST", base + "/api/ui", {"volume": {"level": 0.4, "muted": True, "back": 0.4}})
        check(status == 200 and Studio.ui()["volume"] == {"level": 0.4, "muted": True, "back": 0.4} and Studio.ui()["theme"] == "light",
              "the volume the page sends is kept, muted or not, beside the size and theme")
        status, body = http("POST", base + "/api/ui", {"volume": {"level": 7, "muted": "yes", "back": -1}})
        check(status == 200 and body["ui"]["volume"] == {"level": 1.0, "muted": False, "back": 0.0}, "a volume past either end is kept at that end")
        status, body = http("POST", base + "/api/ui", {"volume": {"level": "loud"}})
        check(status == 400 and Studio.ui()["volume"]["level"] == 1.0, "a volume that is not a number is refused, and the kept one stays")
        status, body = http("POST", base + "/api/ui", {"theme": "dark"})
        check(status == 200 and body["ui"]["volume"]["level"] == 1.0, "setting the theme leaves the volume as it was")
        check(http("GET", base + "/api/state")[1]["ui"]["volume"]["level"] == 1.0, "the page's data carries the kept volume, for the page to start at")
        httpd.shutdown()

        # the record: a session saves the home, and the save reaches the remote
        for key, value in (("GIT_AUTHOR_NAME", "Self-test"), ("GIT_AUTHOR_EMAIL", "selftest@example.invalid"),
                           ("GIT_COMMITTER_NAME", "Self-test"), ("GIT_COMMITTER_EMAIL", "selftest@example.invalid")):
            os.environ.setdefault(key, value)
        check(studio.unsaved() is None, "a home with no history says so")
        far = tmp / "far.git"
        subprocess.run(["git", "init", "-q", "--bare", str(far)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(home), "init", "-q"], check=True, capture_output=True)
        saved = studio.save()
        check(saved["commit"] and saved["files"] > 5 and not saved["pushed"] and "no remote" in saved["note"] and studio.unsaved() == 0,
              "a save commits everything in the home, and says when there is nowhere to push")
        subprocess.run(["git", "-C", str(home), "remote", "add", "origin", str(far)], check=True, capture_output=True)
        studio.set_hand("try-save", title="Try the save", status="open")
        waiting = studio.unsaved()
        saved = studio.save("A chore for the user")
        there = subprocess.run(["git", "--git-dir", str(far), "log", "--format=%s", "-n", "1"], capture_output=True, text=True).stdout.strip()
        check(waiting and saved["pushed"] and there == "A chore for the user" and studio.save()["commit"] == "",
              "the next save pushes, under the words it was given, and a save with nothing new commits nothing")

        # a second copy for a phone: kept in step through the remote, its numbers never the same as the PC's
        from studiolib import sync
        check(sync.setup(studio) and not sync.setup(studio), "a clone is taught once how to merge the Studio's records")
        studio.save("Merge rules")
        phone = tmp / "phone"
        subprocess.run(["git", "clone", "-q", str(far), str(phone)], check=True, capture_output=True)
        (phone / "studio.local.toml").write_text('site = "p"\n', encoding="utf-8")
        copy = Studio(phone)
        sync.setup(copy)
        mine, theirs = studio.add_note("typed on the PC"), copy.add_note("typed on the phone")
        studio.answer_hand("try-save", "done", "saved")
        ruled = copy.add_decision(title="Ruled on the phone")
        first, second, third = sync.step(copy, "always"), sync.step(studio, "always"), sync.step(Studio(phone), "always")
        both = [sorted(n["id"] for n in side.notes()) for side in (Studio(home), Studio(phone))]
        check(theirs["id"] == mine["id"] + "p" and ruled["id"].endswith("p") and first["pushed"] and second["took"] and second["pushed"]
              and third["took"] and both[0] == both[1] and theirs["id"] in both[0]
              and Studio(phone).hands()[-1]["status"] == "done" and Studio(home).decisions()[-1]["id"] == ruled["id"],
              "what the phone and the PC change at once reaches both, with no number given twice")
        mine = studio.add_note("typed during a session")
        copy.add_note("and from the phone again")
        sync.step(copy, "always")
        held, saved = sync.step(studio, "never"), studio.save("A session's work")
        check(held["took"] and not held["pushed"] and saved["pushed"] and sync.step(Studio(phone), "always")["took"]
              and mine["id"] in [n["id"] for n in Studio(phone).notes()],
              "while sessions work the PC only takes the phone's commits, and a save joins both before it pushes")
        (home / "studio.local.toml").write_text('[sync]\ncommit = "quiet"\n', encoding="utf-8")
        from studiolib.store import write_json as put
        put(home / "live" / "s-busy.json", {"id": "s-busy", "state": "working", "updated": store.iso_now()})
        studio.set_hand("half-done", title="A session's unfinished row", status="open")  # the session's: not to be sent
        pc = ThreadingHTTPServer(("127.0.0.1", 0), None)
        pc.RequestHandlerClass = server.make_handler(home, {f"127.0.0.1:{pc.server_address[1]}"}, quiet=True)
        threading.Thread(target=pc.serve_forever, daemon=True).start()
        status, made = http("POST", f"http://127.0.0.1:{pc.server_address[1]}/api/note", {"text": "typed on the PC while a session works"})
        time.sleep(0.2)
        for _ in range(150):  # the sync the click started, done
            if not sync.KICKS[str(home.resolve())].locked():
                break
            time.sleep(0.1)
        sync.step(Studio(phone), "always")
        sent = [n["id"] for n in Studio(phone).notes()]
        check(status == 200 and made["note"]["id"] in sent and not any(x.get("id") == "half-done" for x in Studio(phone).hands())
              and "overview/hands.json" in subprocess.run(["git", "-C", str(home), "status", "--porcelain"], capture_output=True, text=True).stdout,
              "a note typed on the PC page reaches the phone at once while a session works, and the session's own changes wait for its save")
        lent = studio.new_batch("lend", title="Lend", kind="audio", ask="Which?", look_at=["x"])
        studio.add_candidate(lent["id"], [src / "quiet_b.wav"], title="Soft")
        studio.add_candidate(lent["id"], [src / "quiet_a.wav"], title="Softer")
        check(studio.publish(lent["id"])["ready"], "the batch to lend is filed, as only a filed batch is shared")
        studio.set_hand("half-done-2", title="Another unfinished row of the session's", status="open")
        bad_status, bad = http("POST", f"http://127.0.0.1:{pc.server_address[1]}/api/share", {"files": ["sample-sounds"]})
        status, made = http("POST", f"http://127.0.0.1:{pc.server_address[1]}/api/share", {"files": [lent["id"] + "/a"], "title": "For a friend", "time": "12h"})
        time.sleep(0.2)
        for _ in range(150):
            if not sync.KICKS[str(home.resolve())].locked():
                break
            time.sleep(0.1)
        sync.step(Studio(phone), "always")
        from studiolib import share as shares
        far_side = ThreadingHTTPServer(("127.0.0.1", 0), shares.make_share_handler([phone]))
        threading.Thread(target=far_side.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{far_side.server_address[1]}/{made['share']['token']}/0/quiet_b.wav", timeout=10) as res:
                there = res.status == 200 and res.read() == (src / "quiet_b.wav").read_bytes()
        except urllib.error.HTTPError:
            there = False
        far_side.shutdown(); far_side.server_close()
        check(bad_status == 400 and "sample" in bad.get("error", "") and status == 200 and made["share"]["files"][0]["group"] == "Soft"
              and made["share"]["hours"] == 12 and (phone / f"batches/{lent['id']}/files/a/quiet_b.wav").is_file()
              and (phone / f"batches/{lent['id']}/batch.json").is_file() and there
              and not any(x.get("id") == "half-done-2" for x in Studio(phone).hands()),
              "a candidate shared from the PC page while a session works takes its file and its batch's record to the phone, where the link opens it")
        shares.stop(studio, made["share"]["id"])
        (home / "live" / "s-busy.json").unlink()
        pc.shutdown(); pc.server_close()

        import hook
        lone = Studio.init(tmp / "lone", "Lone")
        (lone.home / "studio.local.toml").write_text("[sync]\nevery_seconds = 0\n", encoding="utf-8")
        hook.fetch(str(lone.home), {"hook_event_name": "UserPromptSubmit"})
        started = (lone.home / "live" / "sync.started").stat().st_mtime
        for _ in range(100):
            if (lone.home / "live" / "sync.json").exists():
                break
            time.sleep(0.1)
        hook.fetch(str(lone.home), {"hook_event_name": "Stop"})
        check("no git remote" in json.loads((lone.home / "live" / "sync.json").read_text(encoding="utf-8"))["error"]
              and (lone.home / "live" / "sync.started").stat().st_mtime == started,
              "a session's prompt starts a sync on its own, at most once a minute, without waiting for it")

        # every Studio behind one address, for a server: a menu, and each Studio under its own name
        from http.client import HTTPConnection
        both = server.studios_by_name([home, lone.home])
        menu = ThreadingHTTPServer(("127.0.0.1", 0), None)
        mport = menu.server_address[1]
        menu.RequestHandlerClass = server.menu_handler(both, {f"127.0.0.1:{mport}"})
        threading.Thread(target=menu.serve_forever, daemon=True).start()
        conn = HTTPConnection("127.0.0.1", mport, timeout=20)

        def ask(method: str, path: str, body=None):
            conn.request(method, path, body=json.dumps(body) if body is not None else None,
                         headers={"Content-Type": "application/json"} if body is not None else {})
            res = conn.getresponse()
            raw = res.read()
            return res.status, (json.loads(raw) if res.headers.get("Content-Type", "").startswith("application/json") else raw)

        status, rows = ask("GET", "/api/hub")
        first, second = ask("GET", "/self-test/api/state")[1], ask("GET", "/lone/api/state")[1]
        page, missing = ask("GET", "/lone/")[1], ask("GET", "/nowhere/")[0]
        status_note, made = ask("POST", "/lone/api/note", {"text": "typed on the phone"})
        check(sorted(r["url"] for r in rows["studios"]) == ["lone/", "self-test/"] and rows["served"]
              and first["project"] == "Self-test" and second["project"] == "Lone" and second["hub"] == "../"
              and b"app.js" in page and missing == 404 and status_note == 200 and lone.note(made["note"]["id"])["text"] == "typed on the phone",
              "one address serves a menu and each Studio under its name, one after another on the same connection")
        conn.close()
        menu.shutdown()

        # the Studio app: a menu of every project's Studio, each started only when the user picks it
        import socket
        from studiolib import app
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        menu = tmp / "menu.json"
        setup.register("Self-test", home, tmp / "nowhere", free, menu)
        setup.register("Gone", tmp / "gone", tmp / "nowhere", free + 1, menu)
        hub = app.Hub(registry=menu, port=0)
        try:
            listed = app._get(hub.url + "api/hub")
            rows = {r["name"]: r for r in listed["studios"]}
            check(listed["studio_hub"] and rows["Self-test"]["running"] is False and "judge" in rows["Self-test"]
                  and rows["Gone"]["missing"], "the app's menu lists every Studio, and says which folder is gone")
            req = urllib.request.Request(hub.url + "api/open", data=json.dumps({"home": str(home)}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            url = json.loads(urllib.request.urlopen(req, timeout=5).read())["url"]
            page = app._get(url + "api/state")
            check(page["hub"] == hub.url and Path(page["home"]) == home.resolve() and hub.open(str(home)) == url
                  and app._get(hub.url + "api/hub")["studios"][0]["running"], "a Studio starts when it is picked, and knows the way back to the menu")

            # desktop notifications: what lands in Needs you in a Studio opened in the app is handed out once, only when on
            def ui_post(base, body):
                req = urllib.request.Request(base + "api/ui", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
                try:
                    return json.loads(urllib.request.urlopen(req, timeout=5).read())
                except urllib.error.HTTPError as err:
                    return json.loads(err.read())

            def page_post(base, path, body):
                req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
                return json.loads(urllib.request.urlopen(req, timeout=5).read())
            check(page["notify"] is True and app._get(url + "api/notices?can=1") == {"on": False, "notices": []}
                  and app._get(hub.url + "api/notices?can=1") == {"on": False, "notices": []},
                  "a Studio opened in the app may notify, and nothing is handed out while notifications are off")
            studio.set_hand("before", title="There before notifications were on", kind="info")
            turned = ui_post(url, {"notify": True})
            check(turned["ui"]["notify"] is True and turned["ui"]["notify_since"] and Studio.ui()["notify"] is True
                  and "error" in ui_post(url, {"notify": "yes"}),
                  "the Notify switch is kept in the PC-wide prefs, and anything but true or false is refused")
            check(app._get(url + "api/notices?can=1")["notices"] == [], "what already waits when notifications go on is not new")
            studio.set_hand("try-it", title="Try the new build", kind="play")
            held = app._get(url + "api/notices")["notices"]
            got = app._get(hub.url + "api/notices?can=1")["notices"]
            again = app._get(url + "api/notices?can=1")["notices"] + app._get(hub.url + "api/notices?can=1")["notices"]
            check(held == [] and len(got) == 1 and got[0]["key"] == "ask:try-it" and got[0]["title"] == "Try the new build"
                  and got[0]["what"] == "To try" and got[0]["project"] == "Self-test" and got[0]["url"] == url + "#ask.try-it" and again == [],
                  "a new ask waits for a page that can show it, goes to whichever page of the window asks first, once, and opens that ask")
            make_png(src / "sky_a.png", 256, 120); make_png(src / "sky_b.png", 256, 60)
            nb = studio.new_batch("notify", title="Pick a sky", kind="image", ask="Which sky?", look_at=["The sky"])
            studio.add_candidate(nb["id"], [src / "sky_a.png"], title="A")
            studio.add_candidate(nb["id"], [src / "sky_b.png"], title="B")
            studio.publish(nb["id"])
            nid = studio.add_note("make the sky darker")["id"]
            studio.sort_note(nid, "directive", reading="Make the sky a darker blue.")
            got = {n["key"]: n for n in app._get(url + "api/notices?can=1")["notices"]}
            check(set(got) == {"batch:" + nb["id"], "note:" + nid} and got["batch:" + nb["id"]]["url"] == url + "#b." + nb["id"]
                  and got["batch:" + nb["id"]]["what"] == "To judge" and got["note:" + nid]["title"] == "Make the sky a darker blue."
                  and got["note:" + nid]["what"] == "A note to confirm" and got["note:" + nid]["url"] == url + "#note." + nid,
                  "a batch to judge and a note waiting on the user are handed out too, each with its title and the page it opens")
            cands = {c["id"]: {"call": "winner" if i == 0 else "reject"} for i, c in enumerate(studio.load_batch(nb["id"])["candidates"])}
            studio.submit(nb["id"], {"schema": 1, "batch": nb["id"], "action": "ship", "candidates": cands})
            studio.answer_hand("try-it", "done")
            left = app._get(url + "api/notices?can=1")["notices"]
            page_post(url, "api/batch/" + nb["id"] + "/reopen", {})
            page_post(url, "api/hand", {"id": "try-it", "action": "undo"})
            check(left == [] and studio.load_batch(nb["id"])["status"] in ("open", "draft") and next(x for x in studio.hands() if x["id"] == "try-it")["status"] == "open"
                  and app._get(url + "api/notices?can=1")["notices"] == [] and app._get(hub.url + "api/notices?can=1")["notices"] == [],
                  "what the user puts back in Needs you themselves, by Change my verdict or Undo, is not new")
            ui_post(hub.url, {"notify": False})
            off = Studio.ui()["notify"]
            studio.set_hand("while-off", title="Filed while notifications were off")
            time.sleep(1.1)  # the switch going on again is kept to the second
            ui_post(hub.url, {"notify": True})
            check(off is False and app._get(url + "api/notices?can=1")["notices"] == [] and Studio.ui()["notify"] is True,
                  "the menu's switch is the same one, and what landed while it was off is not handed out when it goes back on")
            studio.set_hand("held", title="Filed while the page in front could not show it")
            waiting = app._get(url + "api/notices")["notices"]
            ui_post(url, {"notify": False})
            time.sleep(1.1)
            ui_post(url, {"notify": True})
            check(waiting == [] and app._get(url + "api/notices?can=1")["notices"] == [],
                  "something kept for a page that can show it is dropped when the switch goes off and on again")
            studio.answer_hand("try-it", "done")
            gone = app._get(url + "api/notices?can=1")["notices"]
            studio.answer_hand("try-it", "reopen")
            back = app._get(hub.url + "api/notices?can=1")["notices"]
            check(gone == [] and [n["key"] for n in back] == ["ask:try-it"], "an ask that leaves Needs you and comes back is new again")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                cport = probe.getsockname()[1]
            cmd = Studio.init(tmp / "cmd-studio", "Cmd", str(tmp / "nowhere"))
            cmd_watch = server.Watch()
            cmd_watch.add(cmd.home)
            cmd_srv = ThreadingHTTPServer(("127.0.0.1", cport), server.make_handler(cmd.home, {f"127.0.0.1:{cport}"}, quiet=True, watch=cmd_watch))
            threading.Thread(target=cmd_srv.serve_forever, daemon=True).start()
            setup.register("Cmd", cmd.home, tmp / "nowhere", cport, menu)
            curl = hub.open(str(cmd.home))
            app._get(curl + "api/notices?can=1"); app._get(hub.url + "api/notices?can=1")
            cmd.set_hand("build", title="Run the build", kind="play")
            not_yet = app._get(hub.url + "api/notices")["notices"]
            menu_got = app._get(hub.url + "api/notices?can=1")["notices"]
            own_got = app._get(curl + "api/notices?can=1")["notices"]
            check(curl == f"http://127.0.0.1:{cport}/" and not_yet == [] and [n["key"] for n in menu_got] == ["ask:build"]
                  and menu_got[0]["url"] == curl + "#ask.build" and own_got == [],
                  "a Studio already running from studio.cmd is asked by the menu, not watched twice, so what lands there is handed out once")
            cmd_srv.shutdown(); cmd_srv.server_close()
            menu.write_text(json.dumps({"studios": [r for r in setup.studios(menu) if r["name"] != "Cmd"]}), encoding="utf-8")
            phone_watch = server.Watch()
            phone_watch.add(tmp / "site-copy")
            phone_srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
            phone_srv.RequestHandlerClass = server.make_handler(tmp / "site-copy", {f"127.0.0.1:{phone_srv.server_address[1]}"}, quiet=True, watch=phone_watch)
            threading.Thread(target=phone_srv.serve_forever, daemon=True).start()
            pbase = f"http://127.0.0.1:{phone_srv.server_address[1]}/"
            check(app._get(pbase + "api/state")["notify"] is False and app._get(pbase + "api/notices?can=1") == {"on": False, "notices": []},
                  "the phone copy shows no switch and sends nothing, even with notifications on")
            phone_srv.shutdown(); phone_srv.server_close()
            ui_post(url, {"notify": False})
            try:
                hub.open(str(tmp / "gone")); check(False, "a Studio whose folder is gone is not started")
            except StudioError:
                check(True, "a Studio whose folder is gone is not started")

            # the user's own notes under the menu: pages to read, a box that only adds to the end of one
            os.environ["STUDIO_HUB"] = str(tmp / "hub.toml")
            check(app._get(hub.url + "api/vault") == {"vault": False}, "with no notes folder set, the menu shows only the projects")
            notes = tmp / "notes"; notes.mkdir()
            (notes / "Now.md").write_text("# Now\n- [ ] one\n- [x] two\n", encoding="utf-8")
            (notes / "Dump.md").write_bytes(b"\r\n---\r\n")
            (tmp / "hub.toml").write_text(f'[vault]\nfolder = "{notes.as_posix()}"\nshow = ["Now.md", "Gone.md", "../outside.md"]\ndump = "Dump.md"\n', encoding="utf-8")
            seen = app._get(hub.url + "api/vault")
            check(seen.get("vault") is False and "outside" in seen.get("error", ""), "a page outside the notes folder is refused")
            (tmp / "hub.toml").write_text(f'[vault]\nfolder = "{notes.as_posix()}"\nshow = ["Now.md", "Gone.md"]\ndump = "Dump.md"\n', encoding="utf-8")
            seen = app._get(hub.url + "api/vault")
            check(seen["pages"][0]["text"].startswith("# Now") and seen["pages"][1]["missing"] and seen["dump"] == "Dump",
                  "the menu shows the notes pages named, and says which is not there")

            def dump(text):
                req = urllib.request.Request(hub.url + "api/dump", data=json.dumps({"text": text}).encode(),
                                             headers={"Content-Type": "application/json"}, method="POST")
                try:
                    return urllib.request.urlopen(req, timeout=5).status
                except urllib.error.HTTPError as err:
                    return err.code
            check(dump("first thought") == 200 and dump("second\nthought") == 200 and dump("   ") == 400
                  and (notes / "Dump.md").read_bytes() == b"\r\n---\r\n\r\nfirst thought\r\n\r\nsecond\r\nthought\r\n",
                  "the box adds what is typed to the end of the dump page, as typed, in the page's own line endings")

            # the idea loop: from the menu, a loose idea becomes a project folder and a Studio, opened on its Talk page
            projects = tmp / "projects"; projects.mkdir()
            import socket
            with socket.socket() as probe:  # a port nothing holds: a Studio of the user's own may be open on the usual first one
                probe.bind(("127.0.0.1", 0))
                setup.FIRST_PORT = probe.getsockname()[1]
            with open(tmp / "hub.toml", "a", encoding="utf-8") as fh:
                fh.write(f'\n[ideas]\nfolder = "{projects.as_posix()}"\nwhen_done = "add it to the list"\n')
            req = urllib.request.Request(hub.url + "api/idea", data=json.dumps({"name": "Kite Lab", "text": "a kite that films the yard"}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            made = json.loads(urllib.request.urlopen(req, timeout=20).read())
            kite = projects / "Kite Lab"
            check(made["url"].endswith("#talk") and (kite / "docs" / "idea.md").is_file() and (projects / "Kite Lab-studio" / "studio.toml").is_file()
                  and any(r["name"] == "Kite Lab" for r in app._get(hub.url + "api/hub")["studios"]),
                  "an idea started from the menu gets its own project folder and Studio, and opens on its Talk page")
            kurl = made["url"].split("#")[0]
            os.environ["STUDIO_CLAUDE"] = json.dumps([sys.executable, str(Path(__file__).resolve().parent / "selftest_claude.py")])
            seen = app._get(kurl + "api/idea")
            check(seen["stage"] == "idea" and seen["first"] == "a kite that films the yard" and "films the yard" in seen["text"],
                  "the idea's Studio knows it is an idea, and shows docs/idea.md")
            req = urllib.request.Request(kurl + "api/idea", data=json.dumps({"action": "start", "text": seen["first"]}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            ikey = json.loads(urllib.request.urlopen(req, timeout=20).read())["key"]
            end = time.time() + 10
            while time.time() < end and not (app._get(kurl + f"api/talk/{ikey}") or {}).get("asks"):
                time.sleep(0.1)
            loop = app._get(kurl + f"api/talk/{ikey}")
            order = app._get(hub.url + "api/hub")["studios"]
            check([r["name"] for r in order] == ["Kite Lab", "Self-test", "Gone"] and order[0]["talk"]["asks"] == 1 and order[0]["touched"] > 0,
                  "the menu puts the project worked on last at the top, and says when its Talk page asks something")
            check(app._get(kurl + "api/idea")["stage"] == "loop" and any(e["text"] == "The idea, as I put it: a kite that films the yard" for e in loop["events"]),
                  "starting the loop hands the session the idea in the user's words")
            req = urllib.request.Request(kurl + f"api/talk/{loop['key']}", data=json.dumps({"action": "allow", "ask": loop["asks"][0]["id"]}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10)
            req = urllib.request.Request(kurl + "api/idea", data=json.dumps({"action": "done"}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=20)
            told = [e["text"] for e in app._get(kurl + f"api/talk/{loop['key']}")["events"] if e["kind"] == "you"]
            check(app._get(kurl + "api/idea")["stage"] == "done" and told[-1].startswith("They said the idea is done") and told[-1].endswith("Also: add it to the list"),
                  "done tells the session to write the spec and set the project up, with the user's own last step")
            del os.environ["STUDIO_CLAUDE"]
            del os.environ["STUDIO_HUB"]
        finally:
            hub.close()
        check(app._get(url + "api/state") is None and app._get(hub.url + "api/hub") is None, "closing the app stops every Studio it started")

        # a Studio for another project: a home of its own, a free port, the skill in its repo
        other = tmp / "Other Project"
        other.mkdir()
        reg = tmp / "studios.json"
        setup.register("First", tmp / "first", tmp / "first-repo", setup.FIRST_PORT, reg)
        made = setup.create(other, registry=reg, git=False)
        new = Studio(made["home"])
        skill = (other / ".claude/skills/studio/SKILL.md").read_text(encoding="utf-8")
        check(new.config["project"] == "Other Project" and new.repo_root() == other.resolve() and made["port"] == setup.FIRST_PORT + 1
              and made["home"] in skill and "{{" not in skill and (Path(made["home"]) / "studio.cmd").exists()
              and new.state()["has_test_runs"] is False and len(setup.studios(reg)) == 2
              and len(new.state()["samples"]) == 10 and not new.state()["batches"],
              "a Studio is made for another project, with its own home, port, launcher and skill")
        made_skill = setup.install_create_skill(tmp / "skills").read_text(encoding="utf-8")
        check(str(setup.KIT) in made_skill and "{{" not in made_skill, "the setup skill is written with this tool's own path in it")
        try:
            setup.create(other, registry=reg, git=False); check(False, "a second Studio for the same project is refused")
        except StudioError:
            check(True, "a second Studio for the same project is refused")

        # Codex: the same skill where Codex looks for skills, its own hooks file, and the same hook told whose it is
        cproj = tmp / "codex-proj"
        cproj.mkdir()
        cmade = setup.create(cproj, registry=reg, git=False, agents=["codex", "claude"])
        cskill = (cproj / ".agents/skills/studio/SKILL.md").read_text(encoding="utf-8")
        check(cskill == (cproj / ".claude/skills/studio/SKILL.md").read_text(encoding="utf-8") and cmade["docs"] == ["AGENTS.md", "CLAUDE.md"]
              and len(setup.skill_copies(cproj)) == 2 and cmade["home"] in cskill and "Claude Code" not in cskill,
              "a project Codex works in gets the same skill where Codex looks for skills, and the skill names no one agent")
        csetup = setup.install_create_skill(tmp / "agents-skills", who="codex").read_text(encoding="utf-8")
        check("--for codex" in csetup and "`AGENTS.md`" in csetup and ".agents/skills/studio" in csetup and "/hooks" in csetup
              and "{{" not in csetup and "--for" not in made_skill and "`CLAUDE.md`" in made_skill,
              "the setup skill for Codex names Codex's own files and commands, and Claude Code's is as it was")
        chooks = setup.codex_hooks()
        chooks.parent.mkdir(parents=True)
        ctheirs = {"hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": 'py -3.11 "C:/mine/scripts/codex/hook.py"', "timeout": 10}]}]}}
        chooks.write_text(json.dumps(ctheirs), encoding="utf-8")
        setup.install_hooks(who="codex"); setup.install_hooks(who="codex")
        cdata = json.loads(chooks.read_text(encoding="utf-8"))
        cstop = cdata["hooks"]["Stop"]
        check(set(setup.hooks_installed(who="codex")) == set(setup.CODEX_EVENTS) and len(cstop) == 2 and cstop[0] == ctheirs["hooks"]["Stop"][0]
              and cstop[1]["hooks"][0]["command"].endswith("--agent codex") and cstop[1]["hooks"][0]["additionalContextLimit"] == 0
              and "async" not in cstop[1]["hooks"][0] and cdata["hooks"]["PreToolUse"][0]["hooks"][0]["async"] is True
              and cdata["hooks"]["SessionEnd"][0]["hooks"][0]["timeout"] == 3 and setup.hooks_hand_over(who="codex")
              and "codex" in setup.hooks_on() and not setup.claude_settings().exists(),
              "Codex's hooks go into its own file beside the user's own, once, and Claude Code's settings are not touched")
        setup.install_hooks(remove=True, who="codex")
        check(json.loads(chooks.read_text(encoding="utf-8")) == ctheirs, "removing them puts Codex's file back")

        cenv = dict(os.environ, STUDIO_REGISTRY=str(reg), LOCALAPPDATA=str(tmp / "local-codex"))

        def codex(**event) -> dict:
            run = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "hook.py"), "--agent", "codex"],
                                 input=json.dumps(event).encode(), capture_output=True, env=cenv)
            assert run.returncode == 0 and not run.stderr, run
            return json.loads(run.stdout) if run.stdout else {}

        cstudio = Studio(cmade["home"])
        codex(session_id="c-1", cwd=str(cproj), hook_event_name="SessionStart", source="startup", model="gpt")
        codex(session_id="c-1", cwd=str(cproj), hook_event_name="UserPromptSubmit", turn_id="t1", prompt="Widen the door")
        codex(session_id="c-1", cwd=str(cproj), hook_event_name="PreToolUse", turn_id="t1", tool_name="apply_patch",
              tool_input={"command": "*** Begin Patch\n*** Update File: content/door.scene\n@@\n-a\n+b\n*** End Patch"})
        one = board.sessions(cstudio)[0]
        check(one["agent"] == "codex" and one["state"] == "working" and one["doing"] == "Editing door.scene" and one["prompt"] == "Widen the door",
              "a Codex session shows on the Overview as Codex's, with what it is editing")
        cnote = cstudio.add_note("door width to 0.9")["id"]
        between = codex(session_id="c-1", cwd=str(cproj), hook_event_name="PostToolUse", turn_id="t1", tool_name="Bash", tool_input={"command": "ls"})
        ended = codex(session_id="c-1", cwd=str(cproj), hook_event_name="Stop", turn_id="t1", stop_hook_active=False, last_assistant_message="Done.")
        again = codex(session_id="c-1", cwd=str(cproj), hook_event_name="Stop", turn_id="t1", stop_hook_active=True, last_assistant_message="Done.")
        check(between == {} and ended.get("decision") == "block" and cnote in ended.get("reason", "") and "> door width to 0.9" in ended.get("reason", "")
              and "hookSpecificOutput" not in ended and again == {},
              "a note reaches a Codex session as its turn ends, in the shape Codex carries on from, and only once")
        codex(session_id="c-1", cwd=str(cproj), hook_event_name="PreToolUse", turn_id="t2", tool_name="Bash", tool_input={"command": ["bash", "-lc", "ls"]})
        busy = board.sessions(cstudio)[0]
        codex(session_id="c-1", cwd=str(cproj), hook_event_name="Interrupt", turn_id="t2")
        check(busy["doing"] == "bash -lc ls" and board.sessions(cstudio)[0]["state"] == "waiting",
              "a Codex turn the user stops goes back to waiting")
    print("\nAll good." if not FAILED else f"\n{len(FAILED)} step(s) failed.")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
