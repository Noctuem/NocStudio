"""Checks that run before a batch reaches the user's inbox.

The user should never spend a minute on a candidate a script could have refused:
a sound that is too loud, a model at the wrong height, two candidates that are
the same file. Every check reads the file itself; nothing is taken on trust
from the maker's notes.
"""
from __future__ import annotations

import array
import hashlib
import json
import math
import struct
import wave
from pathlib import Path

GENERATED_KINDS = ("image", "texture", "model", "audio", "video")


def _chk(level: str, cid: str, msg: str) -> dict:
    return {"level": level, "id": cid, "msg": msg}


# --------------------------------------------------------------------- images
def image_size(path: Path):
    with open(path, "rb") as fh:
        head = fh.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", head[6:10])
        if head[:2] == b"\xff\xd8":
            fh.seek(2)
            while True:
                marker = fh.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                while marker[1] == 0xFF:
                    marker = bytes([0xFF]) + fh.read(1)
                code = marker[1]
                if code in (0xD8, 0x01) or 0xD0 <= code <= 0xD7:
                    continue
                (size,) = struct.unpack(">H", fh.read(2))
                if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", fh.read(5)[1:5])
                    return (w, h)
                fh.seek(size - 2, 1)
    return None


def check_image(path: Path, kind: str, rules: dict):
    facts, out = {}, []
    size = image_size(path)
    if not size:
        return facts, [_chk("warn", "image.size", "could not read the picture's size")]
    w, h = size
    facts.update(width=w, height=h)
    if kind == "texture":
        r = rules.get("texture", {})
        if r.get("power_of_two") and (w & (w - 1) or h & (h - 1)):
            out.append(_chk("warn", "texture.pow2", f"{w}x{h} is not a power of two"))
        if r.get("max_size") and max(w, h) > r["max_size"]:
            out.append(_chk("warn", "texture.size", f"{w}x{h} is over the {r['max_size']} px limit"))
    else:
        r = rules.get("image", {})
        if r.get("min_width") and w < r["min_width"]:
            out.append(_chk("warn", "image.small", f"only {w} px wide; hard to judge detail"))
    return facts, out


# ---------------------------------------------------------------------- audio
def check_audio(path: Path, rules: dict):
    facts, out = {}, []
    r = rules.get("audio", {})
    if path.suffix.lower() != ".wav":
        return facts, [_chk("warn", "audio.format", f"{path.suffix} is not WAV; level and length were not checked")]
    try:
        with wave.open(str(path), "rb") as wav:
            channels, width, rate, frames = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
            raw = wav.readframes(frames)
    except (wave.Error, EOFError) as err:
        return facts, [_chk("error", "audio.read", f"not a PCM WAV the game can load ({err})")]
    seconds = frames / rate if rate else 0.0
    peak = 0.0
    if width == 2:
        samples = array.array("h")
        samples.frombytes(raw[: len(raw) // 2 * 2])
        if struct.pack("=H", 1) != struct.pack("<H", 1):
            samples.byteswap()
        peak = max((abs(s) for s in samples), default=0) / 32768.0
    elif width == 1:
        peak = max((abs(b - 128) for b in raw), default=0) / 128.0
    elif width == 3:
        top = 0
        for i in range(0, len(raw) - 2, 3):
            v = int.from_bytes(raw[i:i + 3], "little", signed=True)
            if abs(v) > top:
                top = abs(v)
        peak = top / 8388608.0
    elif width == 4:
        samples = array.array("i")
        samples.frombytes(raw[: len(raw) // 4 * 4])
        peak = max((abs(s) for s in samples), default=0) / 2147483648.0
    dbfs = 20 * math.log10(peak) if peak > 0 else -120.0
    facts.update(seconds=round(seconds, 3), peak_dbfs=round(dbfs, 1), sample_rate=rate,
                 channels=channels, bits=width * 8)
    if r.get("sample_width_bits") and width * 8 != r["sample_width_bits"]:
        out.append(_chk("error", "audio.bits", f"{width * 8}-bit; the game loads {r['sample_width_bits']}-bit PCM"))
    if r.get("max_peak_dbfs") is not None and dbfs > r["max_peak_dbfs"] + 0.05:
        out.append(_chk("error", "audio.peak", f"peaks at {dbfs:.1f} dBFS; the limit is {r['max_peak_dbfs']:g}"))
    if r.get("max_seconds") and seconds > r["max_seconds"] + 0.005:
        out.append(_chk("error", "audio.length", f"{seconds:.2f} s long; the limit is {r['max_seconds']:g} s"))
    if peak == 0:
        out.append(_chk("error", "audio.silent", "the file is silent"))
    return facts, out


# --------------------------------------------------------------------- models
def _mat_mul(a, b):
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


def _node_matrix(node):
    """Row-major local matrix of a glTF node."""
    if "matrix" in node:
        m = node["matrix"]  # glTF stores column-major
        return [m[c * 4 + r] for r in range(4) for c in range(4)]
    tx, ty, tz = node.get("translation", (0, 0, 0))
    x, y, z, w = node.get("rotation", (0, 0, 0, 1))
    sx, sy, sz = node.get("scale", (1, 1, 1))
    return [
        (1 - 2 * (y * y + z * z)) * sx, (2 * (x * y - z * w)) * sy, (2 * (x * z + y * w)) * sz, tx,
        (2 * (x * y + z * w)) * sx, (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z - x * w)) * sz, ty,
        (2 * (x * z - y * w)) * sx, (2 * (y * z + x * w)) * sy, (1 - 2 * (x * x + y * y)) * sz, tz,
        0, 0, 0, 1,
    ]


def read_gltf_json(path: Path) -> dict:
    data = path.read_bytes()
    if data[:4] != b"glTF":
        return json.loads(data.decode("utf-8"))
    offset = 12
    while offset + 8 <= len(data):
        length, ctype = struct.unpack_from("<II", data, offset)
        offset += 8
        if ctype == 0x4E4F534A:
            return json.loads(data[offset:offset + length].decode("utf-8"))
        offset += length
    raise ValueError("no JSON chunk in the .glb")


def model_facts(path: Path) -> dict:
    gltf = read_gltf_json(path)
    nodes, meshes, accessors = gltf.get("nodes", []), gltf.get("meshes", []), gltf.get("accessors", [])
    scene = gltf.get("scenes", [{}])[gltf.get("scene", 0)] if gltf.get("scenes") else {"nodes": list(range(len(nodes)))}
    lo, hi, tris = [math.inf] * 3, [-math.inf] * 3, 0
    identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    stack = [(n, identity) for n in scene.get("nodes", [])]
    seen = 0
    while stack and seen < 100000:
        index, parent = stack.pop()
        seen += 1
        node = nodes[index]
        world = _mat_mul(parent, _node_matrix(node))
        if "mesh" in node:
            for prim in meshes[node["mesh"]].get("primitives", []):
                pos = accessors[prim["attributes"]["POSITION"]] if "POSITION" in prim.get("attributes", {}) else None
                count = accessors[prim["indices"]]["count"] if "indices" in prim else (pos or {}).get("count", 0)
                if prim.get("mode", 4) == 4:
                    tris += count // 3
                if pos and "min" in pos and "max" in pos:
                    for cx in (pos["min"][0], pos["max"][0]):
                        for cy in (pos["min"][1], pos["max"][1]):
                            for cz in (pos["min"][2], pos["max"][2]):
                                p = [world[r * 4] * cx + world[r * 4 + 1] * cy + world[r * 4 + 2] * cz + world[r * 4 + 3]
                                     for r in range(3)]
                                lo = [min(lo[i], p[i]) for i in range(3)]
                                hi = [max(hi[i], p[i]) for i in range(3)]
        stack += [(child, world) for child in node.get("children", [])]
    clips = []
    for i, anim in enumerate(gltf.get("animations", [])):
        ends = [accessors[s["input"]].get("max", [0])[0] for s in anim.get("samplers", []) if "input" in s]
        clips.append({"name": anim.get("name") or f"clip {i + 1}", "seconds": round(max(ends, default=0), 2)})
    facts = {"triangles": tris, "clips": clips, "skinned": bool(gltf.get("skins")),
             "materials": len(gltf.get("materials", [])), "textures": len(gltf.get("images", []))}
    if lo[0] != math.inf:
        facts.update(height_m=round(hi[1] - lo[1], 3), width_m=round(hi[0] - lo[0], 3),
                     depth_m=round(hi[2] - lo[2], 3), floor_y=round(lo[1], 3))
    return facts


def check_model(path: Path, rules: dict, targets: dict):
    out = []
    try:
        facts = model_facts(path)
    except Exception as err:  # a broken file must not stop the other checks
        return {}, [_chk("error", "model.read", f"could not read the model ({err})")]
    limit = targets.get("max_triangles")
    soft = rules.get("model", {}).get("max_triangles")
    if limit and facts["triangles"] > limit:
        out.append(_chk("error", "model.triangles", f"{facts['triangles']} triangles; this batch's limit is {limit}"))
    elif soft and facts["triangles"] > soft:
        out.append(_chk("warn", "model.triangles", f"{facts['triangles']} triangles; over the usual {soft}"))
    want = targets.get("height_m")
    if want and "height_m" in facts:
        slack = targets.get("height_tolerance_m", 0.05)
        if abs(facts["height_m"] - want) > slack:
            out.append(_chk("error", "model.height", f"{facts['height_m']:.2f} m tall; it must be {want:g} m"))
    if "floor_y" in facts and abs(facts["floor_y"]) > 0.02:
        out.append(_chk("warn", "model.floor", f"its feet are at y = {facts['floor_y']:.2f} m, not on the floor"))
    for clip in targets.get("clips", []):
        if clip not in [c["name"] for c in facts["clips"]]:
            out.append(_chk("error", "model.clip", f"the motion {clip!r} is missing"))
    return facts, out


# ---------------------------------------------------------------------- batch
def check_batch(studio, batch: dict) -> dict:
    rules = studio.config.get("checks", {})
    review = studio.config.get("review", {})
    kind, mode = batch.get("kind"), batch.get("mode")
    targets = batch.get("targets") or {}
    folder = studio.batch_dir(batch["id"])
    top = []
    if not (batch.get("ask") or "").strip():
        top.append(_chk("error", "batch.ask", "say in one sentence what the user is choosing (--ask)"))
    if not batch.get("look_at") and mode != "question":
        top.append(_chk("warn", "batch.look_at", "no 'look at' points: tell the user where to look (--look)"))
    n = len(batch.get("candidates", []))
    need = {"pick": 2, "rate": 1, "question": 2}[mode]
    if n < need:
        top.append(_chk("error", "batch.count", f"a {mode} batch needs at least {need} candidates; this has {n}"))
    if review.get("max_candidates") and n > review["max_candidates"]:
        top.append(_chk("warn", "batch.many", f"{n} candidates; over {review['max_candidates']} is hard to judge well"))
    every_candidate_has_one = bool(batch.get("candidates")) and all(c.get("slot") for c in batch["candidates"])
    if mode != "question" and not batch.get("slot") and not every_candidate_has_one:
        if not batch.get("sample"):
            top.append(_chk("warn", "batch.slot", "no slot: the winner has nowhere to go (--slot)"))
    elif batch.get("slot") and studio.slot(batch["slot"]) is None:
        top.append(_chk("warn", "batch.slot_new", f"slot {batch['slot']!r} does not exist yet; import will create it"))
    if kind == "ingame" and not batch.get("launch"):
        top.append(_chk("warn", "batch.launch", "no launch line: tell the user how to start the game to look (--launch)"))
    open_now = 0
    for other in studio.batch_ids():
        if other != batch["id"] and studio.load_batch(other)["status"] in ("open", "draft"):
            open_now += 1
    if review.get("max_open_batches") and open_now >= review["max_open_batches"]:
        top.append(_chk("warn", "batch.inbox", f"the user's inbox already holds {open_now} batches; "
                                               f"consider waiting before filing more"))
    hashes: dict[str, str] = {}
    for cand in batch.get("candidates", []):
        facts, out = {}, []
        files = cand.get("files", [])
        if kind == "ingame":
            if not cand.get("label"):
                out.append(_chk("error", "cand.label", "an in-game candidate needs the label the user will see over it"))
        elif kind == "question":
            if not (cand.get("body") or cand.get("summary")):
                out.append(_chk("error", "cand.body", "an option needs a description"))
        elif not files:
            out.append(_chk("error", "cand.files", "no file"))
        for entry in files:
            path = folder / entry["path"]
            if not path.is_file():
                out.append(_chk("error", "file.missing", f"{entry['path']} is missing"))
                continue
            size = path.stat().st_size
            entry["bytes"] = size
            if size == 0:
                out.append(_chk("error", "file.empty", f"{entry['path']} is empty"))
                continue
            max_mb = rules.get("file", {}).get("max_mb")
            if max_mb and size > max_mb * 1024 * 1024:
                out.append(_chk("warn", "file.big", f"{entry['path']} is {size / 1048576:.0f} MB"))
            f_facts, f_out = {}, []
            if entry["kind"] in ("image", "texture"):
                f_facts, f_out = check_image(path, entry["kind"], rules)
            elif entry["kind"] == "audio":
                f_facts, f_out = check_audio(path, rules)
            elif entry["kind"] == "model":
                f_facts, f_out = check_model(path, rules, targets)
            entry["facts"] = f_facts
            if entry.get("role") == "primary":
                facts.update(f_facts)
                digest = hashlib.sha1(path.read_bytes()).hexdigest()
                if digest in hashes:
                    out.append(_chk("warn", "cand.same", f"the same file as candidate {hashes[digest]}"))
                else:
                    hashes[digest] = cand["id"]
            many = len(files) > 1
            out += [dict(c, msg=f"{Path(entry['path']).name}: {c['msg']}") if many else c for c in f_out]
        if kind in GENERATED_KINDS and not cand.get("made_with") and not cand.get("carried_from"):
            out.append(_chk("warn", "cand.provenance", "no record of how it was made (--tool, --prompt, --seed)"))
        cand["facts"], cand["checks"] = facts, out
    batch["checks"] = top
    errors = [f"{c['msg']}" for c in top if c["level"] == "error"]
    warnings = [f"{c['msg']}" for c in top if c["level"] == "warn"]
    for cand in batch.get("candidates", []):
        errors += [f"candidate {cand['id']}: {c['msg']}" for c in cand["checks"] if c["level"] == "error"]
        warnings += [f"candidate {cand['id']}: {c['msg']}" for c in cand["checks"] if c["level"] == "warn"]
    return {"errors": errors, "warnings": warnings}
