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
import struct
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import wave
import zlib
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from studiolib import bake, server, setup  # noqa: E402
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
        home, game, src = tmp / "studio", tmp / "game", tmp / "src"
        game.mkdir(); src.mkdir()
        studio = Studio.init(home, "Self-test", str(game))
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
            check(b"app.js" in res.read(), "the page itself is served")
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

        # the overview: the road, the build in hand, what only the user can do
        studio.set_milestone("M1", name="One room", status="current")
        studio.set_now(headline="Built.", next=["The user's picks"])
        studio.set_hand("walk", title="Walk the build", status="open")
        status, state = http("GET", base + "/api/state")
        ov = state["overview"]
        check(ov["milestones"][0]["status"] == "current" and ov["now"]["next"] == ["The user's picks"] and ov["hands"][0]["id"] == "walk",
              "the overview holds the road, the build in hand and what only the user can do")
        status, _ = http("POST", base + "/api/hand", {"id": "walk", "action": "done", "note": "walked it"})
        check(status == 200 and studio.unseen_hands()[0]["his_note"] == "walked it", "what the user marks done on the page reaches Claude's queue")
        studio.see_hand("walk")
        check(studio.unseen_hands() == [], "and leaves it once read")

        # an asset the user can open: what the game holds, by file, folder or glob
        (game / "content/audio/core").mkdir(parents=True); (game / "content/audio/tape").mkdir(parents=True)
        make_wav(game / "content/audio/core/step_1.wav", -24.0, 0.2); make_wav(game / "content/audio/tape/step_1.wav", -24.0, 0.2)
        (game / "content/audio/core/step.toml").write_text("kind = 'audio.sfx'", encoding="utf-8")
        studio.set_slot("test.step", title="Step", kind="audio", group="Test", status="placeholder", game_path="content/audio/*/step_*.wav")
        status, state = http("GET", base + "/api/state")
        files = next(x for x in state["slots"] if x["id"] == "test.step")["files"]
        check([f["url"] for f in files] == ["/game/content/audio/core/step_1.wav", "/game/content/audio/tape/step_1.wav"],
              "a slot lists the game's own files for it")
        with urllib.request.urlopen(base + files[0]["url"]) as res:
            check(res.headers["Content-Type"] == "audio/wav", "a game file is served to the Library")
        status, _ = http("GET", base + "/game/content/audio/core/step.toml")
        check(status == 404, "a game file that is not a picture, model or sound is refused")
        make_png(src / "old.png", 64, 40)
        studio.set_slot("test.concept", title="Concept", kind="image", group="Test", status="needed")
        adopted = studio.adopt("test.concept", [src / "old.png"], note="Perfect 10/10", score=10, date="2026-10-04")
        check(adopted["status"] == "approved" and (home / adopted["current"]["library"] / "old.png").exists(),
              "a master approved before the Studio is adopted with its provenance")

        # a playtest folder in the shape the game writes
        pt = tmp / "pt" / "2026-10-08-0.0.1+abc-cs-desktop"
        (pt / "f8-1").mkdir(parents=True)
        (pt / "results.json").write_text(json.dumps({"items": [{"id": "a.b", "feature": "Labels", "state": "pass"}]}), encoding="utf-8")
        (pt / "sliders.json").write_text(json.dumps({"sliders": [{"label": "Movement", "value": 3}], "text": "feels goofy"}), encoding="utf-8")
        (pt / "f8-1" / "note.txt").write_text("the hose breaks", encoding="utf-8")
        (pt / "f8-1" / "stats.json").write_text(json.dumps({"checklist_item": {"id": "a.b", "feature": "Labels"}}), encoding="utf-8")
        make_png(pt / "f8-1" / "screenshot.png", 8, 10)
        studio.config["playtests"] = {"dirs": [str(tmp / "pt")]}
        sess = studio.playtests()[0]
        check(sess["checklist"][0]["result"] == "pass" and sess["sliders"] == {"Movement": 3} and sess["end_note"] == "feels goofy"
              and sess["reports"][0]["screenshot"] == "screenshot.png" and sess["machine"] == "cs-desktop",
              "a playtest folder as the game writes it is read whole")
        httpd.shutdown()

        todo = studio.todo()
        check(len(todo) == 1 and todo[0]["winners"][0]["candidate"] == "a" and any("import" in s for s in todo[0]["steps"]), "the verdict is in Claude's queue with its steps")
        brief = studio.brief(batch["id"])
        check("> too soft" in brief and "> closer, but drier" in brief, "the next round's brief quotes the user exactly")
        rows = studio.import_batch(batch["id"])
        check((game / "content/audio/shot.wav").read_bytes() == (src / "quiet_a.wav").read_bytes(), "the winner is copied into the game repo")
        check((home / rows[0]["library"] / "provenance.json").exists(), "the master and where it came from are in the library")
        try:
            studio.import_batch(batch["id"]); check(False, "a second import is refused")
        except StudioError:
            check(True, "a second import is refused")
        nxt = studio.new_batch("shot", parent=batch["id"])
        studio.carry(nxt["id"], batch["id"], "a")
        check(nxt["round"] == 2 and nxt["slot"] == "test.shot" and studio.load_batch(nxt["id"])["candidates"][0]["carried_from"].endswith("/a"), "the next round inherits the ask and carries the user's pick")
        result = studio.mark_done(batch["id"], ruling="Shot A ships; one more round for a drier one.", next_batch=nxt["id"], in_game=True)
        decisions = studio.decisions()
        check(decisions[-1]["id"] == result["decision"] and "closer, but drier" in decisions[-1]["his_words"] and "this one" in decisions[-1]["his_words"], "the ruling is logged in the user's words")
        check(studio.slot("test.shot")["status"] == "in_game" and studio.slot("test.shot")["current"]["version"] == 1, "the slot shows the shipped version")
        check(studio.todo() == [] and studio.load_batch(batch["id"])["status"] == "processed", "the queue is empty again")
        check(all(p.exists() for p in studio.write_index()), "the plain-text index is written")

        # motions baked from the game's own samples, looped beside a label and on an asset
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
              "the game's samples become a clip: at the game's size, in the file's axes, the loop closed")
        try:
            bake.bake(src / "puppet.glb", dict(samples, scale=1.0), src / "wrong.glb"); check(False, "samples at the wrong scale are refused")
        except StudioError as err:
            check("at rest" in str(err), "samples at the wrong scale are refused, with the reason")
        entry = studio.set_motion("test.puppet", src / "puppet_baked.glb")
        check(entry["clips"][0]["name"] == "sway" and (home / "motions/test.puppet.glb").exists(), "a baked model is kept with its clips")
        feel = studio.new_batch("sway", kind="ingame", slot="test.sway", ask="Which sway?", look_at=["The hips"], launch="game.exe")
        studio.add_candidate(feel["id"], [], label="sway 1 wide", title="Wide", motion="test.puppet:sway")
        studio.add_candidate(feel["id"], [], label="sway 2 tight", title="Tight")
        studio.link_motion(feel["id"], "b", "test.puppet:sway")
        studio.set_slot("test.sway", title="Sway", kind="ingame", group="Test", status="placeholder", motion="test.puppet:sway")
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
        check(len(made) == 10 and {"image", "texture", "model", "audio", "video", "text", "ingame", "question"} <= kinds
              and all(b["sample"] and b["status"] == "open" for b in state["samples"])
              and [b["id"] for b in state["samples"]][:2] == ["sample-motions", "sample-models"],
              "the samples are made, one for each thing the user can be asked to judge")
        check(state["samples_held"] and state["samples_held"][0]["id"] == "sample-held" and all(not b["id"].startswith("sample-") for b in state["held"] + state["batches"]),
              "one sample is refused by the checks, and shows as held among the samples only")
        moves = studio.load_batch("sample-motions")
        check(all(c.get("motion", "").startswith("sample.figure:") for c in moves["candidates"])
              and state["motions"]["sample.figure"].get("sample") is True, "the motion sample loops a figure with made-up clips")
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

        # the record: a session saves the home, and the save reaches the remote
        import os
        import subprocess
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
            try:
                hub.open(str(tmp / "gone")); check(False, "a Studio whose folder is gone is not started")
            except StudioError:
                check(True, "a Studio whose folder is gone is not started")
        finally:
            hub.close()
        check(app._get(url + "api/state") is None and app._get(hub.url + "api/hub") is None, "closing the app stops every Studio it started")

        # a Studio for another project: a home of its own, a free port, the skill in its repo
        other = tmp / "Other Game"
        other.mkdir()
        reg = tmp / "studios.json"
        setup.register("First", tmp / "first", tmp / "first-repo", setup.FIRST_PORT, reg)
        made = setup.create(other, registry=reg, git=False)
        new = Studio(made["home"])
        skill = (other / ".claude/skills/studio/SKILL.md").read_text(encoding="utf-8")
        check(new.config["project"] == "Other Game" and new.game_root() == other.resolve() and made["port"] == setup.FIRST_PORT + 1
              and made["home"] in skill and "{{" not in skill and (Path(made["home"]) / "studio.cmd").exists()
              and new.state()["has_playtests"] is False and len(setup.studios(reg)) == 2
              and len(new.state()["samples"]) == 9 and not new.state()["batches"],
              "a Studio is made for another project, with its own home, port, launcher and skill")
        made_skill = setup.install_create_skill(tmp / "skills").read_text(encoding="utf-8")
        check(str(setup.KIT) in made_skill and "{{" not in made_skill, "the setup skill is written with this tool's own path in it")
        try:
            setup.create(other, registry=reg, git=False); check(False, "a second Studio for the same project is refused")
        except StudioError:
            check(True, "a second Studio for the same project is refused")
    print("\nAll good." if not FAILED else f"\n{len(FAILED)} step(s) failed.")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
