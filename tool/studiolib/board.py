"""The board: how far along the project is, what is being worked on now, and what happened.

    overview/roadmap.json     the milestones, each with its steps
    overview/lanes.json       the pieces of work in progress right now
    overview/events.jsonl     the log: starts, landings, merges, publishes, setbacks; append only
    overview/days.json        one snapshot a day of how far along the project was

The percentage is counted, never typed: a step is worth what its status says (WORTH), a milestone
is the average of its steps, and the project is the average of its milestones by weight.
"""
from __future__ import annotations

import datetime
import json
import os

from .store import SCHEMA, Studio, StudioError, iso_now, read_json, safe_id, today, write_json

STEP_STATUS = ("planned", "building", "built", "tested", "done", "parked", "dropped")
WORTH = {"planned": 0.0, "building": 0.3, "built": 0.6, "tested": 0.85, "done": 1.0, "parked": 0.25}  # dropped: not counted
LANE_STATE = ("building", "testing", "waiting", "stuck")
EVENT_KINDS = ("start", "done", "merge", "publish", "setback", "note")
ASK_KINDS = ("action", "decision", "play", "info")
CHART_DAYS = 45


# ------------------------------------------------------------------ the road
def _save_road(studio: Studio, rows: list) -> None:
    write_json(studio.overview_dir / "roadmap.json", {"schema": SCHEMA, "milestones": rows})


def _milestone(rows: list, mid: str) -> dict:
    row = next((r for r in rows if r["id"] == mid), None)
    if row is None:
        raise StudioError(f"no milestone {mid!r}; see: studio.py milestone list")
    return row


def set_step(studio: Studio, mid: str, sid: str, *, name: str = "", status: str = "", note: str = "",
             date: str = "", quiet: bool = False) -> dict:
    """One step of a milestone: something that is either done or not, small enough to land in a day or two."""
    rows = studio.roadmap()
    m = _milestone(rows, mid)
    steps = m.setdefault("steps", [])
    step = next((s for s in steps if s["id"] == sid), None)
    if step is None:
        step = {"id": safe_id(sid, "step"), "name": name or sid, "status": "planned"}
        steps.append(step)
    before = step.get("status")
    if name:
        step["name"] = name
    if note:
        step["note"] = note
    if status:
        if status not in STEP_STATUS:
            raise StudioError(f"step status must be one of: {', '.join(STEP_STATUS)}")
        step["status"] = status
    if step["status"] != before or date:
        step["date"] = date or today()
        if step["status"] == "done":
            step["landed"] = step["date"]
        else:
            step.pop("landed", None)
    m["updated"] = iso_now()
    _save_road(studio, rows)
    if step["status"] == "done" and before != "done" and not quiet and not date:
        log(studio, "done", step["name"], milestone=mid, step=sid, snap=False)
    snapshot(studio)
    return step


def _counted(m: dict) -> list:
    return [s for s in m.get("steps") or [] if s.get("status") != "dropped"]


def _weight(m: dict) -> float:
    try:
        return max(0.0, float(m.get("weight", 1)))
    except (TypeError, ValueError):
        return 1.0


def milestone_pct(m: dict, on: str = "") -> float:
    """0..1. With `on` (a day), as it stood that evening: only steps landed by then count."""
    steps = _counted(m)
    if not steps:
        return 1.0 if m.get("status") == "done" and not on else 0.0
    if on:
        return sum(1.0 for s in steps if s.get("landed") and s["landed"] <= on) / len(steps)
    return sum(WORTH.get(s.get("status"), 0.0) for s in steps) / len(steps)


def _overall(rows: list, on: str = "") -> float:
    live = [m for m in rows if m.get("status") != "parked"]
    total = sum(_weight(m) for m in live)
    return 100.0 * sum(_weight(m) * milestone_pct(m, on) for m in live) / total if total else 0.0


def _done_steps(rows: list, on: str = "") -> int:
    return sum(1 for m in rows for s in _counted(m)
               if (s.get("landed") and s["landed"] <= on if on else s.get("status") == "done"))


# ------------------------------------------------------------ a day at a time
def _days(studio: Studio) -> dict:
    return (read_json(studio.overview_dir / "days.json", {}) or {}).get("days", {})


def snapshot(studio: Studio) -> dict:
    """Write today's line of the chart. A day before the Studio kept count is read off the dates steps landed on."""
    rows = studio.roadmap()
    days = _days(studio)
    before = dict(days)
    for day in {s["landed"] for m in rows for s in _counted(m) if s.get("landed") and s["landed"] < today()}:
        if day not in days or days[day].get("read"):  # a day read off the dates follows the plan as it is now
            days[day] = {"pct": round(_overall(rows, day), 1), "done": _done_steps(rows, day), "read": True}
    now = days[today()] = {"pct": round(_overall(rows), 1), "done": _done_steps(rows)}
    if days != before:
        write_json(studio.overview_dir / "days.json", {"schema": SCHEMA, "days": dict(sorted(days.items()))})
    return now


def _date(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text[:10])


def _chart(days: dict, events: list) -> list:
    """Every day from the first snapshot to today, a quiet day standing where the last one left off."""
    if not days:
        return []
    setbacks: dict[str, int] = {}
    for e in events:
        if e.get("kind") == "setback":
            day = _local_day(e.get("ts", ""))
            setbacks[day] = setbacks.get(day, 0) + 1
    first, last = _date(min(days)), datetime.date.today()
    first = max(first, last - datetime.timedelta(days=CHART_DAYS - 1))
    before = [d for d in sorted(days) if _date(d) < first]
    held = days[before[-1]] if before else {"pct": 0.0, "done": 0}
    out, day = [], first
    while day <= last:
        key = day.isoformat()
        cur = days.get(key, held)
        out.append({"date": key, "pct": cur["pct"], "landed": max(0, cur["done"] - held["done"]),
                    "setbacks": setbacks.get(key, 0)})
        held, day = cur, day + datetime.timedelta(days=1)
    return out


def _local_day(ts: str) -> str:
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date().isoformat()
    except ValueError:
        return ts[:10]


def _pace(days: dict, pct: float) -> dict:
    """Points a day over the last week, and the day the project is done if that holds."""
    if len(days) < 2 or pct >= 100:
        return {}
    last = datetime.date.today()
    since = (last - datetime.timedelta(days=7)).isoformat()
    older = [d for d in sorted(days) if d <= since]
    base = older[-1] if older else min(days)
    span = min(7, (last - _date(base)).days)
    if span < 1:
        return {}
    per_day = (pct - days[base]["pct"]) / span
    out = {"per_day": round(per_day, 2), "over_days": span}
    if per_day > 0.01:
        left = (100 - pct) / per_day
        if left < 3650:
            out["finish"] = (last + datetime.timedelta(days=round(left))).isoformat()
    return out


# -------------------------------------------------------------------- the log
def log(studio: Studio, kind: str, text: str, *, milestone: str = "", step: str = "", session: str = "",
        snap: bool = True) -> dict:
    if kind not in EVENT_KINDS:
        raise StudioError(f"an event is one of: {', '.join(EVENT_KINDS)}")
    if not text.strip():
        raise StudioError("say what happened, in one line")
    event = {"ts": iso_now(), "kind": kind, "text": text.strip()}
    for key, value in (("milestone", milestone), ("step", step), ("session", session or os.environ.get("STUDIO_SESSION", ""))):
        if value:
            event[key] = value
    path = studio.overview_dir / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    if snap:
        snapshot(studio)
    return event


def events(studio: Studio, limit: int = 0) -> list:
    """Oldest first."""
    out = []
    try:
        with open(studio.overview_dir / "events.jsonl", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except FileNotFoundError:
        pass
    return out[-limit:] if limit else out


# ------------------------------------------------------------------ the lanes
def lanes(studio: Studio) -> list:
    return (read_json(studio.overview_dir / "lanes.json", {}) or {}).get("lanes", [])


def _save_lanes(studio: Studio, rows: list) -> None:
    write_json(studio.overview_dir / "lanes.json", {"schema": SCHEMA, "lanes": rows})


def set_lane(studio: Studio, lid: str, *, name: str = "", milestone: str = "", step: str = "", state: str = "",
             eta: str = "", note: str = "", session: str = "") -> dict:
    """A piece of work in progress: who is on what, how it is going and when it should land."""
    rows = lanes(studio)
    lane = next((r for r in rows if r["id"] == lid), None)
    fresh = lane is None
    if fresh:
        lane = {"id": safe_id(lid, "lane"), "name": name or lid, "state": "building", "started": iso_now()}
        rows.append(lane)
    session = session or os.environ.get("STUDIO_SESSION", "") or (_caller(studio) if fresh else "")
    for key, value in (("name", name), ("milestone", milestone), ("step", step), ("state", state), ("eta", eta),
                       ("note", note), ("session", session)):
        if value:
            lane[key] = value
    if lane["state"] not in LANE_STATE:
        raise StudioError(f"a lane is one of: {', '.join(LANE_STATE)} (studio.py lane done <id> ends it)")
    if lane.get("milestone"):
        m = _milestone(studio.roadmap(), lane["milestone"])
        if lane.get("step") and not any(s["id"] == lane["step"] for s in m.get("steps") or []):
            raise StudioError(f"milestone {m['id']} has no step {lane['step']!r}; see: studio.py step list {m['id']}")
    lane["updated"] = iso_now()
    _save_lanes(studio, rows)
    if fresh:
        log(studio, "start", lane["name"], milestone=lane.get("milestone", ""), step=lane.get("step", ""), snap=False)
    if lane.get("milestone") and lane.get("step") and lane["state"] == "building":
        m = _milestone(studio.roadmap(), lane["milestone"])
        if next(s for s in m["steps"] if s["id"] == lane["step"]).get("status") == "planned":
            set_step(studio, lane["milestone"], lane["step"], status="building")
    return lane


def _caller(studio: Studio) -> str:
    """The session that is most likely running this command, when it could not say: the only one that moved just now."""
    recent = [s["id"] for s in sessions(studio) if s["state"] in ("working", "background") and s["quiet"] <= 20]
    return recent[0] if len(recent) == 1 else ""


def end_lane(studio: Studio, lid: str, *, note: str = "", step_status: str = "") -> dict:
    """The work landed or stopped: the lane leaves the board, and its step moves if a status is given."""
    rows = lanes(studio)
    lane = next((r for r in rows if r["id"] == lid), None)
    if lane is None:
        raise StudioError(f"no lane {lid!r}; see: studio.py lane list")
    _save_lanes(studio, [r for r in rows if r["id"] != lid])
    moved = bool(step_status and lane.get("milestone") and lane.get("step"))
    if moved:
        set_step(studio, lane["milestone"], lane["step"], status=step_status)
    if not (moved and step_status == "done"):  # a step that lands logs itself
        log(studio, "done", lane["name"] + (": " + note if note else ""), milestone=lane.get("milestone", ""),
            step=lane.get("step", ""))
    return lane


# ------------------------------------------------------------- the whole plan
def plan(studio: Studio) -> dict:
    """The plan as one document, in the shape `apply_plan` takes."""
    now = studio.now()
    return {"goal": now.get("goal", ""), "headline": now.get("headline", ""), "finish": now.get("finish", ""),
            "counters": now.get("counters", []), "next": now.get("next", []),
            "milestones": [{k: m[k] for k in ("id", "name", "status", "goal", "question", "note", "eta", "weight", "steps")
                            if m.get(k) not in (None, "", [])} for m in studio.roadmap()]}


def apply_plan(studio: Studio, data: dict) -> dict:
    """Write a whole plan at once. What the document names is added or changed; nothing is removed."""
    if not isinstance(data, dict):
        raise StudioError("a plan is a JSON object; `studio.py plan` prints the shape")
    count = {"milestones": 0, "steps": 0, "asks": 0, "slots": 0}
    for m in data.get("milestones") or []:
        if not isinstance(m, dict) or not m.get("id"):
            raise StudioError("every milestone needs an id")
        studio.set_milestone(str(m["id"]), **{k: m.get(k) for k in ("name", "status", "goal", "question", "note",
                                                                    "estimate", "eta", "weight")})
        count["milestones"] += 1
        for s in m.get("steps") or []:
            if not isinstance(s, dict) or not s.get("id"):
                raise StudioError(f"every step of {m['id']} needs an id")
            set_step(studio, str(m["id"]), str(s["id"]), name=str(s.get("name") or ""), status=str(s.get("status") or ""),
                     note=str(s.get("note") or ""), date=str(s.get("date") or s.get("landed") or ""), quiet=True)
            count["steps"] += 1
    fields = {k: data.get(k) for k in ("goal", "headline", "finish", "next") if data.get(k)}
    if data.get("counters"):
        fields["counters"] = [counter(c) for c in data["counters"]]
    if fields:
        studio.set_now(**fields)
    for a in data.get("asks") or []:
        studio.set_hand(str(a.get("id") or ""), **{k: a.get(k) for k in ("title", "detail", "gates", "time", "run", "group",
                                                                         "status", "kind", "default", "urgent")})
        count["asks"] += 1
    for s in data.get("slots") or []:
        studio.set_slot(str(s.get("id") or ""), **{k: s.get(k) for k in ("title", "kind", "group", "status", "game_path",
                                                                         "notes", "needed_by") if s.get(k)})
        count["slots"] += 1
    snapshot(studio)
    return count


def counter(value) -> dict:
    """`Holds=2/5`, or {"name": "Holds", "have": 2, "of": 5}: something the user counts the project by."""
    if isinstance(value, dict):
        name, have, of = value.get("name"), value.get("have"), value.get("of")
    else:
        name, _, rest = str(value).partition("=")
        have, _, of = rest.partition("/")
    try:
        return {"name": str(name).strip(), "have": int(have), "of": int(of)}
    except (TypeError, ValueError):
        raise StudioError(f"a counter reads Name=have/of, as in Holds=2/5; got {value!r}") from None


# ----------------------------------------------------------------- the view
def view(studio: Studio) -> dict:
    """Everything the Overview draws about progress, counted from the files."""
    rows = studio.roadmap()
    log_rows = events(studio)
    live = [m for m in rows if m.get("status") != "parked"]
    total = sum(_weight(m) for m in live) or 1.0
    share = {s: 0.0 for s in ("done", "tested", "built", "building", "parked", "planned")}
    counts = dict.fromkeys(share, 0)
    milestones = []
    for m in rows:
        steps = _counted(m)
        row = dict(m, pct=round(100 * milestone_pct(m), 1), unplanned=not steps and m.get("status") != "done")
        milestones.append(row)
        if m.get("status") == "parked":
            continue
        part = 100 * _weight(m) / total
        if not steps:
            share["done" if m.get("status") == "done" else "planned"] += part
        for s in steps:
            share[s.get("status", "planned")] += part / len(steps)
            counts[s.get("status", "planned")] += 1
    pct = round(_overall(rows), 1)
    days = _days(studio)
    if days and days.get(today(), {}).get("pct") != pct:  # read-only here: the chart shows today as it is
        days = dict(days, **{today(): {"pct": pct, "done": _done_steps(rows)}})
    return {"pct": pct, "share": {k: round(v, 2) for k, v in share.items()}, "counts": counts,
            "steps": sum(counts.values()), "milestones": milestones,
            "milestones_done": sum(1 for m in rows if m.get("status") == "done"),
            "days": _chart(days, log_rows), "pace": _pace(days, pct),
            "lanes": lanes(studio), "events": list(reversed(log_rows[-80:]))}


def advice(studio: Studio) -> list[str]:
    """What a session should put right so the board tells the truth. Printed by `status` and `todo`."""
    out = []
    rows = studio.roadmap()
    for m in rows:
        steps = _counted(m)
        if m.get("status") == "current" and not steps:
            out.append(f"Milestone {m['id']} is the current one and has no steps, so the Overview cannot show how far along "
                       f"it is. Break it down: studio.py step set {m['id']} <step id> --name \"...\" --status ...")
        if steps and all(s.get("status") == "done" for s in steps) and m.get("status") != "done":
            out.append(f"Every step of {m['id']} is done but the milestone is still {m.get('status')!r}: "
                       f"studio.py milestone set {m['id']} --status done (once the user has accepted it)")
    for lane in lanes(studio):
        try:
            age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(lane["updated"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if age > datetime.timedelta(hours=12):
            out.append(f"Lane {lane['id']} ({lane['name']}) has not moved in {int(age.total_seconds() // 3600)} hours. "
                       f"If it landed or stopped: studio.py lane done {lane['id']}")
    return out


# ------------------------------------------------- the sessions, as they work
def sessions(studio: Studio) -> list:
    """What each Claude Code session in the project is doing, from the notes the hooks keep (tool/hook.py)."""
    out, now = [], datetime.datetime.now(datetime.timezone.utc)
    for path in sorted((studio.home / "live").glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                rec = json.load(fh)
            quiet = (now - datetime.datetime.fromisoformat(rec["updated"].replace("Z", "+00:00"))).total_seconds()
        except (OSError, ValueError, KeyError, AttributeError):
            continue  # half written, or not a session
        state = rec.get("state") or "waiting"
        if quiet > (600 if state == "ended" else 6 * 3600):
            continue  # ended a while ago, or went away without saying so
        tasks = list((rec.get("tasks") or {}).values())
        out.append({"id": rec.get("id") or path.stem, "state": state, "since": rec.get("since") or rec.get("updated"),
                    "started": rec.get("started"), "quiet": int(quiet), "title": rec.get("title") or "",
                    "where": os.path.basename(str(rec.get("cwd") or "").rstrip("\/")), "prompt": rec.get("prompt") or "",
                    "doing": rec.get("doing") or "", "said": rec.get("said") or "",
                    "agents": [{"type": a.get("type") or "agent", "doing": a.get("doing") or ""}
                               for a in (rec.get("agents") or {}).values()],
                    "background": rec.get("background") or [], "tools": rec.get("tools") or 0,
                    "tasks": {"done": sum(1 for t in tasks if t.get("done")), "of": len(tasks),
                              "open": [t.get("what") or "" for t in tasks if not t.get("done")][:6]}})
    order = {"asking": 0, "stuck": 1, "working": 2, "background": 3, "waiting": 4, "ended": 5}
    out.sort(key=lambda s: (order.get(s["state"], 9), s["quiet"]))
    return out


def live(studio: Studio) -> dict:
    """The part of the Overview that moves by the second."""
    return {"sessions": sessions(studio), "lanes": lanes(studio)}


def checklist(studio: Studio, hooks: bool) -> list:
    """What a project needs before the Overview can be trusted. Each line is done or it is not."""
    now, rows = studio.now(), studio.roadmap()
    current = next((m for m in rows if m.get("status") == "current"), None)
    root = studio.game_root()
    skill = bool(root and (root / ".claude" / "skills" / "studio" / "SKILL.md").is_file())
    return [
        {"id": "goal", "title": "A goal: what the project is and what done looks like", "done": bool(now.get("goal"))},
        {"id": "road", "title": "The milestones from here to done", "done": len(rows) >= 2},
        {"id": "steps", "title": "Steps for the milestone in hand, so progress can be counted",
         "done": bool(current and _counted(current))},
        {"id": "needs", "title": "A list of what the project holds or still needs", "done": bool(studio.slots()), "optional": True},
        {"id": "skill", "title": "The project's sessions know the Studio's rules", "done": skill},
        {"id": "hooks", "title": "Sessions report in on their own while they work", "done": hooks},
    ]
