"""The notes box: who a note waits on, which session it goes to, and when a session is handed it.

The user types notes on the page whenever a thought comes. Nothing polls for them. Claude Code's
hooks (tool/hook.py) run this at the points where a session can take something in: when it finishes
a turn, and between tool calls once a note has waited a while. With nothing waiting it costs a
session no tokens at all.

A note is one file, notes/N-0001.json (the store writes them). Its status says where it stands:

    new      nobody has read it yet                          waits on a session, any one
    confirm  a session said what it takes the note to mean   waits on the user
    go       to be worked in                                 waits on the session it was sent to
    talk     a discussion                                    waits on whoever did not speak last
    later    an idea kept for when the next stretch is planned
    done, parked

Kept free of the store, so the hook stays quick. What was handed to whom is under live/, and is not
history.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

KINDS = ("directive", "bug", "discussion", "options", "rule", "later")
STATUS = ("new", "confirm", "go", "talk", "later", "done", "parked")
CONFIRMED = ("directive", "rule")  # the user confirms what a session took these to mean before anything changes
OPEN = ("new", "confirm", "go", "talk")
SAID = {"directive": "a change to make", "bug": "something broken", "discussion": "something to talk through",
        "options": "something to see options for", "rule": "a standing rule", "later": "an idea for later"}
AFTER = 600    # seconds a note waits before it is handed to a session in the middle of its work
RETRY = 1200   # a note handed over and not acted on is handed over again after this long
TRIES = 3      # and no more often than this while it stays as it is
SESSION_GONE = 6 * 3600


def _read(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _epoch(iso: str) -> float:
    import calendar
    try:
        return calendar.timegm(time.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return 0.0


def load(home) -> list:
    out = []
    for path in sorted(Path(home, "notes").glob("N-*.json")):
        note = _read(path, None)
        if isinstance(note, dict) and note.get("id"):
            out.append(note)
    return out


def waits(note: dict) -> str:
    """Who the note waits on: 'you' (the user), 'claude', or '' when nothing waits on it."""
    status = note.get("status")
    if status in ("new", "go"):
        return "claude"
    if status == "confirm":
        return "you"
    if status == "talk":
        thread = note.get("thread") or []
        return "you" if thread and thread[-1].get("who") == "claude" else "claude"
    return ""


def key(note: dict) -> str:
    """Changes whenever the note does: a session is handed each state of a note once."""
    return f"{note.get('status')}:{note.get('kind') or ''}:{len(note.get('thread') or [])}:{note.get('updated') or ''}"


def alive(home) -> dict:
    """The sessions of the project that are open now, by id (from what the hooks keep)."""
    out, now = {}, time.time()
    for path in Path(home, "live").glob("*.json"):
        rec = _read(path, None)
        if not isinstance(rec, dict) or "state" not in rec or rec.get("state") == "ended":
            continue
        if now - _epoch(rec.get("updated") or "") > SESSION_GONE:
            continue
        out[rec.get("id") or path.stem] = rec
    return out


def lanes(home) -> dict:
    rows = (_read(Path(home, "overview", "lanes.json"), {}) or {}).get("lanes") or []
    return {r.get("id"): r for r in rows if isinstance(r, dict)}


def route(note: dict, lane_rows: dict, sessions: dict) -> str:
    """The session a note waits on: its id, '*' for whichever session comes first, '' when none is there to take it."""
    if waits(note) != "claude":
        return ""
    status = note.get("status")
    if status == "new":
        return "*"
    if status == "talk":  # the session that was in the conversation, while it is still open
        return note["session"] if note.get("session") in sessions else "*"
    if note.get("anyone"):
        return "*"
    to = (lane_rows.get(note["lane"]) or {}).get("session") if note.get("lane") else note.get("session")
    return to if to in sessions else ""


def _locked(home, fn):
    """Run fn on what was handed to whom, alone: two sessions can reach a break in the same moment."""
    live = Path(home, "live")
    live.mkdir(exist_ok=True)
    ignore = live / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# what sessions are doing right now: not history\n*\n", encoding="utf-8")
    lock, path = live / "notes.lock", live / "notes.json"
    held = False
    for _ in range(80):
        try:
            os.mkdir(lock)
            held = True
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 5:
                    os.rmdir(lock)
            except OSError:
                pass
            time.sleep(0.025)
        except OSError:
            break
    if not held:
        return None
    try:
        data = _read(path, {})
        data = data if isinstance(data, dict) else {}
        out = fn(data)
        _write(path, data)
        return out
    finally:
        try:
            os.rmdir(lock)
        except OSError:
            pass


def told(home) -> dict:
    """Per note: the session it was last handed to, and when."""
    return (_read(Path(home, "live", "notes.json"), {}) or {}).get("told") or {}


def _after(home) -> float:
    """[notes] after_minutes in studio.toml: how long a note waits before it interrupts work in progress."""
    try:
        import tomllib
        with open(Path(home, "studio.toml"), "rb") as fh:
            return max(0.0, float((tomllib.load(fh).get("notes") or {}).get("after_minutes", AFTER / 60))) * 60
    except (OSError, ValueError, TypeError, ImportError):
        return AFTER


def _waiting(home) -> list:
    """Every note that waits on a session. Read again only when the notes folder changed, or a minute passed."""
    folder = Path(home, "notes")
    try:
        stamp = folder.stat().st_mtime_ns
    except OSError:
        return []
    cache = Path(home, "live", "notes-waiting.json")
    seen = _read(cache, {})
    if isinstance(seen, dict) and seen.get("stamp") == stamp and time.time() - float(seen.get("at") or 0) < 60:
        return seen.get("notes") or []
    rows = [n for n in load(home) if waits(n) == "claude"]
    try:
        _write(cache, {"stamp": stamp, "at": time.time(), "notes": rows})
    except OSError:
        pass
    return rows


def due(home, session: str, midwork: bool = False, mark: bool = True) -> list:
    """The notes to hand to this session now. Each is marked as handed over, so no other session takes it too."""
    rows = _waiting(home)
    if not rows:
        return []
    lane_rows, sessions, now = lanes(home), alive(home), time.time()
    mine = [n for n in rows if route(n, lane_rows, sessions) in ("*", session)]
    if midwork and mine:
        limit = _after(home)
        mine = [n for n in mine if n.get("urgent") or now - _epoch(n.get("updated") or "") >= limit]
    if not mine:
        return []

    def take(data: dict) -> list:
        book, out = data.setdefault("told", {}), []
        for note in mine:
            was = book.get(note["id"]) or {}
            if was.get("key") == key(note) and (int(was.get("n") or 0) >= TRIES or now - float(was.get("at") or 0) < RETRY):
                continue
            out.append(note)
            if mark:
                book[note["id"]] = {"key": key(note), "session": session, "at": now,
                                    "n": int(was.get("n") or 0) + 1 if was.get("key") == key(note) else 1}
        for nid in [n for n in book if now - float(book[n].get("at") or 0) > 30 * 86400]:
            del book[nid]
        return out

    if not mark:
        return take({"told": dict(told(home))})
    return _locked(home, take) or []


def command(home) -> str:
    tool = Path(__file__).resolve().parents[1] / "studio.py"
    return f'py -3.11 "{tool}" --home "{home}"' if sys.platform == "win32" else f'"{sys.executable}" "{tool}" --home "{home}"'


def _quote(text: str) -> str:
    return "\n".join("      > " + line for line in str(text or "").strip().splitlines() or [""])


def wording(notes: list, home, lane_rows: dict | None = None, midwork: bool = False) -> str:
    """What a session is told, complete in itself: a session that never read the skill can still act on it."""
    s = command(home)
    new = [n for n in notes if n.get("status") == "new"]
    go = [n for n in notes if n.get("status") == "go"]
    talk = [n for n in notes if n.get("status") == "talk"]
    count = len(notes)
    out = [f"The user left {count} note{'s' if count != 1 else ''} for you in the project's Studio. They type these on its page "
           "while you work; this is how the notes reach you, and nothing else will deliver them. "
           + ("Deal with them at the next sensible point in what you are doing, then carry on with it."
              if midwork else "Deal with them now, before you stop.")
           + " Their words are quoted exactly; never paraphrase them in what you record.",
           "", f"S is: {s}", ""]
    if new:
        out += [f"TO SORT ({len(new)}): nobody has read these yet. For each one, say what kind of note it is and what you take it to mean.", ""]
        for n in new:
            head = f"  {n['id']}" + ("  URGENT" if n.get("urgent") else "")
            if n.get("kind"):
                head += f"  (the user marked it: {SAID.get(n['kind'], n['kind'])}; sort it as `{n['kind']}`)"
            out += [head, _quote(n.get("text"))]
            for m in n.get("thread") or []:
                out.append(f"      {'They' if m.get('who') == 'you' else 'You'} then said: {m.get('text')}")
            if n.get("reading"):
                out.append(f"      An earlier reading, which they sent back: {n['reading']}")
            out.append("")
        out += ["  The kinds, and what each sets off:",
                "    directive   an order to change something. Say exactly what you will change; they confirm on the page",
                "                before anything is done. Do NOT make the change now.",
                "    rule        a standing rule for every future session. Say the rule as you will record it; they confirm.",
                "    bug         something is broken. No confirmation is needed: it is to be fixed.",
                "    options     a complaint about feel or look with no exact answer in it. Variants get built and filed as a batch.",
                "    later       an idea that asks for nothing now. It is kept, and comes back when the next stretch is planned.",
                "    discussion  a question, or a point they want to talk through. You sort it by answering it (below).",
                "",
                f"    S note sort <id> --kind directive|rule|bug|options|later --reading \"<what you take it to mean, plainly>\" \\",
                "           [--mine | --lane <lane id>]",
                f"    S note reply <id> \"<your answer>\"          a discussion: answer what they asked, with what you found",
                f"    S note split <id> \"<part of their words, exact>\"   one note that holds two things: prints a new id for that part",
                "",
                "  --reading is shown to them under \"Claude takes this to mean\": the change or the rule itself, in a sentence",
                "  or two, with the names and numbers it touches. Nothing about what happens next.",
                "  --mine: the work is in the part of the project you are on, and you will do it. --lane <id>: it belongs to",
                "  another piece of work on the board. Neither: no session is on that part, and the page will say so.",
                "  If you sorted a bug or options as --mine, it is yours to do now (as under TO DO)."]
        if lane_rows:
            out.append("  Work on the board now: " + "; ".join(f"{lid} ({r.get('name') or lid})" for lid, r in lane_rows.items()))
        out.append("")
    if go:
        out += [f"TO DO ({len(go)}): these were sent to you. A directive or a rule here is one the user has confirmed.", ""]
        for n in go:
            out += [f"  {n['id']}  {n.get('kind')}" + ("  URGENT" if n.get("urgent") else ""), _quote(n.get("text"))]
            if n.get("reading"):
                out.append(f"      Taken to mean: {n['reading']}")
            for m in n.get("thread") or []:
                out.append(f"      {'They' if m.get('who') == 'you' else 'You'} said: {m.get('text')}")
            out.append("")
        out += ["  Do each one, then close it with what was done, in a sentence they can read on the page:",
                f"    S note done <id> --result \"<what was done>\" [--ref <commit, or the batch id for options>]",
                "  directive, bug: make the change, test it, commit it. Closing a directive or a rule records it as a decision",
                "  in their words. rule: also write it where the project's sessions read their instructions.",
                "  options: build two or three variants and file them as a batch; --ref is the batch id.",
                f"  If it cannot or should not be done, say why and leave it with them: S note done <id> --parked --result \"<why>\"",
                ""]
    if talk:
        out += [f"TO ANSWER ({len(talk)}): a discussion where the user spoke last.", ""]
        for n in talk:
            out += [f"  {n['id']}" + ("  URGENT" if n.get("urgent") else ""), _quote(n.get("text"))]
            for m in n.get("thread") or []:
                out.append(f"      {'They' if m.get('who') == 'you' else 'You'}: {m.get('text')}")
            out.append("")
        out += [f"    S note reply <id> \"<your answer>\"",
                "  Answer what was asked, with what you looked up to answer it. Do not change the project because of a",
                "  discussion: when it turns into something to do, they will say so on the page.", ""]
    out.append("When you have dealt with them, go back to what you were doing. Do not ask the user in chat about these notes; "
               "they read your answers on the page.")
    return "\n".join(out)
