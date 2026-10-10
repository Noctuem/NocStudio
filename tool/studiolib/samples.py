"""Made-up batches for trying the page on: one for each thing the user can be asked to judge.

They live under samples/ in the studio home, apart from the real batches. The user opens them from the
Inbox (Samples), judges them like any other, and starts them over at will. Nothing in a sample is
counted, listed by `todo`, imported, recorded as a decision or acted on.

The files are placeholders drawn by script, kept in tool/samples_src with a manifest. The moving figure
is a rigged model (`--model`, or `[samples] model` and `scale` in studio.toml) moved by motion made up
here and baked the way a project's own samples are; with no such model, a blocky figure and its clips.
"""
from __future__ import annotations

import math
import shutil
import tempfile
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
    """A samples file as the game would write one (see bake.py), but the motion is invented here:
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
    root = studio.game_root()
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
                    f"follows the bone it hangs on, so it pulls where the game would not)")
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
INGAME = [("Light", "sample 1 light", "A few drops"), ("Heavy", "sample 2 heavy", "Twice as much, stains for a minute"),
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
                               "Each tile shows its length and how loud it peaks"])


def _held(studio, _):
    return _from_set(studio, "held", title="A sound the checks refuse",
                      ask="You never see this one: it shows under Held back by the checks.", brief=SAY)


def _motions(studio, model):
    clips, source = _figure(studio, model)
    bid = studio.new_batch("motions", sample=True, filed_by=BY, kind="ingame", title="Motions: looping in place",
                           ask="Which motion would you keep?", launch="echo a sample has no build to start",
                           brief=SAY + f" The figure is {source}; a real motion batch shows what the game itself draws.",
                           look_at=["Each loops in place over its label; Play, Half and Quarter slow them together",
                                    "Turntable and the 1.8 m figure; drag to turn one, Compare to turn them together",
                                    "The line under Start the game with is what you would copy for a real batch"])["id"]
    for i, (name, label, title, summary) in enumerate(clips, 1):
        studio.add_candidate(bid, [], cid=str(i), label=label, title=title, summary=summary,
                             motion=f"{MOTION_SET}:{name}", made_with={"tool": "made-up motion", "source": "studio.py samples"})
    return bid


def _video(studio, _):
    bid = studio.new_batch("video", sample=True, filed_by=BY, kind="video", title="Video: three clips",
                           ask="Which clip would you keep?", brief=SAY + " The clips are test patterns, four seconds each, silent.",
                           look_at=["Each clip loops; the controls are the browser's own"])["id"]
    for title, name, summary in VIDEO:
        studio.add_candidate(bid, [SRC / "video" / name], title=title, summary=summary,
                             made_with={"tool": "ffmpeg test source", "source": "studio.py samples"})
    return bid


def _ingame(studio, _):
    bid = studio.new_batch("in-game", sample=True, filed_by=BY, kind="ingame", title="In the game: labels only",
                           ask="Which amount would you keep?", launch="echo a sample has no build to start", brief=SAY,
                           look_at=["Nothing is drawn here: you would look for each label in the game, then mark it here"])["id"]
    for i, (title, label, summary) in enumerate(INGAME, 1):
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
           ("sounds", _sounds), ("video", _video), ("in-game", _ingame), ("question", _question),
           ("writing", _writing), ("held", _held)]


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
        report = studio.publish(bid)
        if slug == "held" and report["ready"]:  # this Studio's checks are loose: nothing to show held
            shutil.rmtree(studio.samples_dir / bid)
            out.append({"id": bid, "note": "left out: this Studio's checks refuse nothing in it"})
            continue
        out.append({"id": bid, "note": "made" if report["ready"] else "made; held back by the checks: "
                    + "; ".join(str(e.get("msg", e)) if isinstance(e, dict) else str(e) for e in report["errors"])})
    return out
