"""Handing the user's verdicts to a session: what they judged in the Studio, and what they answered there.

The hooks call `due()` when a session finishes a turn and when the user sends it a message, never between
tool calls: a verdict is not worth breaking into work for, and it never wakes a session that is idle. The
first session of the project to reach one of those points is handed everything waiting (`studio.py todo`
lists it, with the steps for each), and it is marked as handed so no other session takes it too. A
verdict still waiting after RETRY is handed again, at most TRIES times while it stays as it is.
"""
from __future__ import annotations

import time
from pathlib import Path

from . import notes
from .store import Studio, StudioError, read_json

RETRY = notes.RETRY
TRIES = notes.TRIES


def waiting(home) -> list[dict]:
    """Every verdict and answered thing nobody has acted on: [{"id", "key", "what"}]. Cheap when there is none:
    a batch is submitted when it has a verdict and no result yet, which a look at its folder tells."""
    home = Path(home)
    submitted = [d for d in (home / "batches").glob("*")
                 if (d / "verdict.json").is_file() and not (d / "result.json").exists()]
    hands_file = home / "overview" / "hands.json"
    if not submitted and not hands_file.exists():
        return []
    try:
        studio = Studio(home)
    except StudioError:
        return []
    out = []
    if submitted:
        for item in studio.todo():
            what = {"ship": "shipped", "ship_and_iterate": "shipped, and wants another round",
                    "another_round": "wants another round", "park": "parked", "answer": "answered"}.get(item["action"], item["action"])
            out.append({"id": "batch:" + item["batch"], "key": str(item.get("submitted") or ""),
                        "what": f"{item['batch']} ({item.get('title') or item['kind']}): {what}"})
    for x in studio.unseen_hands():
        said = {"done": "they say it is done", "parked": "they parked it", "open": "they opened it again"}.get(x.get("status"), x.get("status"))
        out.append({"id": "hand:" + x["id"], "key": str(x.get("answered") or ""), "what": f"{x['id']} ({x.get('title') or ''}): {said}"})
    return out


def due(home, session: str, mark: bool = True) -> list[dict]:
    """What to hand this session now, marked as handed to it."""
    rows = waiting(home)
    if not rows or not session:
        return []
    now = time.time()

    def take(data: dict) -> list:
        book, out = data.setdefault("verdicts", {}), []
        for row in rows:
            was = book.get(row["id"]) or {}
            if was.get("key") == row["key"] and (int(was.get("n") or 0) >= TRIES or now - float(was.get("at") or 0) < RETRY):
                continue
            out.append(row)
            if mark:
                book[row["id"]] = {"key": row["key"], "session": session, "at": now,
                                   "n": int(was.get("n") or 0) + 1 if was.get("key") == row["key"] else 1}
        for gone in [k for k in book if now - float(book[k].get("at") or 0) > 30 * 86400]:
            del book[gone]
        return out

    if not mark:
        return take({"verdicts": dict((read_json(Path(home, "live", "notes.json"), {}) or {}).get("verdicts") or {})})
    return notes._locked(home, take) or []


def wording(rows: list[dict], home, prompt: bool = False) -> str:
    """What the session is told: short, because `studio.py todo` prints the whole of each verdict and its steps."""
    s = notes.command(home)
    n = len(rows)
    when = ("Answer what the user just asked first; then, in the same turn, act on these."
            if prompt else "Act on these now, before you stop.")
    return "\n".join([
        f"The user judged or answered {n} thing{'s' if n != 1 else ''} in the project's Studio. This is how verdicts reach "
        "you; nothing else will deliver them. " + when,
        "",
        *[f"  {r['what']}" for r in rows],
        "",
        f"S is: {s}",
        "Run `S todo`: it prints each verdict in full, with the user's words quoted exactly and the steps to take. Do "
        "each, then close it as `S todo` says (`S done <batch> --ruling ...` for a verdict, `S hand seen <id>` for an "
        "answered item). Never paraphrase their words in what you record, and do not ask them about these in chat.",
    ])
