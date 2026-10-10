"""Bake motions into a model: the project's own samples of what it draws, written as glTF clips.

The game knows how each motion really looks (its keys, its eased timelines, the hose it hangs each
frame). So the game samples itself and writes plain numbers; this module only turns those numbers
into animation clips inside a copy of the model, which the page's 3D view loops.

The samples file (JSON), format "studio-motion-samples-1":

    {
      "format": "studio-motion-samples-1",
      "rig": "enemy.creature",
      "model": "content/rigs/creature.glb",        the model the samples are of, in the game repo
      "scale": 0.7906,                              what the game multiplies the model's metres by
      "ticks_per_second": 60,
      "bones": ["root", "body", ...],               the model's joints by name, in the order used below
      "rest": [M, M, ...],                          one matrix a bone, standing at rest
      "clips": [
        {"name": "stride_lope", "label": "stride 2 lope", "loop": true,
         "frames": [[M, M, ...], [M, M, ...], ...]}        one list of matrices a tick
      ]
    }

M is a bone's posed model matrix as the game draws its piece with: 16 numbers, column by column
(glam's `Mat4::to_cols_array()`), taking a point of the bone's own rest space to the character's own
space in real metres (+y up, -z ahead, +x to its right, the origin between its feet). The
character's place and facing in the world are left out, so a walk is sampled in place.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from .store import StudioError

FORMAT = "studio-motion-samples-1"
FLIP = (-1.0, 1.0, -1.0)  # the engine's (x, y, z) is the file's (-x, y, -z): a half turn about y


# ------------------------------------------------------------------- matrices
# 4x4, row-major lists of 16; a point is a column, so M[3], M[7], M[11] are the translation.
def _mul(a, b):
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


def _from_cols(cols):
    if len(cols) != 16:
        raise StudioError("a bone's matrix is 16 numbers, column by column")
    return [float(cols[c * 4 + r]) for r in range(4) for c in range(4)]


def _inverse(m):
    a = [list(m[r * 4:r * 4 + 4]) + [1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]
    for col in range(4):
        pivot = max(range(col, 4), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise StudioError("a bone's matrix cannot be inverted (it flattens space)")
        a[col], a[pivot] = a[pivot], a[col]
        d = a[col][col]
        a[col] = [x / d for x in a[col]]
        for r in range(4):
            if r != col and a[r][col]:
                f = a[r][col]
                a[r] = [x - f * y for x, y in zip(a[r], a[col])]
    return [a[r][c + 4] for r in range(4) for c in range(4)]


def _flip(m):
    """The same motion seen in the file's space: C M C with C = diag(-1, 1, -1)."""
    s = FLIP + (1.0,)
    return [m[r * 4 + c] * s[r] * s[c] for r in range(4) for c in range(4)]


def _trs(m):
    """Translation, rotation (x, y, z, w) and one scale out of a matrix with no shear."""
    cols = [(m[0 + c], m[4 + c], m[8 + c]) for c in range(3)]
    lens = [math.sqrt(sum(x * x for x in col)) or 1.0 for col in cols]
    r = [[cols[c][row] / lens[c] for c in range(3)] for row in range(3)]
    trace = r[0][0] + r[1][1] + r[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        q = ((r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s, 0.25 * s)
    elif r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2
        q = (0.25 * s, (r[0][1] + r[1][0]) / s, (r[0][2] + r[2][0]) / s, (r[2][1] - r[1][2]) / s)
    elif r[1][1] > r[2][2]:
        s = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2
        q = ((r[0][1] + r[1][0]) / s, 0.25 * s, (r[1][2] + r[2][1]) / s, (r[0][2] - r[2][0]) / s)
    else:
        s = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2
        q = ((r[0][2] + r[2][0]) / s, (r[1][2] + r[2][1]) / s, 0.25 * s, (r[1][0] - r[0][1]) / s)
    n = math.sqrt(sum(x * x for x in q)) or 1.0
    return (m[3], m[7], m[11]), tuple(x / n for x in q), sum(lens) / 3.0


# ------------------------------------------------------------------- the file
def _read_glb(path: Path):
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise StudioError(f"{path}: not a binary .glb")
    doc, blob, offset = None, b"", 12
    while offset + 8 <= len(data):
        length, ctype = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8:offset + 8 + length]
        if ctype == 0x4E4F534A:
            doc = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            blob = bytes(chunk)
        offset += 8 + length
    if doc is None:
        raise StudioError(f"{path}: no JSON chunk")
    return doc, blob


def _write_glb(path: Path, doc: dict, blob: bytes) -> None:
    text = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    blob += b"\x00" * (-len(blob) % 4)
    total = 12 + 8 + len(text) + 8 + len(blob)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(text), 0x4E4F534A) + text
                     + struct.pack("<II", len(blob), 0x004E4942) + blob)


def _inverse_binds(doc: dict, blob: bytes, skin: dict) -> list:
    acc = doc["accessors"][skin["inverseBindMatrices"]]
    view = doc["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or 64
    return [_from_cols(struct.unpack_from("<16f", blob, start + i * stride)) for i in range(acc["count"])]


def bake(model: Path, samples: dict, out: Path) -> dict:
    """Write `out`: the model, standing at the game's size, with one clip for each sampled motion."""
    if samples.get("format") != FORMAT:
        raise StudioError(f"the samples file must say \"format\": \"{FORMAT}\"")
    doc, blob = _read_glb(Path(model))
    if not doc.get("skins"):
        raise StudioError(f"{model} has no skin: the motions need its joints")
    skin = doc["skins"][0]
    joints = skin["joints"]
    names = {doc["nodes"][n].get("name"): i for i, n in enumerate(joints)}
    bones = samples.get("bones") or []
    missing = [b for b in bones if b not in names]
    if missing:
        raise StudioError(f"the samples name bones the model lacks: {', '.join(missing)}")
    unsampled = sorted(set(names) - set(bones))
    scale = float(samples.get("scale") or 1.0)
    fps = float(samples.get("ticks_per_second") or 60)
    binds = [_inverse(ib) for ib in _inverse_binds(doc, blob, skin)]  # each joint's rest, in the file's space
    grow = [scale if i % 5 == 0 and i < 15 else (1.0 if i == 15 else 0.0) for i in range(16)]
    stand = [_mul(grow, j0) for j0 in binds]  # at rest, at the game's size

    rest = samples.get("rest")
    if rest is None or len(rest) != len(bones):
        raise StudioError("the samples need \"rest\": one matrix a bone, standing at rest")
    unrest = []
    for name, cols in zip(bones, rest):
        m = _from_cols(cols)
        want = stand[names[name]]
        off = max(abs(m[3] - FLIP[0] * want[3]), abs(m[7] - want[7]), abs(m[11] - FLIP[2] * want[11]))
        if off > 0.005:
            raise StudioError(f"at rest, bone {name!r} stands {off * 100:.1f} cm from where the model has it at scale {scale}: "
                              "check \"scale\", the axes (+y up, -z ahead) and that the matrix is the bone's posed model matrix")
        unrest.append(_inverse(m))

    # every joint becomes a child of one node and carries its whole place, so no parent's motion
    # is applied twice: the game's numbers are already each bone's place in the character's space
    joint_nodes = set(joints)
    for node in doc["nodes"]:
        if "children" in node:
            node["children"] = [c for c in node["children"] if c not in joint_nodes]
            if not node["children"]:
                del node["children"]
    for i, n in enumerate(joints):
        node = doc["nodes"][n]
        t, q, _ = _trs(stand[i])
        for key in ("matrix", "children"):
            node.pop(key, None)
        node.update(translation=list(t), rotation=list(q), scale=[scale] * 3)
    doc["nodes"].append({"name": "baked_motions", "children": list(joints)})
    scene = doc["scenes"][doc.get("scene", 0)]
    scene["nodes"] = [n for n in scene["nodes"] if n not in joint_nodes] + [len(doc["nodes"]) - 1]
    skin.pop("skeleton", None)

    out_blob = bytearray(blob + b"\x00" * (-len(blob) % 4))
    views, accessors = doc.setdefault("bufferViews", []), doc.setdefault("accessors", [])

    def push(values: list, kind: str, lo=None, hi=None) -> int:
        width = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[kind]
        views.append({"buffer": 0, "byteOffset": len(out_blob), "byteLength": len(values) * 4})
        out_blob.extend(struct.pack(f"<{len(values)}f", *values))
        acc = {"bufferView": len(views) - 1, "componentType": 5126, "count": len(values) // width, "type": kind}
        if lo is not None:
            acc.update(min=[lo], max=[hi])
        accessors.append(acc)
        return len(accessors) - 1

    animations, report = [], []
    for clip in samples.get("clips") or []:
        frames = list(clip.get("frames") or [])
        name = str(clip.get("name") or "")
        if not name or not frames:
            raise StudioError("every clip needs a name and at least one frame")
        if any(len(frame) != len(bones) for frame in frames):
            raise StudioError(f"clip {name!r}: every frame needs one matrix for each of the {len(bones)} bones")
        if clip.get("loop"):
            frames.append(frames[0])  # close the loop: the last key is the first again
        times = [i / fps for i in range(len(frames))]
        t_in = push(times, "SCALAR", 0.0, times[-1])
        samplers, channels = [], []
        for b, bone in enumerate(bones):
            j = names[bone]
            moves, turns, last = [], [], None
            for frame in frames:
                skinning = _flip(_mul(_from_cols(frame[b]), unrest[b]))
                t, q, _ = _trs(_mul(skinning, stand[j]))
                if last is not None and sum(x * y for x, y in zip(q, last)) < 0:
                    q = tuple(-x for x in q)  # the short way round between two keys
                last = q
                moves += t
                turns += q
            for path, values, kind in (("translation", moves, "VEC3"), ("rotation", turns, "VEC4")):
                samplers.append({"input": t_in, "output": push(values, kind), "interpolation": "LINEAR"})
                channels.append({"sampler": len(samplers) - 1, "target": {"node": joints[j], "path": path}})
        animations.append({"name": name, "samplers": samplers, "channels": channels})
        report.append({"name": name, "label": clip.get("label", ""), "seconds": round(times[-1], 3), "frames": len(frames)})
    if not animations:
        raise StudioError("the samples hold no clip")
    doc["animations"] = animations
    doc["buffers"][0]["byteLength"] = len(out_blob)
    doc["buffers"][0].pop("uri", None)
    _write_glb(Path(out), doc, bytes(out_blob))
    return {"clips": report, "unsampled": unsampled, "scale": scale}
