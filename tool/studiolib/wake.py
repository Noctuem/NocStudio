"""Waking a session that sits idle at the prompt, when the user says so: the Send verdicts button.

Claude Code runs `hook.py --wait` in the background as a session starts and each time it finishes a turn (an
`asyncRewake` hook, `studio.py hooks install` sets it up). The waiter does nothing until the user presses Send
verdicts for that session. The page then writes live/wake/<session>.go; the waiter prints what to tell the
session and exits 2, and Claude Code wakes the session with it, idle or not. Nothing else ever wakes a session:
no note, no verdict, no timer. A newer waiter for the same session replaces the older one, and each gives up
before Claude Code's timeout for it. A conversation the page itself runs (Talk) is told straight through its
own input instead.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

WAIT = 8 * 3600   # seconds: Claude Code's timeout for the waiter (hooks install); it stops itself before that
BEAT = 15         # seconds between a waiter's signs of life, so the page knows which sessions it can wake
POLL = 1.0
IDLE = ("waiting", "background")  # a session at the prompt; one that is working gets its verdicts when its turn ends


def folder(home) -> Path:
    return Path(home) / "live" / "wake"


def clean(session: str) -> str:
    return "".join(c for c in str(session or "") if c.isalnum() or c in "-_")[:80]


def _state(home, session: str) -> str:
    try:
        with open(Path(home) / "live" / f"{session}.json", "r", encoding="utf-8") as fh:
            return str(json.load(fh).get("state") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def wait(home, session: str) -> bool:
    """In the waiter: True once the user presses Send verdicts for this session; False to stop quietly
    (a newer waiter took over, the session ended, or it waited as long as it may)."""
    session = clean(session)
    if not session:
        return False
    d = folder(home)
    d.mkdir(parents=True, exist_ok=True)
    me, tag, go = f"{os.getpid()}:{time.time()}", d / f"{session}.wait", d / f"{session}.go"
    tag.write_text(me, encoding="utf-8")
    end, beat = time.time() + WAIT - 120, time.time()
    try:
        while time.time() < end:
            try:
                if tag.read_text(encoding="utf-8") != me:
                    return False  # a newer waiter for this session has it now
            except OSError:
                return False
            if go.exists():
                go.unlink(missing_ok=True)
                return True
            if time.time() - beat >= BEAT:
                beat = time.time()
                if _state(home, session) == "ended":
                    return False
                os.utime(tag)
            time.sleep(POLL)
        return False
    finally:
        try:
            if tag.read_text(encoding="utf-8") == me:
                tag.unlink()
        except OSError:
            pass


def awake(home) -> set[str]:
    """The sessions whose waiter is alive now."""
    d, now = folder(home), time.time()
    out = set()
    for tag in d.glob("*.wait") if d.is_dir() else []:
        try:
            if now - tag.stat().st_mtime < 3 * BEAT:
                out.add(tag.stem)
        except OSError:
            continue
    return out


def message(home, session: str) -> str:
    """What the woken session is told. What it is handed is marked as handed to it, as at the end of a turn."""
    from . import notes, verdicts
    verdicts.due(home, session)  # marks them handed to this session
    rows = verdicts.waiting(home)  # all of them: the user asked, so what was handed before goes again
    head = "The user pressed Send verdicts in the Studio: they judged things there and want you to act on them now."
    body = verdicts.wording(rows, home) if rows else f"Run `{notes.command(home)} todo`: it lists each one with the steps to take."
    return head + "\n\n" + body


def counts(home) -> tuple[int, int]:
    """(unseen, waiting): verdicts and answers on the page that no session has been handed yet, and all of
    them that nobody has acted on."""
    from . import verdicts
    from .store import read_json
    rows = verdicts.waiting(home)
    if not rows:
        return 0, 0
    book = ((read_json(Path(home) / "live" / "notes.json", {}) or {}).get("verdicts") or {})
    return sum(1 for r in rows if (book.get(r["id"]) or {}).get("key") != r["key"]), len(rows)


def _talks(home) -> dict:
    """The conversations this page runs itself, by session id, that are alive."""
    from . import talk
    out = {}
    for t in list(talk.TALKS.values()):
        if t.sid and Path(t.home) == Path(home) and t.proc.poll() is None:
            out[t.sid] = t
    return out


def view(studio) -> dict:
    """For the button: how many verdicts no session has seen, and the idle sessions it can tell."""
    from . import board
    if studio.config.get("site"):
        return {"unseen": 0, "waiting": 0, "sessions": [], "here": False}
    home, can, talks = studio.home, awake(studio.home), _talks(studio.home)
    rows = [{"id": s["id"], "title": s["title"] or s["prompt"] or "A session", "where": s["where"], "quiet": s["quiet"],
             "talk": s["id"] in talks}
            for s in board.sessions(studio)
            if s["state"] in IDLE and (s["id"] in can or (s["id"] in talks and not talks[s["id"]].busy()))]
    rows.sort(key=lambda r: r["quiet"])
    unseen, waiting = counts(home)
    from .setup import hooks_wake
    return {"unseen": unseen, "waiting": waiting, "sessions": rows, "here": True, "hooks": hooks_wake()}


def send(studio, session: str) -> dict:
    """The user pressed Send verdicts for this session."""
    from .store import StudioError
    if studio.config.get("site"):
        raise StudioError("sessions run on the PC; send verdicts from the PC's Studio")
    session = clean(session)
    talks = _talks(studio.home)
    if session in talks:
        t = talks[session]
        if t.busy():
            raise StudioError("that conversation is working; it is handed the verdicts when its turn ends")
        from .talk import TalkError
        try:
            t.say(message(studio.home, session))
        except TalkError as err:
            raise StudioError(str(err)) from err
        return {"how": "talk"}
    if session not in awake(studio.home):
        raise StudioError("that session cannot be reached: it started before the Studio could wake sessions, or it has "
                          "ended. Send it any message in its own window and the verdicts go with it.")
    if _state(studio.home, session) not in IDLE:
        raise StudioError("that session is working; it is handed the verdicts when its turn ends")
    d = folder(studio.home)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"{session}.go.tmp"
    tmp.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), encoding="utf-8")
    os.replace(tmp, d / f"{session}.go")
    return {"how": "woken"}
