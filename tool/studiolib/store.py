"""The Studio store.

Every record is a plain file under one folder, the studio home. Nothing here
needs a database, a network or a package outside the standard library.

    <home>/
      studio.toml                 settings the user may edit
      batches/<id>/batch.json     what was asked, the candidates, how each was made
      batches/<id>/files/...      the candidate files
      batches/<id>/draft.json     the user's verdict while they are still judging
      batches/<id>/verdict.json   the user's verdict, once they press Submit
      batches/<id>/result.json    what was done with the verdict
      slots/<slot>.json           one per thing the game needs (a model, a sound...)
      library/<slot>/v<n>/...     the approved masters, with where they came from
      decisions/decisions.jsonl   every ruling, in the user's words, append only
      playtests/triage.json       what happened to each playtest note
      overview/roadmap.json       the milestones, each with its steps
      overview/now.json           the goal, the current build, what is next
      overview/hands.json         what waits on the user: things to do and questions to answer
      notes/N-<n>.json            what the user typed into the notes box, and what became of each (notes.py)
      overview/lanes.json, events.jsonl, days.json    work in progress, the log, a snapshot a day (board.py)
      live/<session>.json         what each Claude Code session is doing now (tool/hook.py); not history
      motions/<id>.glb            a character with its motions baked in as clips, by the game itself
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import notes as notebox

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

SCHEMA = 1
KINDS = ("image", "texture", "model", "audio", "video", "text", "ingame", "question", "mixed")
MODES = ("pick", "rate", "question")
CALLS = {
    "pick": ("winner", "keep", "redo", "reject"),
    "rate": ("approve", "redo", "reject"),
    "question": ("winner",),
}
ACTIONS = {
    "pick": ("ship", "ship_and_iterate", "another_round", "park"),
    "rate": ("ship", "ship_and_iterate", "another_round", "park"),
    "question": ("answer", "park"),
}
SLOT_STATUS = ("needed", "placeholder", "in_review", "approved", "in_game", "parked")
TRIAGE_STATUS = ("open", "planned", "fixed", "wontfix", "question")
MILESTONE_STATUS = ("done", "current", "next", "later", "parked")
HAND_STATUS = ("open", "later", "done", "parked")  # later: the user's, but nothing waits on it yet
HAND_KINDS = ("action", "decision", "play", "info")  # something to do, a question to answer, a build to try, a thing to know
# how the user likes the page: one answer for every Studio here (STUDIO_PREFS names another file, for a test)
PREFS = Path(os.environ.get("STUDIO_PREFS") or Path(__file__).resolve().parents[2] / "ui.json")
NOTE_KINDS, NOTE_CONFIRMED = notebox.KINDS, notebox.CONFIRMED
SAMPLE = "sample-"  # a batch id that starts so is made-up: kept under samples/, never counted or acted on

EXT_KIND = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image",
    ".glb": "model", ".gltf": "model",
    ".wav": "audio", ".ogg": "audio", ".mp3": "audio", ".flac": "audio",
    ".mp4": "video", ".webm": "video",
    ".md": "text", ".txt": "text",
}

DEFAULT_CONFIG = {
    "project": "Untitled game",
    "game_repo": "",
    "port": 8770,
    "review": {"max_candidates": 6, "max_open_batches": 8},
    "checks": {
        "audio": {"max_peak_dbfs": -20.0, "max_seconds": 3.0, "sample_width_bits": 16},
        "model": {"max_triangles": 5000},
        "texture": {"max_size": 2048, "power_of_two": True},
        "image": {"min_width": 512},
        "file": {"max_mb": 64},
    },
    "recipes": {},
    "playtests": {"dirs": []},
    "notes": {"after_minutes": 10},
}


class StudioError(Exception):
    """A problem the person at the keyboard can fix; the message says how."""


def iso_now() -> str:
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def today() -> str:
    return datetime.date.today().isoformat()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "item"


def read_json(path: Path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as err:
        raise StudioError(f"{path}: not valid JSON ({err})") from err


def write_json(path: Path, data) -> None:
    """Write whole and at once: a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def file_kind(path: str, batch_kind: str = "") -> str:
    kind = EXT_KIND.get(Path(path).suffix.lower(), "file")
    if kind == "image" and batch_kind == "texture":
        return "texture"
    return kind


def safe_id(text: str, what: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", text or ""):
        raise StudioError(f"{what} {text!r}: use letters, digits, dot, dash and underscore only")
    return text


class Studio:
    def __init__(self, home):
        self.home = Path(home).resolve()
        if not self.home.is_dir():
            raise StudioError(f"studio home {self.home} does not exist; run: studio.py init {self.home}")
        self.batches_dir = self.home / "batches"
        self.slots_dir = self.home / "slots"
        self.library_dir = self.home / "library"
        self.decisions_file = self.home / "decisions" / "decisions.jsonl"
        self.triage_file = self.home / "playtests" / "triage.json"
        self.overview_dir = self.home / "overview"
        self.notes_dir = self.home / "notes"
        self.motions_dir = self.home / "motions"
        self.samples_dir = self.home / "samples"
        self.config = self._load_config()

    # ------------------------------------------------------------------ setup
    @staticmethod
    def init(home, project: str = "", game_repo: str = "") -> "Studio":
        home = Path(home).resolve()
        for sub in ("batches", "slots", "library", "decisions", "playtests", "overview", "motions"):
            (home / sub).mkdir(parents=True, exist_ok=True)
        cfg = home / "studio.toml"
        if not cfg.exists():
            cfg.write_text(DEFAULT_TOML.format(project=project or "Untitled game",
                                               game_repo=game_repo.replace("\\", "/")),
                           encoding="utf-8", newline="\n")
        ignore = home / ".gitignore"
        if not ignore.exists():
            ignore.write_text("# drafts are the user's unfinished thoughts; everything else is history\n"
                              "draft.json\n*.tmp\n__pycache__/\n", encoding="utf-8", newline="\n")
        attrs = home / ".gitattributes"
        if not attrs.exists():
            attrs.write_text("* text=auto eol=lf\n"
                             "decisions/decisions.jsonl merge=union\n"
                             "*.glb binary\n*.wav binary\n*.png binary\n*.jpg binary\n*.mp4 binary\n",
                             encoding="utf-8", newline="\n")
        return Studio(home)

    def _load_config(self) -> dict:
        path = self.home / "studio.toml"
        if not path.exists():
            return merge(DEFAULT_CONFIG, {})
        if tomllib is None:
            raise StudioError("Python 3.11 or newer is needed to read studio.toml")
        try:
            with open(path, "rb") as fh:
                return merge(DEFAULT_CONFIG, tomllib.load(fh))
        except tomllib.TOMLDecodeError as err:
            raise StudioError(f"{path}: {err}") from err

    def game_root(self, override: str = "") -> Path | None:
        root = override or self.config.get("game_repo") or ""
        if not root:
            return None
        path = Path(root)
        return path if path.is_absolute() else (self.home / path).resolve()

    # ---------------------------------------------------------------- batches
    def batch_dir(self, batch_id: str) -> Path:
        name = safe_id(batch_id, "batch")
        return (self.samples_dir if name.startswith(SAMPLE) else self.batches_dir) / name

    def sample_ids(self) -> list[str]:
        """Made-up batches for trying the page on. No other listing holds them."""
        if not self.samples_dir.is_dir():
            return []
        return sorted(p.name for p in self.samples_dir.iterdir()
                      if p.name.startswith(SAMPLE) and (p / "batch.json").is_file())

    def batch_ids(self) -> list[str]:
        if not self.batches_dir.is_dir():
            return []
        return sorted(p.name for p in self.batches_dir.iterdir() if (p / "batch.json").is_file())

    def load_batch(self, batch_id: str) -> dict:
        folder = self.batch_dir(batch_id)
        batch = read_json(folder / "batch.json")
        if batch is None:
            raise StudioError(f"no batch {batch_id!r}; see: studio.py status")
        batch["verdict"] = read_json(folder / "verdict.json")
        batch["draft"] = read_json(folder / "draft.json")
        batch["result"] = read_json(folder / "result.json")
        batch["status"] = self._status(batch)
        return batch

    @staticmethod
    def _status(batch: dict) -> str:
        if batch.get("result"):
            return "processed"
        if batch.get("verdict"):
            return "submitted"
        if not batch.get("ready"):
            return "building"
        return "draft" if batch.get("draft") else "open"

    def save_batch(self, batch: dict) -> None:
        clean = {k: v for k, v in batch.items() if k not in ("verdict", "draft", "result", "status")}
        write_json(self.batch_dir(batch["id"]) / "batch.json", clean)

    def summary(self, batch: dict) -> dict:
        verdict = batch.get("verdict") or {}
        calls = {cid: (c or {}).get("call") for cid, c in (verdict.get("candidates") or {}).items()}
        thumb = None
        for cand in batch.get("candidates", []):
            for f in cand.get("files", []):
                if f.get("kind") in ("image", "texture"):
                    thumb = f["path"]
                    break
            if thumb:
                break
        return {
            "id": batch["id"], "title": batch.get("title", batch["id"]), "kind": batch.get("kind"),
            "sample": bool(batch.get("sample")), "order": batch.get("order", 0),
            "mode": batch.get("mode"), "slot": batch.get("slot"), "round": batch.get("round", 1),
            "parent": batch.get("parent"), "ask": batch.get("ask", ""), "status": batch["status"],
            "created": batch.get("created"), "filed": batch.get("filed"),
            "count": len(batch.get("candidates", [])), "thumb": thumb,
            "action": verdict.get("action"), "submitted": verdict.get("submitted"),
            "winners": [cid for cid, call in calls.items() if call in ("winner", "approve")],
            "processed": (batch.get("result") or {}).get("processed"),
            "next_batch": (batch.get("result") or {}).get("next_batch"),
            "problems": sum(1 for c in batch.get("candidates", [])
                            for chk in c.get("checks", []) if chk.get("level") in ("warn", "error")),
        }

    def new_batch(self, slug: str, *, title: str = "", kind: str = "", mode: str = "", slot: str = "",
                  ask: str = "", look_at: list[str] | None = None, brief: str = "", parent: str = "",
                  max_winners: int | None = None, targets: dict | None = None, dest: str = "",
                  steps: list[str] | None = None, launch: str = "", date: str = "",
                  filed_by: str = "", round_no: int = 0, sample: bool = False) -> dict:
        base: dict = {}
        if parent:
            base = self.load_batch(parent)
        round_no = round_no or (int(base.get("round", 1)) + 1 if parent else 1)
        kind = kind or base.get("kind") or ""
        if kind not in KINDS:
            raise StudioError(f"--kind must be one of: {', '.join(KINDS)}")
        mode = mode or base.get("mode") or ("question" if kind == "question" else "pick")
        if mode not in MODES:
            raise StudioError(f"--mode must be one of: {', '.join(MODES)}")
        batch_id = f"{date or today()}-{slugify(slug)}-r{round_no}"
        if sample:
            batch_id = SAMPLE + slugify(slug)
        elif batch_id.startswith(SAMPLE):
            raise StudioError(f"a batch id may not start with {SAMPLE!r}: that names a sample")
        folder = self.batch_dir(batch_id)
        if (folder / "batch.json").exists():
            raise StudioError(f"batch {batch_id} already exists")
        base_import = base.get("import") or {}
        batch = {
            "schema": SCHEMA,
            "id": batch_id,
            "title": title or (re.sub(r",? round \d+$", "", base.get("title", "")) + f", round {round_no}"
                               if base.get("title") else slug),
            "kind": kind,
            "mode": mode,
            "max_winners": max_winners if max_winners is not None else base.get("max_winners", 1),
            "slot": slot or base.get("slot", ""),
            "round": round_no,
            "parent": parent or None,
            "created": iso_now(),
            "filed": None,
            "filed_by": filed_by or "claude-code",
            "ready": False,
            "ask": ask or base.get("ask", ""),
            "look_at": look_at if look_at else base.get("look_at", []),
            "brief": brief or "",
            "targets": targets if targets else base.get("targets", {}),
            "launch": launch or base.get("launch", ""),
            "context": [],
            "candidates": [],
            "import": {"dest": dest or base_import.get("dest", ""),
                       "steps": steps if steps else base_import.get("steps", [])},
            "checks": [],
        }
        if sample:
            batch["sample"] = True
        (folder / "files").mkdir(parents=True, exist_ok=True)
        self.save_batch(batch)
        return batch

    def _editable(self, batch_id: str) -> dict:
        batch = self.load_batch(batch_id)
        if batch["status"] in ("submitted", "processed"):
            raise StudioError(f"batch {batch_id} is already judged; a change is a new round "
                              f"(studio.py new ... --parent {batch_id})")
        return batch

    def add_candidate(self, batch_id: str, files: list, *, cid: str = "", title: str = "",
                      summary: str = "", label: str = "", body: str = "", recommended: bool = False,
                      made_with: dict | None = None, slot: str = "", dest: str = "", motion: str = "") -> dict:
        batch = self._editable(batch_id)
        if motion:
            self.motion_ref(motion, sample=bool(batch.get("sample")))
        taken = {c["id"] for c in batch["candidates"]}
        if not cid:
            cid = next(ch for ch in "abcdefghijklmnopqrstuvwxyz" if ch not in taken)
        safe_id(cid, "candidate id")
        if cid in taken:
            raise StudioError(f"batch {batch_id} already has a candidate {cid!r}")
        folder = self.batch_dir(batch_id) / "files" / cid
        entries = []
        for src in files:
            src = Path(src)
            if not src.is_file():
                raise StudioError(f"{src}: no such file")
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, folder / src.name)
            entries.append({"path": f"files/{cid}/{src.name}", "kind": file_kind(src.name, batch["kind"]),
                            "label": src.stem.replace("_", " ")})
        self._assign_roles(entries, batch["kind"])
        cand = {"id": cid, "title": title or cid.upper(), "summary": summary, "files": entries,
                "made_with": made_with or {}, "facts": {}, "checks": []}
        if label:
            cand["label"] = label
        if body:
            cand["body"] = body
        if recommended:
            cand["recommended"] = True
        if slot:
            cand["slot"] = slot
        if dest:
            cand["dest"] = dest
        if motion:
            cand["motion"] = motion
        batch["candidates"].append(cand)
        batch["ready"] = False
        self.save_batch(batch)
        return cand

    @staticmethod
    def _assign_roles(entries: list, batch_kind: str) -> None:
        want = {"texture": "texture", "image": "image"}.get(batch_kind, batch_kind)
        primary = next((e for e in entries if e["kind"] == want), entries[0] if entries else None)
        for entry in entries:
            entry["role"] = "primary" if entry is primary else "extra"
        if primary and primary["kind"] not in ("image", "texture"):
            preview = next((e for e in entries if e["kind"] == "image"), None)
            if preview:
                preview["role"] = "preview"

    def carry(self, batch_id: str, from_batch: str, from_cid: str, cid: str = "") -> dict:
        """Bring a candidate the user liked into a later round, to judge new ones against."""
        source = self.load_batch(from_batch)
        old = next((c for c in source["candidates"] if c["id"] == from_cid), None)
        if old is None:
            raise StudioError(f"batch {from_batch} has no candidate {from_cid!r}")
        files = [self.batch_dir(from_batch) / f["path"] for f in old.get("files", [])]
        cand = self.add_candidate(batch_id, files, cid=cid, title=old.get("title", ""),
                                  summary=old.get("summary", ""), label=old.get("label", ""),
                                  body=old.get("body", ""), made_with=old.get("made_with"))
        batch = self.load_batch(batch_id)
        for c in batch["candidates"]:
            if c["id"] == cand["id"]:
                c["carried_from"] = f"{from_batch}/{from_cid}"
        self.save_batch(batch)
        return cand

    def add_context(self, batch_id: str, src, label: str = "") -> None:
        batch = self._editable(batch_id)
        src = Path(src)
        if not src.is_file():
            raise StudioError(f"{src}: no such file")
        folder = self.batch_dir(batch_id) / "files" / "_context"
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, folder / src.name)
        batch.setdefault("context", []).append({"path": f"files/_context/{src.name}",
                                                "kind": file_kind(src.name), "label": label or src.stem})
        self.save_batch(batch)

    def publish(self, batch_id: str, force: bool = False) -> dict:
        """Run the checks; a batch reaches the user's inbox only when none of them is an error."""
        from . import checks
        batch = self._editable(batch_id)
        report = checks.check_batch(self, batch)
        batch["ready"] = force or not report["errors"]
        if batch["ready"] and not batch.get("filed"):
            batch["filed"] = iso_now()
        self.save_batch(batch)
        if batch["ready"]:
            for slot_id in {batch.get("slot")} | {c.get("slot") for c in batch["candidates"]}:
                slot = self.slot(slot_id) if slot_id else None
                if slot and slot.get("status") in ("needed", "placeholder", "approved", "in_game"):
                    slot["previous_status"] = slot["status"]
                    slot["status"] = "in_review"
                    slot["open_batch"] = batch_id
                    self.save_slot(slot)
        report["ready"] = batch["ready"]
        return report

    # ---------------------------------------------------------------- verdicts
    def save_draft(self, batch_id: str, draft: dict) -> None:
        batch = self.load_batch(batch_id)
        if batch["status"] == "processed":
            raise StudioError("this batch is closed")
        write_json(self.batch_dir(batch_id) / "draft.json", self._clean_verdict(batch, draft, strict=False))

    def _clean_verdict(self, batch: dict, raw: dict, strict: bool) -> dict:
        mode = batch.get("mode", "pick")
        ids = [c["id"] for c in batch.get("candidates", [])]
        out_c = {}
        for cid, entry in (raw.get("candidates") or {}).items():
            if cid not in ids or not isinstance(entry, dict):
                continue
            call = entry.get("call") or None
            if call not in CALLS[mode]:
                call = None
            score = entry.get("score")
            score = int(score) if isinstance(score, (int, float)) and 1 <= int(score) <= 10 else None
            note = str(entry.get("note") or "").strip()
            if call or score or note:
                out_c[cid] = {"call": call, "score": score, "note": note}
        action = raw.get("action")
        if action not in ACTIONS[mode]:
            action = None
        verdict = {"schema": SCHEMA, "batch": batch["id"], "action": action,
                   "note": str(raw.get("note") or "").strip(),
                   "answer": str(raw.get("answer") or "").strip(), "candidates": out_c}
        if strict:
            problem = self.verdict_problem(batch, verdict)
            if problem:
                raise StudioError(problem)
        return verdict

    @staticmethod
    def verdict_problem(batch: dict, verdict: dict) -> str:
        mode = batch.get("mode", "pick")
        calls = [c.get("call") for c in verdict["candidates"].values()]
        chosen = sum(1 for c in calls if c in ("winner", "approve"))
        action = verdict.get("action")
        if not action:
            return "Choose what happens next before you submit."
        if mode == "question":
            if action == "answer" and not chosen and not verdict.get("answer"):
                return "Pick an option or write your own answer."
            return ""
        if action in ("ship", "ship_and_iterate") and not chosen:
            return "Nothing is marked to ship. Mark a winner, or choose another round."
        limit = int(batch.get("max_winners") or 1)
        if mode == "pick" and chosen > limit:
            return f"This batch takes {limit} winner{'s' if limit != 1 else ''}; {chosen} are marked."
        if action in ("another_round", "ship_and_iterate"):
            said = verdict.get("note") or any(c.get("note") or c.get("call") in ("keep", "redo")
                                              for c in verdict["candidates"].values())
            if not said:
                return "Another round needs a direction: write a note, or mark a Keep or a Redo."
        return ""

    def submit(self, batch_id: str, raw: dict) -> dict:
        batch = self.load_batch(batch_id)
        if batch["status"] == "processed":
            raise StudioError("this batch is closed; ask for a new round instead")
        if batch["status"] == "building":
            raise StudioError("this batch is not filed yet")
        verdict = self._clean_verdict(batch, raw, strict=True)
        verdict["submitted"] = iso_now()
        verdict["revision"] = int((batch.get("verdict") or {}).get("revision", 0)) + 1
        folder = self.batch_dir(batch_id)
        write_json(folder / "verdict.json", verdict)
        with open(folder / "verdicts.log.jsonl", "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(verdict, ensure_ascii=False) + "\n")  # the user's words are never lost
        draft = folder / "draft.json"
        if draft.exists():
            draft.unlink()
        return verdict

    def reopen(self, batch_id: str) -> None:
        batch = self.load_batch(batch_id)
        if batch["status"] != "submitted":
            raise StudioError("only a submitted verdict that has not been acted on can be reopened")
        folder = self.batch_dir(batch_id)
        write_json(folder / "draft.json", {k: batch["verdict"].get(k) for k in
                                            ("schema", "batch", "action", "note", "answer", "candidates")})
        (folder / "verdict.json").unlink()

    def reset_sample(self, batch_id: str) -> None:
        """Start a sample over: the user's marks on it are thrown away. Only a sample can lose a verdict."""
        batch = self.load_batch(batch_id)
        if not batch.get("sample"):
            raise StudioError("only a sample can be started over; a real verdict is changed, never erased")
        for name in ("draft.json", "verdict.json", "verdicts.log.jsonl", "next-round-brief.md"):
            (self.batch_dir(batch_id) / name).unlink(missing_ok=True)

    # ------------------------------------------------------------------ slots
    def slots(self) -> list[dict]:
        if not self.slots_dir.is_dir():
            return []
        out = [read_json(p) for p in sorted(self.slots_dir.glob("*.json"))]
        return [s for s in out if s]

    def slot(self, slot_id: str) -> dict | None:
        return read_json(self.slots_dir / (safe_id(slot_id, "slot") + ".json"))

    def save_slot(self, slot: dict) -> None:
        if slot.get("status") not in SLOT_STATUS:
            raise StudioError(f"slot status must be one of: {', '.join(SLOT_STATUS)}")
        write_json(self.slots_dir / (safe_id(slot["id"], "slot") + ".json"), slot)

    def set_slot(self, slot_id: str, **fields) -> dict:
        slot = self.slot(slot_id) or {"schema": SCHEMA, "id": slot_id, "title": slot_id, "kind": "",
                                      "group": "", "status": "needed", "game_path": "", "notes": "",
                                      "current": None, "history": []}
        for key, value in fields.items():
            if value not in (None, ""):
                slot[key] = value
        self.save_slot(slot)
        return slot

    def adopt(self, slot_id: str, files: list, *, title: str = "", note: str = "", source: str = "",
              date: str = "", score: int | None = None, status: str = "approved") -> dict:
        """Bring in a master the user approved before the Studio existed. No batch, no verdict: the
        provenance says where it came from and that it predates the Studio."""
        slot = self.slot(slot_id)
        if slot is None:
            raise StudioError(f"no slot {slot_id!r}; make it first: studio.py slot set {slot_id} ...")
        version = int((slot.get("current") or {}).get("version", 0)) + 1
        lib = self.library_dir / slot_id / f"v{version}"
        paths = [Path(f) for f in files]
        for src in paths:
            if not src.is_file():
                raise StudioError(f"{src}: no such file")
        lib.mkdir(parents=True, exist_ok=True)
        for src in paths:
            shutil.copy2(src, lib / src.name)
        rel = lib.relative_to(self.home).as_posix()
        write_json(lib / "provenance.json", {
            "slot": slot_id, "version": version, "batch": None, "predates_studio": True, "source": source,
            "title": title or slot.get("title", ""), "score": score, "his_note": note, "approved": date})
        picture = next((p.name for p in paths if file_kind(p.name) == "image"), None)
        current = {"version": version, "batch": None, "candidate": None, "title": title or slot.get("title", ""),
                   "score": score, "date": date, "library": rel, "thumb": f"{rel}/{picture}" if picture else None,
                   "note": note, "source": source}
        slot.setdefault("history", []).append(current)
        slot["current"] = current
        slot["status"] = status
        self.save_slot(slot)
        return slot

    # -------------------------------------------------------------- decisions
    def decisions(self) -> list[dict]:
        if not self.decisions_file.exists():
            return []
        out = []
        with open(self.decisions_file, "r", encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as err:
                    raise StudioError(f"{self.decisions_file}:{n}: {err}") from err
        # the log is append only: a later ruling retires an earlier one by naming it
        by_name = {}
        for record in out:
            by_name[record.get("id")] = record
            if record.get("legacy"):
                by_name[record["legacy"]] = record
        for record in out:
            for name in record.get("supersedes") or []:
                old = by_name.get(name)
                if old is not None and old is not record:
                    old["status"] = "superseded"
                    old["superseded_by"] = record["id"]
        return out

    def add_decision(self, *, title: str, his_words: str = "", ruling: str = "", source_type: str = "chat",
                     ref: str = "", tags: list[str] | None = None, supersedes: list[str] | None = None,
                     legacy: str = "", date: str = "", status: str = "active") -> dict:
        if not title.strip():
            raise StudioError("a decision needs a title")
        existing = self.decisions()
        numbers = [int(m.group(1)) for d in existing if (m := re.fullmatch(r"D-(\d+)", d.get("id", "")))]
        record = {"id": f"D-{(max(numbers) if numbers else 0) + 1:04d}", "date": date or today(),
                  "title": title.strip(), "ruling": ruling.strip(), "his_words": his_words.strip(),
                  "source": {"type": source_type, "ref": ref}, "tags": tags or [],
                  "supersedes": supersedes or [], "status": status}
        if legacy:
            record["legacy"] = legacy
        self.decisions_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.decisions_file, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    # ---------------------------------------------------- the queue for Claude
    def todo(self) -> list[dict]:
        """Every verdict the user has submitted that nobody has acted on yet."""
        items = []
        for batch_id in self.batch_ids():
            batch = self.load_batch(batch_id)
            if batch["status"] == "submitted":
                items.append(self._todo_item(batch))
        items.sort(key=lambda i: i["submitted"] or "")
        return items

    def _todo_item(self, batch: dict) -> dict:
        verdict = batch["verdict"]
        by_call: dict[str, list] = {}
        for cand in batch["candidates"]:
            entry = verdict["candidates"].get(cand["id"]) or {}
            row = {"candidate": cand["id"], "title": cand.get("title", ""), "label": cand.get("label", ""),
                   "score": entry.get("score"), "note": entry.get("note", ""),
                   "files": [f["path"] for f in cand.get("files", [])]}
            by_call.setdefault(entry.get("call") or "unmarked", []).append(row)
        action = verdict["action"]
        me = "python tool/studio.py"
        winners = by_call.get("winner", []) + by_call.get("approve", [])
        steps = []
        if batch["mode"] == "question":
            if action == "answer":
                steps.append("The user's answer is a ruling. Apply it where it belongs (spec, content, TODO).")
            else:
                steps.append("The user parked the question: change nothing, ask again only when they say so.")
        else:
            if action in ("ship", "ship_and_iterate"):
                names = ", ".join(w["candidate"] for w in winners)
                if batch["kind"] == "ingame":
                    steps.append(f"Record the user's pick ({names}) on its slot; there is no file to copy: "
                                 f"{me} import {batch['id']}")
                else:
                    steps.append(f"Copy the winner ({names}) into the library and the game: "
                                 f"{me} import {batch['id']}")
                recipe = (self.config.get("recipes") or {}).get(batch["kind"]) or {}
                steps += list(recipe.get("steps") or [])
                steps += list((batch.get("import") or {}).get("steps") or [])
                steps.append("Build, run the fast tier, and commit the game change.")
            if action in ("another_round", "ship_and_iterate"):
                steps.append(f"Read batches/{batch['id']}/next-round-brief.md "
                             f"({me} brief {batch['id']} writes it), make the next candidates from it, "
                             f"and file them: {me} new <slug> --parent {batch['id']}")
                if by_call.get("keep"):
                    kept = ", ".join(k["candidate"] for k in by_call["keep"])
                    steps.append(f"Carry what the user kept ({kept}) into the new round so they can compare: "
                                 f"{me} carry <new batch> {batch['id']} <candidate>")
            if action == "park":
                steps.append("The user parked it: make nothing more for this slot until they say so.")
        steps.append(f"Close it: {me} done {batch['id']} --ruling \"<what this settles, one sentence>\" "
                     f"[--commit <sha>] [--next <new batch id>] [--in-game]")
        return {
            "batch": batch["id"], "title": batch.get("title", ""), "kind": batch["kind"], "mode": batch["mode"],
            "slot": batch.get("slot", ""), "action": action, "submitted": verdict.get("submitted"),
            "his_note": verdict.get("note", ""), "his_answer": verdict.get("answer", ""),
            "winners": winners, "keep": by_call.get("keep", []), "redo": by_call.get("redo", []),
            "reject": by_call.get("reject", []), "unmarked": by_call.get("unmarked", []),
            "import": batch.get("import") or {}, "steps": steps,
        }

    def brief(self, batch_id: str) -> str:
        """What the next round's makers are told: the old ask plus everything the user said."""
        batch = self.load_batch(batch_id)
        verdict = batch.get("verdict")
        if not verdict:
            raise StudioError(f"batch {batch_id} has no submitted verdict yet")
        lines = [f"# Next round brief: {batch.get('title', batch_id)}", "",
                 f"From batch `{batch_id}` (round {batch.get('round', 1)}), judged {verdict.get('submitted', '')}.",
                 "The user's words below are quoted exactly. Do not paraphrase them into the prompt; act on them.", ""]
        lines += ["## What the user was asked", "", batch.get("ask", "") or "(no ask recorded)", ""]
        if batch.get("look_at"):
            lines += ["## What the user was told to look at", ""] + [f"- {x}" for x in batch["look_at"]] + [""]
        if batch.get("targets"):
            lines += ["## Hard targets", ""] + [f"- {k}: {v}" for k, v in batch["targets"].items()] + [""]
        if verdict.get("note"):
            lines += ["## The user's note on the whole batch", "", "> " + verdict["note"].replace("\n", "\n> "), ""]
        order = [("winner", "Winner"), ("approve", "Approved"), ("keep", "Keep: more in this direction"),
                 ("redo", "Redo: right idea, fix what the user says"), ("reject", "Rejected: do not go here again"),
                 (None, "Not marked")]
        for call, heading in order:
            rows = [(c, verdict["candidates"].get(c["id"]) or {}) for c in batch["candidates"]]
            rows = [(c, e) for c, e in rows if (e.get("call") or None) == call]
            if not rows:
                continue
            lines += [f"## {heading}", ""]
            for cand, entry in rows:
                score = f" · {entry['score']}/10" if entry.get("score") else ""
                lines.append(f"### {cand['id']}: {cand.get('title', '')}{score}")
                if entry.get("note"):
                    lines += ["", "> " + entry["note"].replace("\n", "\n> ")]
                made = cand.get("made_with") or {}
                if made:
                    lines += ["", "Made with: " + json.dumps(made, ensure_ascii=False)]
                lines.append("")
        if batch.get("brief"):
            lines += ["## The brief the last round was made from", "", batch["brief"], ""]
        text = "\n".join(lines).rstrip() + "\n"
        (self.batch_dir(batch_id) / "next-round-brief.md").write_text(text, encoding="utf-8", newline="\n")
        return text

    def import_batch(self, batch_id: str, game: str = "", dry_run: bool = False, again: bool = False) -> list[dict]:
        """Copy each winner to the library (the master) and into the game repo."""
        batch = self.load_batch(batch_id)
        if batch.get("sample"):
            raise StudioError(f"{batch_id} is a sample: nothing in it is imported, recorded or acted on")
        verdict = batch.get("verdict")
        folder = self.batch_dir(batch_id)
        if not verdict:
            raise StudioError(f"batch {batch_id} has no submitted verdict")
        if verdict.get("action") not in ("ship", "ship_and_iterate"):
            raise StudioError(f"the user's verdict on {batch_id} is {verdict.get('action')!r}: there is nothing to import")
        if (folder / "import.json").exists() and not (again or dry_run):
            raise StudioError(f"batch {batch_id} was imported already; pass --again to copy it a second time")
        game_root = self.game_root(game)
        winners: dict[str, list] = {}
        for cand in batch["candidates"]:
            entry = verdict["candidates"].get(cand["id"]) or {}
            if entry.get("call") in ("winner", "approve"):
                winners.setdefault(cand.get("slot") or batch.get("slot") or "", []).append((cand, entry))
        done = []
        for slot_id, group in winners.items():
            slot = self.slot(slot_id) if slot_id else None
            if slot_id and slot is None:
                slot = self.set_slot(slot_id, title=batch.get("title", slot_id), kind=batch["kind"])
            version = (int((slot.get("current") or {}).get("version", 0)) + 1) if slot else 1
            thumb = None
            for cand, entry in group:
                row = {"candidate": cand["id"], "slot": slot_id, "version": version, "library": "", "dest": []}
                sources = [folder / f["path"] for f in cand.get("files", [])]
                primary = next((folder / f["path"] for f in cand.get("files", []) if f.get("role") == "primary"),
                               sources[0] if sources else None)
                if slot_id and sources:
                    # two winners for one slot share a version, each in a folder of its own
                    lib = self.library_dir / slot_id / f"v{version}"
                    if len(group) > 1:
                        lib = lib / cand["id"]
                    row["library"] = lib.relative_to(self.home).as_posix()
                    if not dry_run:
                        lib.mkdir(parents=True, exist_ok=True)
                        for src in sources:
                            shutil.copy2(src, lib / src.name)
                        write_json(lib / "provenance.json", {
                            "slot": slot_id, "version": version, "batch": batch_id, "candidate": cand["id"],
                            "title": cand.get("title", ""), "made_with": cand.get("made_with") or {},
                            "facts": cand.get("facts") or {}, "score": entry.get("score"),
                            "his_note": entry.get("note", ""), "approved": verdict.get("submitted")})
                    picture = next((f["path"] for f in cand.get("files", []) if f.get("kind") in ("image", "texture")), None)
                    if picture and not thumb:
                        thumb = f"{row['library']}/{Path(picture).name}"
                dest = cand.get("dest") or (batch.get("import") or {}).get("dest") or ""
                if dest and primary is not None:
                    if game_root is None:
                        row["dest_skipped"] = "no game_repo in studio.toml and no --game given"
                    else:
                        root = game_root.resolve()
                        target = (root / dest).resolve()
                        if not target.is_relative_to(root):
                            raise StudioError(f"import dest {dest!r} leaves the game repo")
                        as_dir = dest.endswith("/") or (len(sources) > 1 and not Path(dest).suffix)
                        for src in (sources if as_dir else [primary]):
                            out = target / src.name if as_dir else target
                            row["dest"].append(out.relative_to(root).as_posix())
                            if not dry_run:
                                out.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(src, out)
                done.append(row)
            if slot and not dry_run:
                first_cand, first_entry = group[0]
                rows = [r for r in done if r["slot"] == slot_id]
                current = {"version": version, "batch": batch_id, "candidate": first_cand["id"],
                           "candidates": [c["id"] for c, _ in group],
                           "title": " + ".join(c.get("title", c["id"]) for c, _ in group),
                           "score": max((e.get("score") or 0 for _, e in group), default=0) or None,
                           "date": verdict.get("submitted"),
                           "library": (self.library_dir / slot_id / f"v{version}").relative_to(self.home).as_posix()
                           if any(r["library"] for r in rows) else "",
                           "thumb": thumb}
                slot.setdefault("history", []).append(current)
                slot["current"] = current
                slot["status"] = "approved"
                slot.pop("open_batch", None)
                dests = [d for r in rows for d in r["dest"]]
                if dests and not slot.get("game_path"):
                    slot["game_path"] = dests[0]
                self.save_slot(slot)
        if not dry_run:
            write_json(folder / "import.json", {"imported": done, "at": iso_now()})
        return done

    def mark_done(self, batch_id: str, *, ruling: str = "", commit: str = "", next_batch: str = "",
                  note: str = "", in_game: bool = False, by: str = "claude-code") -> dict:
        batch = self.load_batch(batch_id)
        if batch.get("sample"):
            raise StudioError(f"{batch_id} is a sample: nothing in it is imported, recorded or acted on")
        verdict = batch.get("verdict")
        if not verdict:
            raise StudioError(f"batch {batch_id} has no submitted verdict to close")
        if batch.get("result"):
            raise StudioError(f"batch {batch_id} is already closed")
        folder = self.batch_dir(batch_id)
        action = verdict["action"]
        imported = (read_json(folder / "import.json") or {}).get("imported", [])
        if action in ("ship", "ship_and_iterate") and batch["mode"] != "question" and not imported:
            raise StudioError(f"the user's verdict ships a winner, but nothing was imported: "
                              f"run studio.py import {batch_id} first")
        if next_batch and not (self.batch_dir(next_batch) / "batch.json").exists():
            raise StudioError(f"--next {next_batch}: no such batch")
        # one decision per verdict, the user's words kept exactly
        words = []
        if verdict.get("answer"):
            words.append(verdict["answer"])
        if verdict.get("note"):
            words.append(verdict["note"])
        titles = {c["id"]: c.get("title", "") for c in batch["candidates"]}
        chosen = []
        for cid, entry in verdict["candidates"].items():
            call = entry.get("call")
            if call in ("winner", "approve"):
                chosen.append(cid)
            if entry.get("note"):
                score = f" {entry['score']}/10" if entry.get("score") else ""
                words.append(f"[{cid}: {titles.get(cid, '')}, {call or 'no call'}{score}] {entry['note']}")
        outcome = {"ship": "picked", "ship_and_iterate": "picked, and another round", "answer": "answered",
                   "another_round": "another round", "park": "parked"}[action]
        picked = ", ".join(f"{c} ({titles.get(c, '')})" for c in chosen)
        title = f"{re.sub(r',? round [0-9]+$', '', batch.get('title', batch_id))}: {outcome}" + (f": {picked}" if picked else "")
        decision = self.add_decision(title=title, his_words="\n".join(words), ruling=ruling,
                                     source_type="question" if batch["mode"] == "question" else "batch",
                                     ref=batch_id, tags=[t for t in (batch["kind"], batch.get("slot", "")) if t])
        result = {"processed": iso_now(), "by": by, "action": action, "imported": imported,
                  "next_batch": next_batch or None, "commit": commit or None,
                  "decision": decision["id"], "note": note}
        write_json(folder / "result.json", result)
        won = {r["slot"] for r in imported if r.get("slot")}
        touched = won | {batch.get("slot")} | {c.get("slot") for c in batch["candidates"]}
        for slot_id in sorted(t for t in touched if t):
            slot = self.slot(slot_id)
            if not slot:
                continue
            if action in ("ship", "ship_and_iterate") and slot_id not in won:
                # judged in this batch but not approved: on to the next round if the user said redo, else back to what it was
                calls = {(verdict["candidates"].get(c["id"]) or {}).get("call") for c in batch["candidates"]
                         if (c.get("slot") or batch.get("slot")) == slot_id}
                again = next_batch and (calls & {"redo", "keep"} or slot_id == batch.get("slot"))
                slot["status"] = "in_review" if again else slot.get("previous_status", "placeholder")
                if not again:
                    slot.pop("open_batch", None)
                    self.save_slot(slot)
                    continue
            elif action == "park":
                slot["status"] = "parked"
            elif action in ("ship", "ship_and_iterate"):
                slot["status"] = "in_game" if in_game else "approved"
            elif action == "another_round":
                slot["status"] = "in_review" if next_batch else slot.get("previous_status", "placeholder")
            if next_batch:
                slot["open_batch"] = next_batch
            else:
                slot.pop("open_batch", None)
            self.save_slot(slot)
        return result

    # -------------------------------------------------------------- playtests
    def playtest_dirs(self) -> list[Path]:
        out = []
        for raw in (self.config.get("playtests") or {}).get("dirs") or []:
            path = Path(os.path.expandvars(os.path.expanduser(raw)))
            out.append(path if path.is_absolute() else (self.home / path).resolve())
        return out

    def triage(self) -> dict:
        return read_json(self.triage_file, {}) or {}

    def set_triage(self, key: str, **fields) -> dict:
        data = self.triage()
        entry = data.get(key) or {"status": "open"}
        for k, v in fields.items():
            if v is not None:
                entry[k] = v
        if entry.get("status") not in TRIAGE_STATUS:
            raise StudioError(f"triage status must be one of: {', '.join(TRIAGE_STATUS)}")
        entry["updated"] = iso_now()
        data[key] = entry
        write_json(self.triage_file, data)
        return entry

    def playtests(self) -> list[dict]:
        triage = self.triage()
        sessions = []
        for index, root in enumerate(self.playtest_dirs()):
            if not root.is_dir():
                continue
            for folder in sorted(root.iterdir(), reverse=True):
                if not folder.is_dir():
                    continue
                reports = sorted((p for p in folder.iterdir() if p.is_dir() and re.fullmatch(r"f8-\d+", p.name)),
                                 key=lambda p: int(p.name.split("-")[1]))
                if not reports and not (folder / "results.json").exists():
                    continue
                sessions.append(self._session(index, folder, reports, triage))
        sessions.sort(key=lambda s: s["name"], reverse=True)
        return sessions

    @staticmethod
    def _session(index: int, folder: Path, reports: list, triage: dict) -> dict:
        name = folder.name
        m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+?)(?:-(cs-[\w-]+|[A-Za-z][\w]*-(?:desktop|laptop)))?$", name)
        session = {"name": name, "root": index, "date": m.group(1) if m else "",
                   "build": m.group(2) if m else name, "machine": (m.group(3) or "") if m else "",
                   "checklist": [], "sliders": {}, "end_note": "", "reports": []}
        results = {}
        try:
            raw = read_json(folder / "results.json", {}) or {}
            rows = raw.get("items", raw) if isinstance(raw, dict) else raw
            if isinstance(rows, dict):
                rows = [dict(v, id=k) if isinstance(v, dict) else {"id": k, "result": v} for k, v in rows.items()]
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict) and row.get("id"):
                    results[str(row["id"])] = str(row.get("result") or row.get("state") or row.get("status") or "untested")
        except StudioError:
            pass
        checklist = folder / "checklist.toml"
        if checklist.exists() and tomllib is not None:
            try:
                with open(checklist, "rb") as fh:
                    data = tomllib.load(fh)
                for part in ("new", "affected"):
                    for item in data.get(part) or []:
                        if isinstance(item, dict):
                            iid = str(item.get("id", ""))
                            session["checklist"].append({"id": iid, "part": part,
                                                         "feature": item.get("feature", iid),
                                                         "result": results.get(iid, "untested")})
            except (tomllib.TOMLDecodeError, OSError):
                pass
        if not session["checklist"]:
            session["checklist"] = [{"id": k, "part": "new", "feature": k, "result": v} for k, v in results.items()]
        try:
            sliders = read_json(folder / "sliders.json", {}) or {}
            if isinstance(sliders, dict) and isinstance(sliders.get("sliders"), list):
                # the game's own shape: the end screen's ratings as a list, and what the player wrote there
                session["sliders"] = {str(row.get("label")): row.get("value") for row in sliders["sliders"]
                                      if isinstance(row, dict) and row.get("label")}
                session["end_note"] = str(sliders.get("text") or "").strip()
            elif isinstance(sliders, dict):
                session["sliders"] = {k: v for k, v in sliders.items() if isinstance(v, (int, float))}
        except StudioError:
            pass
        for rep in reports:
            note = ""
            if (rep / "note.txt").exists():
                note = (rep / "note.txt").read_text(encoding="utf-8", errors="replace").strip()
            try:
                stats = read_json(rep / "stats.json", {}) or {}
            except StudioError:
                stats = {}
            shot = next((p.name for p in sorted(rep.iterdir())
                         if p.suffix.lower() in (".png", ".jpg", ".jpeg")), None)
            key = f"{name}/{rep.name}"
            session["reports"].append({"id": rep.name, "key": key, "note": note, "screenshot": shot,
                                       "has_log": (rep / "log.txt").exists(),
                                       "stats": stats if isinstance(stats, dict) else {},
                                       "triage": triage.get(key) or {"status": "open"}})
        return session

    def playtest_file(self, root_index: int, rel: str) -> Path:
        roots = self.playtest_dirs()
        if not 0 <= root_index < len(roots):
            raise StudioError("no such playtest folder")
        root = roots[root_index].resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise StudioError("no such file")
        return path

    # ---------------------------------------------------------------- motions
    def motions(self) -> dict:
        return read_json(self.motions_dir / "index.json", {}) or {}

    def set_motion(self, mid: str, src, sample: bool = False) -> dict:
        """Keep a character's baked motions: one .glb, the model with a clip for each motion,
        written by the game's own code so the page shows what the game draws."""
        from .checks import model_facts
        src = Path(src)
        if not src.is_file() or src.suffix.lower() != ".glb":
            raise StudioError(f"{src}: give the baked .glb")
        try:
            facts = model_facts(src)
        except Exception as err:
            raise StudioError(f"{src}: could not read the model ({err})") from err
        if not facts.get("clips"):
            raise StudioError(f"{src} holds no animation clip: bake the motions into it first")
        self.motions_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, self.motions_dir / (safe_id(mid, "motion set") + ".glb"))
        index = self.motions()
        index[mid] = {"file": f"motions/{mid}.glb", "clips": facts["clips"], "height_m": facts.get("height_m"),
                      "triangles": facts.get("triangles"), "source": str(src), "updated": iso_now()}
        if sample:
            index[mid]["sample"] = True
        write_json(self.motions_dir / "index.json", index)
        return index[mid]

    def motion_ref(self, ref: str, sample: bool = False) -> tuple[str, str]:
        """`<motion set>:<clip>`, checked against what was baked."""
        mid, _, clip = (ref or "").partition(":")
        entry = self.motions().get(mid)
        if entry is not None and entry.get("sample") and not sample:
            raise StudioError(f"{mid} is made-up motion for the samples, not the game's: it goes on no real batch or slot")
        if entry is None:
            raise StudioError(f"no baked motions {mid!r}; bake them and run: studio.py motion set {mid or '<id>'} <file.glb>")
        names = [c["name"] for c in entry["clips"]]
        if clip not in names:
            raise StudioError(f"{mid} has no clip {clip!r}; it has: {', '.join(names)}")
        return mid, clip

    def link_motion(self, batch_id: str, cid: str, ref: str) -> None:
        """Show a candidate's motion beside its label. It changes what the user sees, not what was asked."""
        batch = self.load_batch(batch_id)
        self.motion_ref(ref, sample=bool(batch.get("sample")))
        cand = next((c for c in batch["candidates"] if c["id"] == cid), None)
        if cand is None:
            raise StudioError(f"batch {batch_id} has no candidate {cid!r}")
        cand["motion"] = ref
        self.save_batch(batch)

    # --------------------------------------------------------------- overview
    def roadmap(self) -> list[dict]:
        return (read_json(self.overview_dir / "roadmap.json", {}) or {}).get("milestones", [])

    def set_milestone(self, mid: str, **fields) -> dict:
        rows = self.roadmap()
        row = next((r for r in rows if r["id"] == mid), None)
        if row is None:
            row = {"id": safe_id(mid, "milestone"), "name": mid, "status": "later", "goal": "",
                   "question": "", "note": ""}
            rows.append(row)
        for key, value in fields.items():
            if value not in (None, ""):
                row[key] = value
        if row.get("status") not in MILESTONE_STATUS:
            raise StudioError(f"milestone status must be one of: {', '.join(MILESTONE_STATUS)}")
        if "weight" in row:
            try:
                row["weight"] = float(row["weight"])
            except (TypeError, ValueError):
                raise StudioError("a milestone's weight is a number: 1 for an ordinary one, 2 for one twice the work") from None
        row["updated"] = iso_now()
        write_json(self.overview_dir / "roadmap.json", {"schema": SCHEMA, "milestones": rows})
        return row

    def now(self) -> dict:
        return read_json(self.overview_dir / "now.json", {}) or {}

    def set_now(self, **fields) -> dict:
        """What the current build is and what comes next. A list given replaces the old one."""
        data = self.now()
        for key, value in fields.items():
            if value in (None, "", []):
                continue
            data[key] = value
        data["updated"] = iso_now()
        write_json(self.overview_dir / "now.json", data)
        return data

    def hands(self) -> list[dict]:
        return (read_json(self.overview_dir / "hands.json", {}) or {}).get("items", [])

    def _save_hands(self, rows: list) -> None:
        write_json(self.overview_dir / "hands.json", {"schema": SCHEMA, "items": rows})

    def _hand(self, rows: list, hid: str) -> dict:
        row = next((r for r in rows if r["id"] == hid), None)
        if row is None:
            raise StudioError(f"no hand {hid!r}; see: studio.py hand list")
        return row

    def set_hand(self, hid: str, **fields) -> dict:
        """One thing only the user can do: try a build, run a check on another machine, sign a paper."""
        rows = self.hands()
        row = next((r for r in rows if r["id"] == hid), None)
        if row is None:
            row = {"id": safe_id(hid, "hand"), "title": hid, "detail": "", "gates": "", "time": "",
                   "run": "", "status": "open", "created": iso_now()}
            rows.append(row)
        for key, value in fields.items():
            if value not in (None, ""):
                row[key] = value
        if row.get("status") not in HAND_STATUS:
            raise StudioError(f"hand status must be one of: {', '.join(HAND_STATUS)}")
        if row.setdefault("kind", "action") not in HAND_KINDS:
            raise StudioError(f"an ask is one of: {', '.join(HAND_KINDS)}")
        row["urgent"] = bool(row.get("urgent"))
        row["updated"] = iso_now()
        self._save_hands(rows)
        return row

    def close_hand(self, hid: str, answer: str) -> dict:
        """The user answered somewhere else (in chat, say): their words go on the ask and it is closed."""
        rows = self.hands()
        row = self._hand(rows, hid)
        row.update(status="done", his_note=answer.strip(), answered=iso_now(), seen=True, updated=iso_now())
        self._save_hands(rows)
        return row

    def answer_hand(self, hid: str, action: str, note: str = "") -> dict:
        """The user's own word from the page: done, parked, or open again. Claude reads it in `todo`."""
        status = {"done": "done", "park": "parked", "reopen": "open"}.get(action)
        if not status:
            raise StudioError("say done, park or reopen")
        rows = self.hands()
        row = self._hand(rows, hid)
        row.update(status=status, his_note=note.strip(), answered=iso_now(), seen=False, updated=iso_now())
        self._save_hands(rows)
        return row

    def see_hand(self, hid: str) -> dict:
        rows = self.hands()
        row = self._hand(rows, hid)
        row["seen"] = True
        self._save_hands(rows)
        return row

    def unseen_hands(self) -> list[dict]:
        return [r for r in self.hands() if r.get("answered") and not r.get("seen")]

    # ------------------------------------------------------------ the notes box
    def notes(self) -> list[dict]:
        return notebox.load(self.home)

    def note(self, nid: str) -> dict:
        note = read_json(self.notes_dir / f"{safe_id(nid, 'note')}.json")
        if not isinstance(note, dict):
            raise StudioError(f"no note {nid!r}; see: studio.py note list")
        return note

    def _save_note(self, note: dict) -> dict:
        note["updated"] = iso_now()
        write_json(self.notes_dir / f"{note['id']}.json", note)
        return note

    @staticmethod
    def _say(note: dict, who: str, text: str) -> None:
        note.setdefault("thread", []).append({"who": who, "at": iso_now(), "text": text.strip()})

    def add_note(self, text: str, *, kind: str = "", urgent: bool = False, parent: str = "") -> dict:
        """What the user typed, as they typed it. A kind they chose themselves stands; otherwise a session sorts it."""
        if not text.strip():
            raise StudioError("a note needs some words")
        if kind and kind not in NOTE_KINDS:
            raise StudioError(f"a note is one of: {', '.join(NOTE_KINDS)}")
        numbers = [int(m.group(1)) for p in self.notes_dir.glob("N-*.json") if (m := re.fullmatch(r"N-(\d+)", p.stem))]
        note = {"id": f"N-{(max(numbers) if numbers else 0) + 1:04d}", "text": text.strip(), "created": iso_now(),
                "kind": kind, "kind_by": "you" if kind else "", "status": "later" if kind == "later" else "new",
                "urgent": bool(urgent), "reading": "", "thread": []}
        if parent:
            note["from"] = parent
        return self._save_note(note)

    def sort_note(self, nid: str, kind: str, *, reading: str = "", lane: str = "", session: str = "") -> dict:
        """A session says what kind of note this is and what it takes it to mean."""
        note = self.note(nid)
        if note["status"] != "new":
            raise StudioError(f"{nid} is already sorted ({note['kind']}, {note['status']})")
        if kind not in NOTE_KINDS:
            raise StudioError(f"a note is one of: {', '.join(NOTE_KINDS)}")
        if note.get("kind_by") == "you" and kind != note["kind"]:
            raise StudioError(f"the user marked {nid} as {note['kind']} themselves; sort it as that")
        if kind == "discussion":
            raise StudioError("a discussion is sorted by answering it: studio.py note reply <id> \"<your answer>\"")
        if kind != "later" and not reading.strip():
            raise StudioError("say what you take it to mean: --reading \"...\"")
        if lane:
            from . import board
            if not any(r["id"] == lane for r in board.lanes(self)):
                raise StudioError(f"no lane {lane!r} on the board; see: studio.py lane list")
        note.update(kind=kind, reading=reading.strip(), lane=lane, session="" if lane else session, anyone=False,
                    status="later" if kind == "later" else "confirm" if kind in NOTE_CONFIRMED else "go")
        return self._save_note(note)

    def split_note(self, nid: str, text: str) -> dict:
        """One note that holds two things: the part named becomes a note of its own, in the user's words."""
        note = self.note(nid)
        squash = lambda t: " ".join(t.split()).lower()  # noqa: E731
        if squash(text) not in squash(note["text"]):
            raise StudioError(f"the part must be the user's own words, as they stand in {nid}")
        return self.add_note(text, urgent=bool(note.get("urgent")), parent=nid)

    def reply_note(self, nid: str, text: str, *, session: str = "") -> dict:
        """A session's answer in a discussion. Answering a note nobody has sorted makes it a discussion."""
        note = self.note(nid)
        if not text.strip():
            raise StudioError("a reply needs some words")
        if note["status"] == "new" and note.get("kind_by") == "you" and note["kind"] != "discussion":
            raise StudioError(f"the user marked {nid} as {note['kind']} themselves; sort it as that")
        if note["status"] not in ("new", "talk"):
            raise StudioError(f"{nid} is not a discussion ({note['kind']}, {note['status']})")
        self._say(note, "claude", text)
        note.update(kind="discussion", status="talk", session=session or note.get("session") or "")
        return self._save_note(note)

    def close_note(self, nid: str, *, result: str, ref: str = "", parked: bool = False) -> dict:
        """A session did what the note asked, or says why it will not be done. A directive or a rule goes on the record."""
        note = self.note(nid)
        if note["status"] in ("done", "parked"):
            raise StudioError(f"{nid} is already closed")
        if note["status"] == "confirm":
            raise StudioError(f"{nid} waits on the user to confirm what it means; nothing is done on it before that")
        if not result.strip():
            raise StudioError("say what was done: --result \"...\"")
        note.update(status="parked" if parked else "done", result=result.strip(), ref=ref, closed=iso_now(), closed_by="claude")
        if not parked and note.get("kind") in NOTE_CONFIRMED and not note.get("decision"):
            words = "\n".join([note["text"]] + [m["text"] for m in note.get("thread") or [] if m.get("who") == "you"])
            note["decision"] = self.add_decision(title=note.get("reading") or note["text"], his_words=words, ruling=result,
                                                 source_type="note", ref=nid, tags=["rule"] if note["kind"] == "rule" else [])["id"]
        return self._save_note(note)

    def answer_note(self, nid: str, action: str, *, text: str = "", kind: str = "", session: str = "") -> dict:
        """The user's own word on a note, from the page."""
        note, text = self.note(nid), text.strip()
        status = note["status"]
        if action == "confirm":
            if status != "confirm":
                raise StudioError("there is nothing to confirm on that note")
            if text:
                self._say(note, "you", text)
            note["status"] = "go"
        elif action == "back":  # not what they meant: a session reads it again, with what they added
            if status != "confirm":
                raise StudioError("there is nothing to send back on that note")
            if not text:
                raise StudioError("say what you meant instead")
            self._say(note, "you", text)
            note["status"] = "new"
        elif action == "reply":
            if status not in ("talk", "go", "new"):
                raise StudioError("that note is not open for a reply")
            if not text:
                raise StudioError("write your reply first")
            self._say(note, "you", text)
        elif action == "kind":  # the user sorts it themselves, or says a session sorted it wrong
            if kind not in NOTE_KINDS:
                raise StudioError(f"a note is one of: {', '.join(NOTE_KINDS)}")
            if status in ("done", "parked"):
                raise StudioError("that note is closed; open it again first")
            note.update(kind=kind, kind_by="you", reading="", lane="", session="", anyone=False,
                        status="later" if kind == "later" else "new")
        elif action == "send":  # to a session by hand, or to whichever comes first
            if status != "go":
                raise StudioError("only a note that is to be worked in can be sent to a session")
            note.update(lane="", session=session, anyone=not session)
        elif action == "urgent":
            note["urgent"] = not note.get("urgent")
        elif action in ("park", "done"):
            if status in ("done", "parked"):
                raise StudioError("that note is already closed")
            note.update(status="parked" if action == "park" else "done", closed=iso_now(), closed_by="you")
        elif action == "reopen":
            if status not in ("done", "parked", "later"):
                raise StudioError("that note is open already")
            if text:
                self._say(note, "you", text)
            talk = note.get("kind") == "discussion" and bool(note.get("thread")) and note["thread"][-1]["who"] == "you"
            if note.get("kind") == "later":
                note.update(kind="", kind_by="")
            note["status"] = "talk" if talk else "new"
        else:
            raise StudioError("say confirm, back, reply, kind, send, urgent, park, done or reopen")
        return self._save_note(note)

    def notes_view(self) -> list[dict]:
        """Every note, with who it waits on and the session it is with, as the page shows it."""
        lane_rows, sessions, told = notebox.lanes(self.home), notebox.alive(self.home), notebox.told(self.home)

        def name(sid: str) -> str:
            rec = sessions.get(sid) or {}
            return rec.get("title") or rec.get("prompt") or "a session"

        def stamp(at: float) -> str:
            when = datetime.datetime.fromtimestamp(at, datetime.timezone.utc).replace(microsecond=0)
            return when.isoformat().replace("+00:00", "Z")

        out = []
        for note in self.notes():
            to, was = notebox.route(note, lane_rows, sessions), told.get(note["id"]) or {}
            handed = was if was.get("key") == notebox.key(note) and was.get("session") in sessions else None
            out.append(dict(note, waits=notebox.waits(note), to=to,
                            to_name=(lane_rows.get(note.get("lane")) or {}).get("name") or (name(to) if to not in ("", "*") else ""),
                            handed={"session": handed["session"], "name": name(handed["session"]), "at": stamp(handed["at"])} if handed else None))
        return out

    _GIT_CACHE: dict = {}

    def game_git(self) -> dict:
        """The game repo as git sees it: branch, version, the last commits. Read only."""
        root = self.game_root()
        if root is None or not (root / ".git").exists():
            return {}
        updated = self.now().get("updated") or ""
        try:
            key = (str(root), (root / ".git" / "logs" / "HEAD").stat().st_mtime_ns, updated)
        except OSError:
            key = (str(root), 0, updated)
        if Studio._GIT_CACHE.get("key") == key:
            return Studio._GIT_CACHE["value"]

        def git(*args) -> str:
            try:
                out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=8,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.SubprocessError):
                return ""
            return out.stdout.decode("utf-8", errors="replace").strip() if out.returncode == 0 else ""

        commits = []
        for line in git("log", "-n", "12", "--no-merges", "--format=%h%x1f%cI%x1f%s").splitlines():
            parts = line.split("\x1f")
            if len(parts) == 3:
                commits.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})
        count = git("rev-list", "--count", "--no-merges", f"--since={updated}", "HEAD") if updated else ""
        try:
            version = (root / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            version = ""
        value = {"branch": git("rev-parse", "--abbrev-ref", "HEAD"), "head": git("rev-parse", "--short", "HEAD"),
                 "version": version, "commits": commits, "since_now": int(count) if count.isdigit() else 0}
        Studio._GIT_CACHE.update(key=key, value=value)
        return value

    def overview(self) -> dict:
        from . import board, setup
        hooks = bool(setup.hooks_installed())
        return {"now": self.now(), "game": self.game_git(), "milestones": self.roadmap(), "hands": self.hands(),
                "board": board.view(self), "live": board.live(self), "hooks": hooks, "hooks_notes": setup.hooks_hand_over(),
                "setup": board.checklist(self, hooks)}

    # ------------------------------------------------- the files behind a slot
    def game_file(self, rel: str) -> Path:
        """A file of the game repo the user may look at or hear from the Library. Media only."""
        root = self.game_root()
        if root is None:
            raise StudioError("no game_repo in studio.toml")
        root = root.resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in EXT_KIND:
            raise StudioError("no such file")
        return path

    def slot_files(self, slot: dict) -> list[dict]:
        """What the user can open for a slot: the approved master, and what the game holds today.
        `game_path` is a file, a folder or a glob (content/audio/*/step_*.wav)."""
        out = []
        kind = slot.get("kind", "")
        cur = slot.get("current") or {}
        lib = (self.home / cur["library"]) if cur.get("library") else None
        if lib and lib.is_dir():
            for p in sorted(lib.rglob("*")):
                if p.is_file() and p.suffix.lower() in EXT_KIND:
                    out.append({"url": "/" + p.relative_to(self.home).as_posix(), "kind": file_kind(p.name, kind),
                                "label": p.stem.replace("_", " "), "from": "library"})
        root = self.game_root()
        pattern = slot.get("game_path") or ""
        if root is not None and pattern and ".." not in pattern and not Path(pattern).is_absolute():
            root = root.resolve()
            hits = sorted(root.glob(pattern)) if any(ch in pattern for ch in "*?[") else [root / pattern]
            files = []
            for hit in hits:
                files += sorted(hit.rglob("*")) if hit.is_dir() else [hit]
            for p in files:
                if len(out) >= 80:
                    break
                if p.is_file() and p.suffix.lower() in EXT_KIND:
                    rel = p.relative_to(root).as_posix()
                    out.append({"url": "/game/" + rel, "kind": file_kind(p.name, kind), "label": rel, "from": "game"})
        return out

    # ------------------------------------------------- the record, kept in git
    def _git(self, *args, timeout: int = 30):
        try:
            return subprocess.run(["git", "-C", str(self.home), *args], capture_output=True, timeout=timeout,
                                  text=True, encoding="utf-8", errors="replace",
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError) as err:
            raise StudioError(f"git did not run: {err}") from err

    def unsaved(self) -> int | None:
        """How many files in the home differ from its last commit. None: the home keeps no history."""
        if not (self.home / ".git").exists():
            return None
        out = self._git("status", "--porcelain")
        return len([line for line in out.stdout.splitlines() if line.strip()]) if out.returncode == 0 else None

    def save(self, message: str = "") -> dict:
        """Commit everything in the home and push it: what the user judged and ruled, and what was filed for them."""
        if not (self.home / ".git").exists():
            raise StudioError(f"{self.home} keeps no history yet: run `git init` in it once")
        if self.unsaved():  # the index carries the time it was written: rewrite it only beside real changes
            self.write_index()
        changed = [line[3:].strip().strip('"') for line in self._git("status", "--porcelain").stdout.splitlines() if line.strip()]
        out = {"files": len(changed), "commit": "", "pushed": False, "note": ""}
        if changed:
            areas: dict[str, int] = {}
            for path in changed:
                top = path.split("/")[0] if "/" in path else "the home"
                areas[top] = areas.get(top, 0) + 1
            subject = message.strip() or "Studio: " + ", ".join(f"{n} in {a}" for a, n in sorted(areas.items(), key=lambda kv: -kv[1])[:6])
            added = self._git("add", "-A")
            done = added if added.returncode else self._git("commit", "-q", "-m", subject)
            if done.returncode:
                raise StudioError(f"the commit failed: {(done.stderr or done.stdout).strip()}")
            out["commit"] = self._git("rev-parse", "--short", "HEAD").stdout.strip()
        remotes = self._git("remote").stdout.split()
        if not remotes:
            out["note"] = "no remote is set, so nothing was pushed"
            return out
        tracked = self._git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").returncode == 0
        branch = self._git("branch", "--show-current").stdout.strip()
        remote = "origin" if "origin" in remotes else remotes[0]
        push = self._git("push", timeout=180) if tracked else self._git("push", "-u", remote, branch, timeout=180)
        out["pushed"] = push.returncode == 0
        if not out["pushed"]:
            out["note"] = "the push failed: " + ((push.stderr or push.stdout).strip().splitlines() or ["no reason given"])[-1]
        return out

    # ---------------------------------------------- how the user likes the page
    @staticmethod
    def ui() -> dict:
        return read_json(PREFS, {}) or {}

    def set_ui(self, scale=None, theme=None) -> dict:
        """The page's size and theme, kept beside the tool so every Studio and window opens the way the user left it."""
        ui = self.ui()
        if scale is not None:
            try:
                ui["scale"] = round(min(2.0, max(0.75, float(scale))), 2)
            except (TypeError, ValueError) as err:
                raise StudioError("scale is a number, 1 for the page as drawn") from err
        if theme is not None:
            if theme not in ("dark", "light"):
                raise StudioError("theme is dark or light")
            ui["theme"] = theme
        write_json(PREFS, ui)
        return ui

    # ------------------------------------------------------------------ views
    def _shown(self, ids: list[str]) -> tuple[list, list]:
        batches, held = [], []
        for batch_id in ids:
            batch = self.load_batch(batch_id)
            if batch["status"] != "building":
                batches.append(self.summary(batch))
                continue
            # made, checked and refused: the user is told it exists, and why they were not shown it
            errors = [c["msg"] for c in batch.get("checks", []) if c.get("level") == "error"]
            errors += [f"{cand['id']}: {c['msg']}" for cand in batch.get("candidates", [])
                       for c in cand.get("checks", []) if c.get("level") == "error"]
            if errors:
                held.append({"id": batch_id, "title": batch.get("title", batch_id), "kind": batch.get("kind"),
                             "errors": errors})
        return batches, held

    def state(self) -> dict:
        batches, held = self._shown(self.batch_ids())
        batches.sort(key=lambda b: b.get("filed") or b.get("created") or "", reverse=True)
        samples, samples_held = self._shown(self.sample_ids())
        samples.sort(key=lambda b: b["order"])
        return {"project": self.config.get("project"), "home": str(self.home), "static": False,
                "limits": self.config.get("review"), "batches": batches, "held": held,
                "samples": samples, "samples_held": samples_held, "ui": self.ui(),
                "slots": [dict(s, files=self.slot_files(s)) for s in self.slots()],
                "decisions": self.decisions(), "playtests": self.playtests(), "overview": self.overview(),
                "has_playtests": bool(self.playtest_dirs()), "motions": self.motions(),
                "notes": self.notes_view(), "stamp": self.stamp()}

    def stamp(self) -> str:
        """Changes whenever anything the user could see changes; the page polls it."""
        parts = []
        for folder in ([self.batches_dir] + [self.batches_dir / b for b in self.batch_ids()] +
                       [self.samples_dir] + [self.samples_dir / b for b in self.sample_ids()] +
                       [self.slots_dir, self.decisions_file.parent, self.triage_file.parent, self.overview_dir,
                        self.motions_dir, self.notes_dir]):
            try:
                for p in folder.iterdir():
                    if p.is_file() and p.suffix in (".json", ".jsonl"):
                        st = p.stat()
                        parts.append(f"{p.name}:{st.st_mtime_ns}:{st.st_size}")
            except OSError:
                continue
        for root in self.playtest_dirs():
            try:
                parts.append(f"{root}:{root.stat().st_mtime_ns}:{sum(1 for _ in root.iterdir())}")
            except OSError:
                continue
        try:  # a note handed to a session shows as handed over
            st = (self.home / "live" / "notes.json").stat()
            parts.append(f"told:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            pass
        root = self.game_root()
        if root is not None:  # a commit in the game repo moves the overview
            try:
                st = (root / ".git" / "logs" / "HEAD").stat()
                parts.append(f"game:{st.st_mtime_ns}:{st.st_size}")
            except OSError:
                pass
        import hashlib
        return hashlib.sha1("|".join(sorted(parts)).encode()).hexdigest()[:16]

    def write_index(self) -> list[Path]:
        """Plain-text views for people and agents who would rather read than click."""
        state = self.state()
        waiting = [b for b in state["batches"] if b["status"] in ("open", "draft")]
        pending = [b for b in state["batches"] if b["status"] == "submitted"]
        lines = [f"# {state['project']}: studio index", "", f"Written {iso_now()} by `studio.py index`. Do not edit.", "",
                 f"## Waiting on the user ({len(waiting)})", ""]
        lines += [f"- `{b['id']}`: {b['title']} ({b['kind']}, {b['count']} candidates)" for b in waiting] or ["- nothing"]
        lines += ["", f"## Waiting on Claude ({len(pending)})", ""]
        lines += [f"- `{b['id']}`: {b['title']}: {b['action']}" for b in pending] or ["- nothing"]
        lines += ["", "## Slots", "", "| Slot | Kind | Status | Current | In the game at |", "|---|---|---|---|---|"]
        for s in sorted(state["slots"], key=lambda s: (s.get("group", ""), s["id"])):
            cur = s.get("current") or {}
            lines.append(f"| `{s['id']}` | {s.get('kind', '')} | {s.get('status', '')} | "
                         f"{('v' + str(cur.get('version')) + ' from ' + str(cur.get('batch'))) if cur else ''} | "
                         f"{s.get('game_path', '')} |")
        index = self.home / "INDEX.md"
        index.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        dl = [f"# {state['project']}: decisions", "",
              "Newest first. The user's words are quoted exactly. Written by `studio.py index`; "
              "the record is `decisions/decisions.jsonl`.", ""]
        for d in reversed(state["decisions"]):
            head = f"## {d['id']}" + (f" ({d['legacy']})" if d.get("legacy") else "") + f": {d['title']}"
            dl += [head, "", f"{d.get('date', '')} · {d.get('status', 'active')} · "
                   f"{(d.get('source') or {}).get('type', '')} {(d.get('source') or {}).get('ref', '')}".rstrip(), ""]
            if d.get("his_words"):
                dl += ["> " + d["his_words"].replace("\n", "\n> "), ""]
            if d.get("ruling"):
                dl += [d["ruling"], ""]
        dec = self.home / "decisions" / "DECISIONS.md"
        dec.parent.mkdir(parents=True, exist_ok=True)
        dec.write_text("\n".join(dl) + "\n", encoding="utf-8", newline="\n")
        return [index, dec]


DEFAULT_TOML = '''# Studio settings. Edit freely; the tool reads this file on every start.

project = "{project}"

# Where approved assets are copied to. Forward slashes work on Windows.
game_repo = "{game_repo}"

port = 8770

[review]
max_candidates = 6      # per batch; past this, judging gets sloppy
max_open_batches = 8    # filing warns when the user's inbox is already this full

# A candidate that breaks a rule is flagged before the user ever sees it.
[checks.audio]
max_peak_dbfs = -20.0
max_seconds = 3.0
sample_width_bits = 16

[checks.model]
max_triangles = 5000

[checks.texture]
max_size = 2048
power_of_two = true

[checks.image]
min_width = 512

[checks.file]
max_mb = 64

# Folders the game writes playtest sessions into (each holds f8-<n>/ reports).
[playtests]
dirs = []

# The notes box: how long a note you typed waits before it is handed to a session in the middle
# of its work. A session that finishes a turn is handed it at once; an urgent note never waits.
[notes]
after_minutes = 10

# What "ship the winner" means for each kind of asset, as steps for Claude Code.
# studio.py todo prints them after the copy step.
[recipes.audio]
steps = []
[recipes.model]
steps = []
[recipes.texture]
steps = []
[recipes.image]
steps = []
[recipes.ingame]
steps = []
'''
