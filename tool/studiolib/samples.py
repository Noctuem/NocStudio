"""Made-up batches for trying the page on: one for each thing the user can be asked to judge.

They live under samples/ in the studio home, apart from the real batches. The user opens them from the
Inbox (Samples), judges them like any other, and starts them over at will. Nothing in a sample is
counted, listed by `todo`, imported, recorded as a decision or acted on.

The files are placeholders drawn by script, kept in tool/samples_src with a manifest. The moving figure
is a rigged model (`--model`, or `[samples] model` and `scale` in studio.toml) moved by motion made up
here and baked the way a project's own samples are; with no such model, a blocky figure and its clips.
"""
from __future__ import annotations

import array
import math
import shutil
import sys
import tempfile
import wave
from pathlib import Path

from . import bake
from .store import SAMPLE, StudioError, read_json

SRC = Path(__file__).resolve().parents[1] / "samples_src"
MOTION_SET = "sample.figure"
BY = "studio samples"


# ------------------------------------------------------------------- made-up motion
def _rot(axis: int, deg: float) -> list:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    if axis == 0:
        return [1, 0, 0, 0, 0, c, -s, 0, 0, s, c, 0, 0, 0, 0, 1]
    if axis == 1:
        return [c, 0, s, 0, 0, 1, 0, 0, -s, 0, c, 0, 0, 0, 0, 1]
    return [c, -s, 0, 0, s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def _at(x: float, y: float, z: float) -> list:
    return [1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1]


def _march(u):
    a = math.sin(2 * math.pi * u)
    return ({"leg_l": 32 * a, "leg_r": -32 * a, "shin_l": -28 * max(0, -a), "shin_r": -28 * max(0, a),
             "arm_l": -24 * a, "arm_r": 24 * a, "chest": -6}, -0.03 * abs(a))


def _lope(u):
    a, b = math.sin(2 * math.pi * u), math.sin(4 * math.pi * u)
    return ({"leg_l": 44 * a, "leg_r": -44 * a, "shin_l": -40 * max(0, -a), "shin_r": -40 * max(0, a),
             "arm_l": -38 * a, "arm_r": 38 * a, "chest": -14 + 4 * b, "neck": 10 - 3 * b,
             "body": (0, 5 * a, 0)}, -0.07 * abs(a))


def _reach(u):
    a = 0.5 - 0.5 * math.cos(2 * math.pi * u)
    return ({"arm_r": 120 * a, "limb_r": 35 * a, "chest": (8 * a, -12 * a, 0), "neck": -10 * a}, 0.0)


def _sway(u):
    a, b = math.sin(2 * math.pi * u), math.sin(4 * math.pi * u)
    return ({"body": (0, 0, 5 * a), "leg_l": (0, 0, -5 * a), "leg_r": (0, 0, -5 * a), "chest": (3 * b, 0, -7 * a),
             "neck": (-3 * b, 0, -4 * a), "arm_l": 6 * b, "arm_r": -6 * b}, -0.01 * abs(b))


CLIPS = [  # name, the words over it, title, summary, the motion, ticks at 60 a second
    ("march", "sample 1 march", "March", "Upright, even steps, arms low", _march, 48),
    ("lope", "sample 2 lope", "Lope", "Long stride, the chest leans and the hips turn", _lope, 66),
    ("reach", "sample 3 reach", "Reach", "One arm up and across, the chest follows", _reach, 90),
    ("sway", "sample 4 sway", "Sway", "Stands and shifts its weight, slowly", _sway, 150),
]
NEEDS = {"body", "chest", "neck", "leg_l", "leg_r", "shin_l", "shin_r", "arm_l", "arm_r"}


def made_up_samples(model: Path, scale: float = 1.0) -> dict:
    """A samples file as a project would write one (see bake.py), but the motion is invented here:
    each named bone turned about its own joint. For a rig whose bones rest unturned."""
    doc, _ = bake._read_glb(model)
    nodes = doc.get("nodes", [])
    if not doc.get("skins"):
        raise StudioError(f"{model.name} has no skin: it cannot be moved by its bones")
    joints = doc["skins"][0]["joints"]
    names = [nodes[j].get("name", "") for j in joints]
    lacks = sorted(NEEDS - set(names))
    if lacks:
        raise StudioError(f"{model.name} lacks the bones the made-up motion turns: {', '.join(lacks)}")
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    inside = set(joints)

    def pose(turns: dict, lift: float = 0.0) -> list:
        world: dict[int, list] = {}

        def of(j: int) -> list:
            if j not in world:
                node = nodes[j]
                t = node.get("translation", [0, 0, 0])
                m = _at(-t[0] * scale, t[1] * scale, -t[2] * scale)  # the file's axes are a half turn from the engine's
                turn = turns.get(node.get("name", ""), 0.0)
                for axis, deg in enumerate(turn if isinstance(turn, tuple) else (turn, 0, 0)):
                    if deg:
                        m = bake._mul(m, _rot(axis, deg))
                if node.get("name") == "body":
                    m = bake._mul(_at(0, lift, 0), m)
                p = parent.get(j)
                world[j] = bake._mul(of(p), m) if p in inside else m
            return world[j]
        return [[of(j)[r * 4 + c] for c in range(4) for r in range(4)] for j in joints]

    return {"format": bake.FORMAT, "rig": MOTION_SET, "model": model.name, "scale": scale,
            "ticks_per_second": 60, "bones": names, "rest": pose({}),
            "clips": [{"name": name, "label": label, "loop": True,
                       "frames": [pose(*fn(i / ticks)) for i in range(ticks)]}
                      for name, label, _, _, fn, ticks in CLIPS]}


def _figure(studio, model: str) -> tuple[list, str]:
    """Keep the samples' moving figure; returns its clips as candidates, and what it was made from."""
    conf = studio.config.get("samples") or {}
    path = Path(model or conf.get("model") or "")
    root = studio.repo_root()
    if path.parts and not path.is_absolute() and root is not None:
        path = root / path
    why = ""
    if path.is_file():
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "figure.glb"
                bake.bake(path, made_up_samples(path, float(conf.get("scale") or 1.0)), out)
                studio.set_motion(MOTION_SET, out, sample=True)
            return ([(name, label, title, summary) for name, label, title, summary, _, _ in CLIPS],
                    f"{path.name}, moved by motion made up in the Studio (nothing is solved: a hose or a cloth only "
                    f"follows the bone it hangs on, so it pulls where the project would not)")
        except (StudioError, KeyError, ValueError) as err:
            why = f" ({path.name} could not be used: {err})"
    elif path.parts:
        why = f" ({path}: no such file)"
    own = SRC / "models" / "figure_brute.glb"
    entry = studio.set_motion(MOTION_SET, own, sample=True)
    words = {"rest": ("Rest", "Stands and breathes"), "stride": ("Stride", "Walks on the spot"),
             "rake": ("Rake", "One arm swings across")}
    return ([(c["name"], f"sample {i} {c['name']}", *words.get(c["name"], (c["name"].title(), "")))
             for i, c in enumerate(entry["clips"], 1)],
            "a blocky placeholder figure and its own clips" + why)


# ------------------------------------------------------------------------- the batches
QUESTION = [
    ("Left of the door", True, """**The lamp hangs left of the door, at head height.**

- Costs: nothing; the bracket is already there.
- Risks: it sits behind the door when the door stands open.
- Feels like: you see the lamp before you see the door.
"""),
    ("Over the door", False, """**The lamp hangs over the lintel.**

- Costs: one new bracket.
- Risks: a tall figure in the doorway hides it.
- Feels like: the doorway itself glows.
"""),
    ("No lamp", False, """**The door stays dark; the room beyond lights it.**

- Costs: nothing.
- Risks: the door is hard to find from the far end of the hall.
- Feels like: you find the door by the light under it.
"""),
]
WRITING = [
    ("Plain", "plain.md", "# Keep out\n\nThis door is locked from the other side.\n"),
    ("Worn", "worn.md", "# KEEP  UT\n\nThis d‑‑r is l‑cked fr‑m the oth‑r side.\n\nHalf the letters have flaked away.\n"),
    ("Long", "long.md", "# Notice to all hands\n\nThis door is locked from the other side by order of the watch.\n\n"
                        "1. Do not knock.\n2. Do not wait.\n3. Report anything you hear behind it.\n"),
]
IN_APP = [("Light", "sample 1 light", "A few drops"), ("Heavy", "sample 2 heavy", "Twice as much, stains for a minute"),
          ("Soaked", "sample 3 soaked", "Three times as much, stains for three minutes")]
VIDEO = [("Bars", "clip_bars.mp4", "A moving test card"), ("Zoom", "clip_zoom.mp4", "A slow zoom into a fractal"),
         ("Cells", "clip_cells.mp4", "Dots that grow and die")]
SAY = "A sample: made up, to try the page on. Nothing here is counted, recorded or acted on."


def _from_set(studio, slug: str, **kw) -> str:
    """A sample that shows one set of the placeholder files in tool/samples_src."""
    src = (read_json(SRC / "manifest.json") or {}).get(slug)
    if src is None:
        raise StudioError(f"the sample files for {slug!r} are missing under {SRC}")
    bid = studio.new_batch(slug, sample=True, filed_by=BY, kind=src["kind"], mode=src["mode"],
                           max_winners=src.get("max_winners", 1), targets=src.get("targets") or {}, **kw)["id"]
    for cand in src["candidates"]:
        studio.add_candidate(bid, [SRC / f for f in cand.get("files", [])], cid=cand["id"], title=cand.get("title", ""),
                             summary=cand.get("summary", ""), made_with=cand.get("made_with") or {})
    for ref in src.get("context", []):
        studio.add_context(bid, SRC / ref["file"], ref.get("label", ""))
    return bid


def _pictures(studio, _):
    return _from_set(studio, "pictures", title="Pictures: pick up to two",
                      ask="Which one or two would you keep?", brief=SAY + " The pictures are placeholders drawn by script.",
                      look_at=["Click a picture to open it large; the wheel zooms, the arrow keys step",
                               "Tick two or more, then Compare: they zoom and pan together",
                               "The reference sits above the candidates; click it to see it large"])


def _textures(studio, _):
    return _from_set(studio, "textures", title="Textures: approve or send back each",
                      ask="Approve, redo or reject each material.", brief=SAY,
                      look_at=["Switch on Tile and drag Tile size: does the repeat show?",
                               "Try the backgrounds under Behind it"])


def _models(studio, _):
    return _from_set(studio, "models", title="Models: turn them, play their clips",
                      ask="Which build would you keep?", brief=SAY + " The models are blocky placeholders built by script.",
                      look_at=["Drag to turn, wheel to zoom, right-drag to pan",
                               "Motion picks a clip the model carries; Turntable, Wireframe and the 1.8 m figure are beside it",
                               "Compare all: the views turn together"])


def _sounds(studio, _):
    return _from_set(studio, "sounds", title="Sounds: play them in turn",
                      ask="Which shot would you keep?", brief=SAY,
                      look_at=["Play them in turn runs down the row; Loop repeats one",
                               "Each tile shows its length and how loud it peaks",
                               "Mark on a tile opens it large: mark a moment or a stretch of it, with a note for each"])


TUNE = {"bpm": 120.0, "beats": 4, "first": 0.0}  # the made-up tune's tempo: it is filed with it, so the page counts bars
TUNE_BARS = 6


def tune_wav(path: Path) -> None:
    """Write the made-up tune: six bars at 120, a thump on each beat, a low line, ticks and a melody that come in
    at bar 3, and a harsh buzz across bar 5 for the user to mark. Mono, 16-bit, peaking just under -20 dBFS."""
    rate, beat = 22050, 60 / TUNE["bpm"]
    n = int(rate * beat * TUNE["beats"] * TUNE_BARS)
    out = [0.0] * n
    tau = 2 * math.pi

    def put(at: float, seconds: float, fn) -> None:
        start = int(at * rate)
        for i in range(max(0, min(int(seconds * rate), n - start))):
            out[start + i] += fn(i / rate)

    seed = [20240]

    def hiss(_t: float) -> float:
        seed[0] = (seed[0] * 1103515245 + 12345) & 0x7FFFFFFF
        return seed[0] / 0x3FFFFFFF - 1.0

    for k in range(TUNE["beats"] * TUNE_BARS):  # the thump: a low note that falls and dies away
        put(k * beat, 0.2, lambda t: 0.9 * math.sin(tau * (45 * t + 6.5 * (1 - math.exp(-t * 28)))) * math.exp(-t * 16))
    low = [55.0, 55.0, 65.41, 49.0, 55.0, 55.0]  # the low line: one note a bar
    for bar, hz in enumerate(low):
        put(bar * 4 * beat, 4 * beat, lambda t, hz=hz: 0.32 * math.sin(tau * hz * t) * min(1.0, t * 40, (4 * beat - t) * 40))
    for k in range(2 * TUNE["beats"], TUNE["beats"] * TUNE_BARS):  # ticks between the beats, from bar 3
        put((k + 0.5) * beat, 0.03, lambda t: 0.35 * hiss(t) * math.exp(-t * 120))
    notes = [440.0, 523.25, 659.25, 523.25, 587.33, 493.88, 440.0, 392.0]  # the melody: a note a beat, bars 3, 4 and 6
    for bar in (2, 3, 5):
        for k in range(4):
            hz = notes[(k + (4 if bar == 3 else 0)) % len(notes)]
            put((bar * 4 + k) * beat, beat * 0.9, lambda t, hz=hz: 0.3 * (math.sin(tau * hz * t) + 0.3 * math.sin(tau * 2 * hz * t)) * math.exp(-t * 5))
    put(4 * 4 * beat, 4 * beat,  # bar 5: the fault to find, a bright buzz over everything
        lambda t: 0.55 * (1 if math.sin(tau * 1760 * t) > 0 else -1) * (0.6 + 0.4 * math.sin(tau * 9 * t)) * min(1.0, t * 30, (4 * beat - t) * 30))
    fade = int(rate * beat)
    for i in range(fade):  # the last beat dies away
        out[n - fade + i] *= 1 - i / fade
    top = max(abs(x) for x in out) or 1.0
    gain = 10 ** (-20.5 / 20) * 32767 / top
    data = array.array("h", (int(x * gain) for x in out))
    if sys.byteorder == "big":
        data.byteswap()
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate); wav.writeframes(data.tobytes())


def _tune(studio, _):
    seconds = 60 / TUNE["bpm"] * TUNE["beats"] * TUNE_BARS
    bid = studio.new_batch("tune", sample=True, filed_by=BY, kind="audio", mode="rate", title="A longer sound: mark parts of it",
                           ask="Approve it, or mark what must change.",
                           brief=SAY + f" The tune is written by script: {TUNE_BARS} bars at {TUNE['bpm']:g} beats a minute, with a harsh buzz across bar 5.",
                           look_at=["Press Mark, or Enter: drag across the wave to mark a stretch, press M to drop a moment while it plays",
                                    "Each mark has its own note, and is a Change, a Cut or a Keep",
                                    "It was filed with its tempo, so the ruler counts bars as well as seconds",
                                    "Bar 5 has a buzz over it: mark it and see what the page measures there"])["id"]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tune.wav"
        tune_wav(path)
        studio.add_candidate(bid, [path], title="Six bars", summary=f"{seconds:g} s, {TUNE['bpm']:g} beats a minute, 4 to the bar", tempo=dict(TUNE),
                             made_with={"tool": "synth (script)", "source": "studio.py samples"})
    return bid


def _held(studio, _):
    return _from_set(studio, "held", title="A sound the checks refuse",
                      ask="You never see this one: it shows under Held back by the checks.", brief=SAY)


def _motions(studio, model):
    clips, source = _figure(studio, model)
    bid = studio.new_batch("motions", sample=True, filed_by=BY, kind="in_app", title="Motions: looping in place",
                           ask="Which motion would you keep?", launch="echo a sample has no build to start",
                           brief=SAY + f" The figure is {source}; a real motion batch shows what the project itself draws.",
                           look_at=["Each loops in place over its label; Play, Half and Quarter slow them together",
                                    "Turntable and the 1.8 m figure; drag to turn one, Compare to turn them together",
                                    "The line under Start it with is what you would copy for a real batch"])["id"]
    for i, (name, label, title, summary) in enumerate(clips, 1):
        studio.add_candidate(bid, [], cid=str(i), label=label, title=title, summary=summary,
                             motion=f"{MOTION_SET}:{name}", made_with={"tool": "made-up motion", "source": "studio.py samples"})
    return bid


def _video(studio, _):
    bid = studio.new_batch("video", sample=True, filed_by=BY, kind="video", title="Video: three clips",
                           ask="Which clip would you keep?", brief=SAY + " The clips are test patterns, four seconds each, silent.",
                           look_at=["Play a clip in its tile; it loops",
                                    "Press Mark, or Enter: step a frame at a time with , and . and press M to mark the frame the clip is on",
                                    "I and O set the start and the end of a stretch; Paint (B) draws on the frame, in the colour of its mark",
                                    "Each mark has its own note, and is a Change, a Cut or a Keep"])["id"]
    for title, name, summary in VIDEO:
        studio.add_candidate(bid, [SRC / "video" / name], title=title, summary=summary,
                             made_with={"tool": "ffmpeg test source", "source": "studio.py samples"})
    return bid


def _in_app(studio, _):
    bid = studio.new_batch("in-app", sample=True, filed_by=BY, kind="in_app", title="In the app: labels only",
                           ask="Which amount would you keep?", launch="echo a sample has no build to start", brief=SAY,
                           look_at=["Nothing is drawn here: you would look for each label in the running app, then mark it here"])["id"]
    for i, (title, label, summary) in enumerate(IN_APP, 1):
        studio.add_candidate(bid, [], cid=str(i), label=label, title=title, summary=summary,
                             made_with={"tool": "tuning", "source": "studio.py samples"})
    return bid


def _question(studio, _):
    bid = studio.new_batch("question", sample=True, filed_by=BY, kind="question", title="A question with options",
                           ask="Where does the lamp by the door hang?",
                           brief=SAY + "\n\nA real question quotes the words of yours that raised it here.")["id"]
    for title, recommended, body in QUESTION:
        studio.add_candidate(bid, [], title=title, body=body, recommended=recommended)
    return bid


def _writing(studio, _):
    bid = studio.new_batch("writing", sample=True, filed_by=BY, kind="text", title="Writing: three wordings",
                           ask="Which sign goes on the door?", brief=SAY,
                           look_at=["Each is a short page of text, shown as it is written"])["id"]
    with tempfile.TemporaryDirectory() as tmp:
        for title, name, text in WRITING:
            path = Path(tmp) / name
            path.write_text(text, encoding="utf-8", newline="\n")
            studio.add_candidate(bid, [path], title=title, made_with={"tool": "written by hand", "source": "studio.py samples"})
    return bid


SAMPLES = [("motions", _motions), ("models", _models), ("pictures", _pictures), ("textures", _textures),
           ("sounds", _sounds), ("tune", _tune), ("video", _video), ("in-app", _in_app), ("question", _question),
           ("writing", _writing), ("held", _held)]


def _file(studio, bid: str, any_length: bool = False) -> dict:
    """Run the checks on a sample and file it. The tune is longer than a project lets its sounds be; it is made-up
    and never counted, so the project's length limit is set aside while that one sample is checked, and only here."""
    audio = (studio.config.get("checks") or {}).get("audio")
    if not (any_length and isinstance(audio, dict) and audio.get("max_seconds")):
        return studio.publish(bid)
    limit, audio["max_seconds"] = audio["max_seconds"], 0
    try:
        return studio.publish(bid)
    finally:
        audio["max_seconds"] = limit


def build(studio, model: str = "", fresh: bool = False) -> list[dict]:
    """Make every sample that is missing. `fresh` makes them all again and forgets the user's marks on them."""
    out = []
    have = set(studio.sample_ids()) | {p.name for p in studio.samples_dir.glob(SAMPLE + "*") if p.is_dir()}
    for slug, make in SAMPLES:
        bid = SAMPLE + slug
        if bid in have and not fresh:
            if slug == "motions" and MOTION_SET not in studio.motions():
                _figure(studio, model)
            out.append({"id": bid, "note": "kept"})
            continue
        if bid in have:
            shutil.rmtree(studio.samples_dir / bid)
        make(studio, model)
        batch = studio.load_batch(bid)
        batch["order"] = [s for s, _ in SAMPLES].index(slug)
        studio.save_batch(batch)
        report = _file(studio, bid, any_length=slug == "tune")
        if slug == "held" and report["ready"]:  # this Studio's checks are loose: nothing to show held
            shutil.rmtree(studio.samples_dir / bid)
            out.append({"id": bid, "note": "left out: this Studio's checks refuse nothing in it"})
            continue
        out.append({"id": bid, "note": "made" if report["ready"] else "made; held back by the checks: "
                    + "; ".join(str(e.get("msg", e)) if isinstance(e, dict) else str(e) for e in report["errors"])})
    return out
