#!/usr/bin/env python3
"""Studio: file candidates for the user's judgment, act on their verdicts, keep what was decided.

    python studio.py serve --open                 the user judges in the browser
    python studio.py status                       what waits on whom
    python studio.py todo                         verdicts the user submitted that nobody acted on yet

Filing a batch (Claude Code does this, never by hand-editing JSON):

    python studio.py new creature-model --kind model --slot enemy.creature.model \\
        --title "Creature model" --ask "Which creature goes into the hall?" \\
        --look "Height against the 1.8 m figure" --target height_m=1.8
    python studio.py add <batch> out/a.glb out/a.png --title "Faceted" --tool blender --seed 3
    python studio.py file <batch>                 runs the checks; only a clean batch reaches the user

Needs Python 3.11 or newer and nothing else. The studio home is --home, or
STUDIO_HOME, or the folder above this file when it holds a studio.toml.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from studiolib import bake, board, checks, server, setup  # noqa: E402
from studiolib.store import (HAND_KINDS, HAND_STATUS, KINDS, MILESTONE_STATUS, MODES, SLOT_STATUS, TRIAGE_STATUS,  # noqa: E402
                             Studio, StudioError)


def find_home(arg: str) -> Path:
    if arg:
        return Path(arg)
    if os.environ.get("STUDIO_HOME"):
        return Path(os.environ["STUDIO_HOME"])
    here = Path(__file__).resolve().parent
    for cand in (here.parent, here, Path.cwd()):
        if (cand / "studio.toml").exists():
            return cand
    raise StudioError("no studio home: pass --home <folder>, set STUDIO_HOME, or run: studio.py init <folder>")


def pairs(items) -> dict:
    out = {}
    for item in items or []:
        if "=" not in item:
            raise StudioError(f"{item!r}: write it as key=value")
        key, value = item.split("=", 1)
        try:
            out[key] = json.loads(value)
        except ValueError:
            out[key] = value
    return out


def text_arg(value: str, file_value: str) -> str:
    if file_value:
        return Path(file_value).read_text(encoding="utf-8")
    return value or ""


def print_report(report: dict) -> None:
    for line in report["errors"]:
        print(f"  ERROR  {line}")
    for line in report["warnings"]:
        print(f"  warn   {line}")
    if not report["errors"] and not report["warnings"]:
        print("  all checks pass")


# ------------------------------------------------------------------ commands
def cmd_init(a):
    studio = Studio.init(a.folder, a.project, a.game)
    print(f"studio home ready: {studio.home}")
    print(f"next: edit {studio.home / 'studio.toml'}, then: python {Path(__file__).name} serve --open")


def cmd_create(a):
    made = setup.create(a.repo, project=a.project, home=a.to, port=a.port)
    print(f"Studio for {made['project']} is ready.")
    print(f"  home      {made['home']}" + ("" if made["git"] else "   (no git history: git init it by hand)"))
    print(f"  open it   {made['launcher']}   (port {made['port']})")
    print(f"  skill     {made['skill']}")
    print(f"  S is      {made['s']}")
    print(f"\nNext, in {made['repo']}: merge {made['section']} into CLAUDE.md, near the top,")
    print("then move the project in: milestones, the build in hand, slots, rulings (the studio-create skill has the steps).")


def cmd_studios(a):
    rows = setup.studios()
    if not rows:
        print("no studio is registered yet")
    for r in rows:
        print(f"{r['name']:24} port {r['port']}  {r['home']}  <-  {r['repo']}")


def cmd_serve(a):
    server.serve(find_home(a.home), a.port, a.host, a.open)


def cmd_new(a):
    s = Studio(find_home(a.home))
    batch = s.new_batch(a.slug, title=a.title, kind=a.kind, mode=a.mode, slot=a.slot, ask=a.ask,
                        look_at=a.look, brief=text_arg(a.brief, a.brief_file), parent=a.parent,
                        max_winners=a.max_winners, targets=pairs(a.target), dest=a.dest, steps=a.step,
                        launch=a.launch, date=a.date, filed_by=a.by, round_no=a.round)
    print(batch["id"])


def cmd_add(a):
    s = Studio(find_home(a.home))
    made = {k: v for k, v in (("tool", a.tool), ("model", a.model), ("seed", a.seed), ("source", a.source),
                              ("prompt", text_arg(a.prompt, a.prompt_file))) if v not in (None, "")}
    if a.param:
        made["params"] = pairs(a.param)
    if a.ref:
        made["refs"] = a.ref
    cand = s.add_candidate(a.batch, a.files, cid=a.id, title=a.title, summary=a.summary, label=a.label,
                           body=text_arg(a.body, a.body_file), recommended=a.recommended, made_with=made,
                           slot=a.slot, dest=a.dest, motion=a.motion)
    print(f"{a.batch}: added candidate {cand['id']} ({len(cand['files'])} file{'s' if len(cand['files']) != 1 else ''})")


def cmd_carry(a):
    s = Studio(find_home(a.home))
    cand = s.carry(a.batch, a.from_batch, a.candidate, a.id)
    print(f"{a.batch}: carried {a.from_batch}/{a.candidate} in as {cand['id']}")


def cmd_context(a):
    Studio(find_home(a.home)).add_context(a.batch, a.file, a.label)
    print(f"{a.batch}: reference added")


def cmd_check(a):
    s = Studio(find_home(a.home))
    batch = s.load_batch(a.batch)
    report = checks.check_batch(s, batch)
    s.save_batch(batch)
    print(f"{a.batch}:")
    print_report(report)
    return 1 if report["errors"] else 0


def cmd_file(a):
    s = Studio(find_home(a.home))
    report = s.publish(a.batch, force=a.force)
    batch = s.load_batch(a.batch)
    print(f"{a.batch}:")
    print_report(report)
    if not report["ready"]:
        print("NOT filed: fix the errors and file again. The user has not been shown this batch.")
        return 1
    n = len(batch["candidates"])
    print(f"Filed. Say to the user, in one line: \"{batch['title']} is in the Studio ({n} to judge).\"")
    return 0


def cmd_status(a):
    s = Studio(find_home(a.home))
    state = s.state()
    groups = {"open": [], "draft": [], "submitted": [], "processed": []}
    for b in state["batches"]:
        groups.setdefault(b["status"], []).append(b)
    building = [b for b in s.batch_ids() if s.load_batch(b)["status"] == "building"]
    print(f"{state['project']}  ({s.home})")
    view = state["overview"]["board"]
    cur = next((m for m in view["milestones"] if m.get("status") == "current"), None)
    print(f"\n{view['pct']:g}% of the way, {view['milestones_done']} of {len(view['milestones'])} milestones done"
          + (f"; now {cur['id']} {cur.get('name', '')} at {cur['pct']:g}%" if cur else ""))
    for lane in view["lanes"]:
        print(f"  running  {lane['id']}  {lane['name']}  [{lane['state']}]" + (f"  eta {lane['eta']}" if lane.get("eta") else ""))
    print(f"\nWaiting on the user: {len(groups['open']) + len(groups['draft'])}")
    for b in groups["open"] + groups["draft"]:
        print(f"  {b['id']}  {b['title']}  [{b['kind']}, {b['count']}]" + ("  (they have started)" if b["status"] == "draft" else ""))
    print(f"\nWaiting on Claude: {len(groups['submitted'])}   (studio.py todo)")
    for b in groups["submitted"]:
        print(f"  {b['id']}  {b['title']}  -> {b['action']}")
    hands = [x for x in s.hands() if x.get("status") == "open"]
    if hands:
        print(f"\nOnly the user can do: {len(hands)}")
        for x in hands:
            print(f"  {x['id']}  {x['title']}")
    unseen = s.unseen_hands()
    if unseen:
        print(f"\nThe user answered, and nobody has read it: {len(unseen)}   (studio.py todo)")
    if building:
        print(f"\nNot filed yet: {len(building)}")
        for b in building:
            print(f"  {b}")
    counts = {}
    for slot in state["slots"]:
        counts[slot["status"]] = counts.get(slot["status"], 0) + 1
    if counts:
        print("\nSlots: " + ", ".join(f"{counts[k]} {k.replace('_', ' ')}" for k in SLOT_STATUS if k in counts))
    open_notes = sum(1 for p in state["playtests"] for r in p["reports"] if r["triage"].get("status") == "open")
    if state["playtests"]:
        print(f"Playtest notes not yet answered: {open_notes}")
    print(f"Closed batches: {len(groups['processed'])}   Decisions on record: {len(state['decisions'])}")
    reminders(s)


def reminders(s: Studio) -> None:
    """What a session must not leave behind: a board that is not true, unsaved history, a skill that has fallen behind."""
    for line in board.advice(s):
        print(f"\n{line}")
    n = s.unsaved()
    if n:
        print(f"\nThe Studio has {n} unsaved change{'s' if n != 1 else ''} (the user's verdicts and answers on the page count). "
              f"Before this session ends: studio.py save")
    root = s.game_root()
    copy = root / ".claude" / "skills" / "studio" / "SKILL.md" if root else None
    if copy is None or not copy.is_file():
        return
    own = s.home / "claude" / "skills" / "studio" / "SKILL.md"
    try:
        source = own.read_text(encoding="utf-8") if own.is_file() else setup.skill_text(s.config.get("project") or root.name, s.home, root)
        if source.replace("\r\n", "\n") != copy.read_text(encoding="utf-8").replace("\r\n", "\n"):
            print(f"\nThis repo's studio skill has fallen behind the Studio's. Copy it over, and commit it there:\n  "
                  + (f"{own}  ->  {copy}" if own.is_file() else f"studio.py skill > {copy}"))
    except OSError:
        pass


def cmd_save(a):
    s = Studio(find_home(a.home))
    out = s.save(a.message or "")
    print(f"Committed {out['files']} file{'s' if out['files'] != 1 else ''} as {out['commit']}." if out["commit"] else "Nothing new to commit.")
    print("Pushed." if out["pushed"] else f"NOT pushed: {out['note']}.")


def cmd_install_skill(a):
    print(f"Wrote {setup.install_create_skill()}\nIn any project, say to Claude Code: create a studio page for this")


def cmd_skill(a):
    s = Studio(find_home(a.home))
    own = s.home / "claude" / "skills" / "studio" / "SKILL.md"
    root = s.game_root()
    sys.stdout.write(own.read_text(encoding="utf-8") if own.is_file()
                     else setup.skill_text(s.config.get("project") or (root.name if root else s.home.name), s.home, root or s.home))


def cmd_todo(a):
    s = Studio(find_home(a.home))
    items = s.todo()
    for item in items:
        if item["action"] in ("another_round", "ship_and_iterate"):
            s.brief(item["batch"])
    unseen = s.unseen_hands()
    if a.json:
        print(json.dumps({"verdicts": items, "hands": unseen} if unseen else items, indent=2, ensure_ascii=False))
        return
    if unseen:
        print(f"{len(unseen)} thing{'s' if len(unseen) != 1 else ''} only the user could do, answered on the page. "
              "Act on each, then: studio.py hand seen <id>\n")
        for x in unseen:
            said = {"done": "they say it is done", "parked": "they parked it", "open": "they opened it again"}[x["status"]]
            print(f"  {x['id']}  {x['title']}: {said}" + (f"  \"{x['his_note']}\"" if x.get("his_note") else ""))
        print()
    if not items:
        print("Nothing to do: the user has no submitted verdict waiting.")
        reminders(s)
        return
    print(f"{len(items)} verdict{'s' if len(items) != 1 else ''} to act on, oldest first. Their words are quoted exactly.\n")
    for n, item in enumerate(items, 1):
        print(f"{n}. {item['title']}   [{item['batch']}]")
        print(f"   kind {item['kind']} · slot {item['slot'] or '-'} · their call: {item['action'].replace('_', ' ')}")
        if item["his_answer"]:
            print(f"   their answer: \"{item['his_answer']}\"")
        if item["his_note"]:
            print(f"   their note:   \"{item['his_note']}\"")
        for name in ("winners", "keep", "redo", "reject"):
            for row in item[name]:
                score = f" {row['score']}/10" if row.get("score") else ""
                label = f" ({row['label']})" if row.get("label") else ""
                note = f" \"{row['note']}\"" if row.get("note") else ""
                print(f"   {name.rstrip('s'):7} {row['candidate']}{label}: {row['title']}{score}{note}")
        print("   do:")
        for k, step in enumerate(item["steps"], 1):
            print(f"     {k}. {step}")
        print()
    print("When the last one is closed: studio.py save")
    reminders(s)


def cmd_brief(a):
    print(Studio(find_home(a.home)).brief(a.batch))


def cmd_import(a):
    s = Studio(find_home(a.home))
    rows = s.import_batch(a.batch, game=a.game, dry_run=a.dry_run, again=a.again)
    if not rows:
        print("nothing marked winner or approve")
        return 1
    for row in rows:
        print(f"{'would copy' if a.dry_run else 'copied'} candidate {row['candidate']}"
              + (f" -> slot {row['slot']} v{row['version']}" if row["slot"] else ""))
        if row["library"]:
            print(f"  library  {row['library']}")
        for dest in row["dest"]:
            print(f"  game     {dest}")
        if row.get("dest_skipped"):
            print(f"  game     SKIPPED: {row['dest_skipped']}")
    return 0


def cmd_done(a):
    s = Studio(find_home(a.home))
    result = s.mark_done(a.batch, ruling=a.ruling, commit=a.commit, next_batch=a.next, note=a.note,
                         in_game=a.in_game, by=a.by)
    s.write_index()
    print(f"{a.batch}: closed. Logged as {result['decision']}.")


def cmd_decide(a):
    s = Studio(find_home(a.home))
    rec = s.add_decision(title=a.title, his_words=text_arg(a.words, a.words_file), ruling=a.ruling,
                         source_type=a.type, ref=a.ref, tags=a.tag, supersedes=a.supersedes,
                         legacy=a.legacy, date=a.date)
    s.write_index()
    print(rec["id"])


def cmd_slot(a):
    s = Studio(find_home(a.home))
    if a.action == "list":
        for slot in sorted(s.slots(), key=lambda x: (x.get("group", ""), x["id"])):
            cur = slot.get("current") or {}
            print(f"{slot['status']:11} {slot['id']:44} {slot.get('kind', ''):8} "
                  f"{'v' + str(cur['version']) if cur else ''}")
        return
    if not a.id:
        raise StudioError("slot set needs an id")
    if a.motion:
        s.motion_ref(a.motion)
    slot = s.set_slot(a.id, title=a.title, kind=a.kind, group=a.group, status=a.status,
                      game_path=a.game_path, notes=a.notes, needed_by=a.needed_by, motion=a.motion)
    print(f"{slot['id']}: {slot['status']}")


def cmd_adopt(a):
    s = Studio(find_home(a.home))
    slot = s.adopt(a.slot, a.files, title=a.title, note=text_arg(a.note, a.note_file), source=a.source,
                   date=a.date, score=a.score, status=a.status or "approved")
    print(f"{slot['id']}: v{slot['current']['version']} in {slot['current']['library']}")


def cmd_motion(a):
    s = Studio(find_home(a.home))
    if a.action == "list":
        for mid, entry in sorted(s.motions().items()):
            print(f"{mid}  ({entry.get('updated', '')})" + ("   made-up motion for the samples; not the game's" if entry.get("sample") else ""))
            for clip in entry["clips"]:
                print(f"  {mid}:{clip['name']:28} {clip.get('seconds', 0):.2f} s")
        return
    if a.action == "set":
        if len(a.args) != 2:
            raise StudioError("motion set <id> <baked .glb>")
        entry = s.set_motion(a.args[0], a.args[1])
        print(f"{a.args[0]}: {len(entry['clips'])} clips kept")
        return
    if a.action == "bake":
        if len(a.args) != 2:
            raise StudioError("motion bake <id> <samples.json> [--model <the model's .glb>]")
        mid, path = a.args
        try:
            samples = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise StudioError(f"{path}: {err}") from err
        model = Path(a.model) if a.model else None
        if model is None:
            root = s.game_root()
            if not samples.get("model") or root is None:
                raise StudioError("say which model: --model <file.glb>, or \"model\" in the samples")
            model = root / samples["model"]
        if not model.is_file():
            raise StudioError(f"{model}: no such model")
        tmp = s.motions_dir / f"{mid}.baking.glb"
        try:
            made = bake.bake(model, samples, tmp)
            entry = s.set_motion(mid, tmp)
        finally:
            tmp.unlink(missing_ok=True)
        print(f"{mid}: {len(entry['clips'])} clips baked from {model.name} at scale {made['scale']:g}")
        for clip in made["clips"]:
            print(f"  {mid}:{clip['name']:28} {clip['seconds']:.2f} s" + (f"   ({clip['label']})" if clip["label"] else ""))
        if made["unsampled"]:
            print(f"  not sampled, so they stand still: {', '.join(made['unsampled'])}")
        return
    if len(a.args) < 2 or any("=" not in x for x in a.args[1:]):
        raise StudioError("motion link <batch> <candidate>=<motion set>:<clip> [...]")
    if a.action != "link":
        raise StudioError("motion set | bake | list | link")
    for pair in a.args[1:]:
        cid, ref = pair.split("=", 1)
        s.link_motion(a.args[0], cid, ref)
        print(f"{a.args[0]}: {cid} loops {ref}")


def cmd_app(a):
    from studiolib import app
    if a.install:
        print(f"Made {app.install()}\nOpen the Start menu and type NocStudio. Right-click it there to pin it to the taskbar.")
        return
    app.main()


def cmd_samples(a):
    from studiolib import samples
    s = Studio(find_home(a.home))
    made = samples.build(s, model=a.model, fresh=a.fresh)
    for row in made:
        print(f"  {row['id']:26} {row['note']}")
    print(f"{len(s.sample_ids())} samples under {s.samples_dir}. The user opens them from the Inbox: Samples. "
          f"Nothing in them is counted, recorded or acted on.")


def cmd_triage(a):
    s = Studio(find_home(a.home))
    entry = s.set_triage(a.key, status=a.status, build=a.build, ref=a.ref, note=a.note)
    print(f"{a.key}: {entry['status']}")


def cmd_milestone(a):
    s = Studio(find_home(a.home))
    if a.action == "list":
        for m in board.view(s)["milestones"]:
            print(f"{m['status']:8} {m['id']:4} {m['pct']:5g}%  {m.get('name', '')}" + (f"  eta {m['eta']}" if m.get("eta") else "")
                  + (f"  ({m['note']})" if m.get("note") else ""))
        return
    if not a.id:
        raise StudioError("milestone set needs an id")
    m = s.set_milestone(a.id, name=a.name, status=a.status, goal=a.goal, question=a.question, note=a.note,
                        estimate=a.estimate, eta=a.eta, weight=a.weight)
    board.snapshot(s)
    print(f"{m['id']}: {m['status']}")


def cmd_step(a):
    s = Studio(find_home(a.home))
    if a.action == "list":
        for m in board.view(s)["milestones"]:
            if a.milestone and m["id"] != a.milestone:
                continue
            print(f"{m['id']}  {m.get('name', '')}  {m['pct']:g}%")
            for step in m.get("steps") or []:
                print(f"  {step['status']:9} {step['id']:28} {step.get('name', '')}")
        return
    if not a.milestone or not a.id:
        raise StudioError("step set <milestone> <step id> --name \"...\" --status ...")
    step = board.set_step(s, a.milestone, a.id, name=a.name, status=a.status, note=a.note, date=a.date)
    print(f"{a.milestone} {step['id']}: {step['status']}   ({board.view(s)['pct']:g}% of the way)")


def cmd_lane(a):
    s = Studio(find_home(a.home))
    if a.action == "list":
        for lane in board.lanes(s):
            print(f"{lane['state']:9} {lane['id']:24} {lane['name']}" + (f"  eta {lane['eta']}" if lane.get("eta") else ""))
        return
    if not a.id:
        raise StudioError(f"lane {a.action} needs an id")
    if a.action == "done":
        lane = board.end_lane(s, a.id, note=a.note, step_status=a.step_status)
        print(f"{lane['id']}: off the board")
        return
    lane = board.set_lane(s, a.id, name=a.name, milestone=a.milestone, step=a.step, state=a.state, eta=a.eta, note=a.note)
    print(f"{lane['id']}: {lane['state']}")


def cmd_log(a):
    s = Studio(find_home(a.home))
    if not a.kind:
        for e in board.events(s, 20):
            print(f"{e['ts']}  {e['kind']:8} {e['text']}")
        return
    board.log(s, a.kind, " ".join(a.text), milestone=a.milestone, step=a.step)
    print(f"logged: {a.kind}")


def cmd_plan(a):
    s = Studio(find_home(a.home))
    if not a.file:
        print(json.dumps(board.plan(s), indent=2, ensure_ascii=False))
        return
    try:
        data = json.loads(Path(a.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise StudioError(f"{a.file}: {err}") from err
    n = board.apply_plan(s, data)
    print(f"Planned: {n['milestones']} milestones, {n['steps']} steps, {n['asks']} asks, {n['slots']} slots. "
          f"{board.view(s)['pct']:g}% of the way.")


def cmd_hooks(a):
    if a.action == "status":
        events = setup.hooks_installed()
        print(f"Claude Code reports {len(events)} kinds of event to {setup.HOOK}" if events
              else f"Not installed: studio.py hooks install   (it edits {setup.claude_settings()})")
        return
    out = setup.install_hooks(remove=a.action == "remove")
    print(f"{'Removed from' if a.action == 'remove' else 'Installed in'} {out['settings']}"
          + (f"\n  as it was before: {out['backup']}" if out["backup"] else ""))
    if a.action == "install":
        print("Every Claude Code session in a project that has a Studio now shows on its Overview while it works.\n"
              "Sessions already open pick it up within a few seconds, or when they next start.")


def cmd_now(a):
    s = Studio(find_home(a.home))
    fields = {"headline": a.headline, "build": a.build, "gate": a.gate, "spec": a.spec, "goal": a.goal,
              "finish": a.finish, "built": a.built, "next": a.next, "known": a.known, "start": a.start,
              "counters": [board.counter(c) for c in a.counter]}
    if any(v not in (None, "", []) for v in fields.values()):
        s.set_now(**fields)
    print(json.dumps(s.now(), indent=2, ensure_ascii=False))


def cmd_hand(a):
    s = Studio(find_home(a.home))
    if a.action == "list":
        for x in s.hands():
            flag = "  (the user answered, not read yet)" if x.get("answered") and not x.get("seen") else ""
            print(f"{x['status']:7} {x.get('kind', 'action'):9} {x['id']:28} {x['title']}{flag}")
        return
    if not a.id:
        raise StudioError(f"hand {a.action} needs an id")
    if a.action == "seen":
        s.see_hand(a.id)
        print(f"{a.id}: read")
        return
    if a.action == "answered":
        if not a.answer:
            raise StudioError("hand answered <id> --answer \"<their words, exact>\"")
        s.close_hand(a.id, a.answer)
        print(f"{a.id}: closed with their answer")
        return
    x = s.set_hand(a.id, title=a.title, detail=text_arg(a.detail, a.detail_file), gates=a.gates, time=a.time,
                   run=a.run, status=a.status, group=a.group, kind=a.kind, default=a.default,
                   urgent=True if a.urgent else (False if a.no_urgent else None))
    print(f"{x['id']}: {x['status']}")


def cmd_index(a):
    for path in Studio(find_home(a.home)).write_index():
        print(path)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # the user's notes may hold characters a Windows console code page lacks
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="studio.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--home", default="", help="the studio home folder")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("init", help="make a new studio home")
    c.add_argument("folder"); c.add_argument("--project", default=""); c.add_argument("--game", default="")
    c.set_defaults(fn=cmd_init)

    c = sub.add_parser("create", help="make a Studio for another project: a home, a launcher, the skill in its repo")
    c.add_argument("repo", help="the project's repo")
    c.add_argument("--project", default="", help="the project's name as the page shows it (default: the repo folder's name)")
    c.add_argument("--to", default="", help="the new studio home (default: <repo>-studio beside the repo)")
    c.add_argument("--port", type=int, default=0)
    c.set_defaults(fn=cmd_create)

    c = sub.add_parser("studios", help="every Studio on this machine"); c.set_defaults(fn=cmd_studios)

    c = sub.add_parser("serve", help="start the review page")
    c.add_argument("--port", type=int, default=0); c.add_argument("--host", default="127.0.0.1")
    c.add_argument("--open", action="store_true", help="open the browser")
    c.set_defaults(fn=cmd_serve)

    c = sub.add_parser("new", help="start a batch; prints its id")
    c.add_argument("slug")
    c.add_argument("--kind", default="", choices=("",) + KINDS)
    c.add_argument("--mode", default="", choices=("",) + MODES,
                   help="pick: choose a winner. rate: judge each on its own. question: choose an answer")
    c.add_argument("--title", default=""); c.add_argument("--slot", default="")
    c.add_argument("--ask", default="", help="one sentence: what the user is choosing")
    c.add_argument("--look", action="append", default=[], help="where the user should look; repeat")
    c.add_argument("--brief", default=""); c.add_argument("--brief-file", default="")
    c.add_argument("--parent", default="", help="the batch this is the next round of")
    c.add_argument("--max-winners", type=int, default=None)
    c.add_argument("--target", action="append", default=[], help="hard target, e.g. height_m=1.8; repeat")
    c.add_argument("--dest", default="", help="where the winner goes in the game repo")
    c.add_argument("--step", action="append", default=[], help="a step to do after the copy; repeat")
    c.add_argument("--launch", default="", help="for in-game batches: the line that starts the game")
    c.add_argument("--date", default=""); c.add_argument("--by", default="")
    c.add_argument("--round", type=int, default=0, help="only to record a round judged before the Studio existed")
    c.set_defaults(fn=cmd_new)

    c = sub.add_parser("add", help="add a candidate to a batch")
    c.add_argument("batch"); c.add_argument("files", nargs="*")
    c.add_argument("--id", default=""); c.add_argument("--title", default=""); c.add_argument("--summary", default="")
    c.add_argument("--label", default="", help="the words the user sees over it in the game")
    c.add_argument("--body", default=""); c.add_argument("--body-file", default="")
    c.add_argument("--recommended", action="store_true")
    c.add_argument("--tool", default=""); c.add_argument("--model", default="")
    c.add_argument("--prompt", default=""); c.add_argument("--prompt-file", default="")
    c.add_argument("--seed", default=None); c.add_argument("--source", default="", help="the script that made it")
    c.add_argument("--param", action="append", default=[]); c.add_argument("--ref", action="append", default=[])
    c.add_argument("--slot", default=""); c.add_argument("--dest", default="")
    c.add_argument("--motion", default="", help="<motion set>:<clip>: the baked motion to loop beside it")
    c.set_defaults(fn=cmd_add)

    c = sub.add_parser("carry", help="bring a candidate the user kept into a later round")
    c.add_argument("batch"); c.add_argument("from_batch"); c.add_argument("candidate"); c.add_argument("--id", default="")
    c.set_defaults(fn=cmd_carry)

    c = sub.add_parser("context", help="attach a reference picture or note to a batch")
    c.add_argument("batch"); c.add_argument("file"); c.add_argument("--label", default="")
    c.set_defaults(fn=cmd_context)

    c = sub.add_parser("check", help="run the checks without filing")
    c.add_argument("batch"); c.set_defaults(fn=cmd_check)

    c = sub.add_parser("file", help="run the checks and put the batch in the user's inbox")
    c.add_argument("batch"); c.add_argument("--force", action="store_true", help="file despite errors")
    c.set_defaults(fn=cmd_file)

    c = sub.add_parser("status", help="what waits on whom"); c.set_defaults(fn=cmd_status)

    c = sub.add_parser("todo", help="the user's submitted verdicts, with the steps for each")
    c.add_argument("--json", action="store_true"); c.set_defaults(fn=cmd_todo)

    c = sub.add_parser("brief", help="write and print the next round's brief from the user's verdict")
    c.add_argument("batch"); c.set_defaults(fn=cmd_brief)

    c = sub.add_parser("import", help="copy the winner to the library and the game")
    c.add_argument("batch"); c.add_argument("--game", default=""); c.add_argument("--dry-run", action="store_true")
    c.add_argument("--again", action="store_true", help="copy again after an earlier import")
    c.set_defaults(fn=cmd_import)

    c = sub.add_parser("done", help="close a verdict once it has been acted on")
    c.add_argument("batch"); c.add_argument("--ruling", default="", help="what this settles, one sentence")
    c.add_argument("--commit", default=""); c.add_argument("--next", default="", help="the next round's batch id")
    c.add_argument("--note", default=""); c.add_argument("--in-game", action="store_true")
    c.add_argument("--by", default="claude-code")
    c.set_defaults(fn=cmd_done)

    c = sub.add_parser("decide", help="record a ruling the user made somewhere else (chat, a playtest)")
    c.add_argument("--title", required=True); c.add_argument("--words", default=""); c.add_argument("--words-file", default="")
    c.add_argument("--ruling", default=""); c.add_argument("--type", default="chat"); c.add_argument("--ref", default="")
    c.add_argument("--tag", action="append", default=[]); c.add_argument("--supersedes", action="append", default=[])
    c.add_argument("--legacy", default=""); c.add_argument("--date", default="")
    c.set_defaults(fn=cmd_decide)

    c = sub.add_parser("slot", help="the things the game needs, and where each stands")
    c.add_argument("action", choices=("set", "list")); c.add_argument("id", nargs="?", default="")
    c.add_argument("--title", default=""); c.add_argument("--kind", default=""); c.add_argument("--group", default="")
    c.add_argument("--status", default="", choices=("",) + SLOT_STATUS)
    c.add_argument("--game-path", default=""); c.add_argument("--notes", default=""); c.add_argument("--needed-by", default="")
    c.add_argument("--motion", default="", help="<motion set>:<clip>: the baked motion the Library loops for it")
    c.set_defaults(fn=cmd_slot)

    c = sub.add_parser("adopt", help="bring in a master the user approved before the Studio existed (no batch)")
    c.add_argument("slot"); c.add_argument("files", nargs="+")
    c.add_argument("--title", default=""); c.add_argument("--note", default="", help="the user's words on it, exact")
    c.add_argument("--note-file", default=""); c.add_argument("--source", default="", help="where it came from")
    c.add_argument("--date", default="", help="when the user approved it"); c.add_argument("--score", type=int, default=None)
    c.add_argument("--status", default="", choices=("",) + SLOT_STATUS)
    c.set_defaults(fn=cmd_adopt)

    c = sub.add_parser("motion", help="baked motions: a character's .glb with a clip per motion, looped on the page")
    c.add_argument("action", choices=("bake", "set", "list", "link"))
    c.add_argument("args", nargs="*", help="bake <id> <samples.json> | set <id> <file.glb> | link <batch> <candidate>=<id>:<clip> ...")
    c.add_argument("--model", default="", help="bake: the model the samples are of (default: \"model\" in the samples, in the game repo)")
    c.set_defaults(fn=cmd_motion)

    c = sub.add_parser("save", help="commit everything in the studio home and push it; end every session that touched the Studio with this")
    c.add_argument("-m", "--message", default="", help="what changed, one line (else the tool writes one)")
    c.set_defaults(fn=cmd_save)

    c = sub.add_parser("install-skill", help="put the studio-create skill in your own Claude Code skills, so any project can ask for a Studio")
    c.set_defaults(fn=cmd_install_skill)

    c = sub.add_parser("skill", help="print the studio skill this project's repo should carry")
    c.set_defaults(fn=cmd_skill)

    c = sub.add_parser("app", help="NocStudio, the app: one window with a menu of every project's Studio")
    c.add_argument("--install", action="store_true", help="put NocStudio in the Start menu and stop")
    c.set_defaults(fn=cmd_app)

    c = sub.add_parser("samples", help="make the made-up batches the user tries the page on (Inbox: Samples)")
    c.add_argument("--fresh", action="store_true", help="make them all again, throwing away the user's marks on them")
    c.add_argument("--model", default="", help="a rigged .glb to move with made-up motion (else [samples] model in studio.toml, else the kit's own)")
    c.set_defaults(fn=cmd_samples)

    c = sub.add_parser("triage", help="say what happened to a playtest note")
    c.add_argument("key", help="<session folder>/f8-<n>")
    c.add_argument("--status", required=True, choices=TRIAGE_STATUS)
    c.add_argument("--build", default=None, help="the build that answers it")
    c.add_argument("--ref", default=None, help="a commit, a spec item or a decision id")
    c.add_argument("--note", default=None, help="what was done, one or two sentences")
    c.set_defaults(fn=cmd_triage)

    c = sub.add_parser("milestone", help="the road to release: where each milestone stands")
    c.add_argument("action", choices=("set", "list")); c.add_argument("id", nargs="?", default="")
    c.add_argument("--name", default=""); c.add_argument("--status", default="", choices=("",) + MILESTONE_STATUS)
    c.add_argument("--goal", default="", help="what the milestone is, in a sentence or two")
    c.add_argument("--question", default="", help="the question the user's verdict answers")
    c.add_argument("--note", default="", help="where it stands today, one line")
    c.add_argument("--estimate", default="")
    c.add_argument("--eta", default="", help="when it should be done: a date or a day, revised when it slips")
    c.add_argument("--weight", default="", help="how much of the whole it is: 1 for an ordinary milestone, 2 for twice the work")
    c.set_defaults(fn=cmd_milestone)

    c = sub.add_parser("step", help="the steps of a milestone; the Overview counts how far along the project is from them")
    c.add_argument("action", choices=("set", "list")); c.add_argument("milestone", nargs="?", default="")
    c.add_argument("id", nargs="?", default="")
    c.add_argument("--name", default="", help="the step as the user would say it")
    c.add_argument("--status", default="", choices=("",) + board.STEP_STATUS,
                   help="planned, building, built (made, not yet proven), tested, done (accepted and in the project), parked, dropped")
    c.add_argument("--note", default=""); c.add_argument("--date", default="", help="only to record a step that landed on an earlier day")
    c.set_defaults(fn=cmd_step)

    c = sub.add_parser("lane", help="work in progress right now: what the Overview shows under Running now")
    c.add_argument("action", choices=("set", "done", "list")); c.add_argument("id", nargs="?", default="")
    c.add_argument("--name", default="", help="the work, in a few words")
    c.add_argument("--milestone", default=""); c.add_argument("--step", default="", help="the step it is on; a planned step becomes building")
    c.add_argument("--state", default="", choices=("",) + board.LANE_STATE)
    c.add_argument("--eta", default="", help="when it should land: a clock time or a date, revised when it slips")
    c.add_argument("--note", default="", help="where it stands, one line")
    c.add_argument("--step-status", default="", choices=("",) + board.STEP_STATUS, help="done: where the work leaves its step")
    c.set_defaults(fn=cmd_lane)

    c = sub.add_parser("log", help="one line in the project's log: a merge, a publish, a setback; with no kind, prints the last lines")
    c.add_argument("kind", nargs="?", default="", choices=("",) + board.EVENT_KINDS); c.add_argument("text", nargs="*")
    c.add_argument("--milestone", default=""); c.add_argument("--step", default="")
    c.set_defaults(fn=cmd_log)

    c = sub.add_parser("plan", help="the whole plan as one JSON document: prints it, or with a file, writes one in")
    c.add_argument("file", nargs="?", default="", help="a plan to add or change: goal, milestones with steps, counters, asks, slots")
    c.set_defaults(fn=cmd_plan)

    c = sub.add_parser("hooks", help="have Claude Code report what each session is doing, so the Overview shows it live")
    c.add_argument("action", choices=("install", "remove", "status"))
    c.set_defaults(fn=cmd_hooks)

    c = sub.add_parser("now", help="the current build for the overview; with no flag, prints it")
    c.add_argument("--headline", default="", help="one sentence: where the game stands today")
    c.add_argument("--build", default="", help="the build the user can play, e.g. 0.0.1+3b4e833f7643")
    c.add_argument("--spec", default="", help="the plan of record")
    c.add_argument("--gate", default="", help="the last gate run, e.g. '2869 of 2869, laptop, 2026-10-08'")
    c.add_argument("--built", action="append", default=[], help="something the user can see in the build; repeat (replaces the list)")
    c.add_argument("--next", action="append", default=[], help="what comes next; repeat (replaces the list)")
    c.add_argument("--known", action="append", default=[], help="known and left as it is; repeat (replaces the list)")
    c.add_argument("--start", action="append", default=[], help="a line that starts the build; repeat (replaces the list)")
    c.add_argument("--goal", default="", help="what the project is and what done looks like, in a sentence or two")
    c.add_argument("--finish", default="", help="your honest estimate of when the whole project is done")
    c.add_argument("--counter", action="append", default=[], help="something the user counts the project by, as Name=have/of; repeat (replaces the list)")
    c.set_defaults(fn=cmd_now)

    c = sub.add_parser("hand", aliases=["ask"], help="what waits on the user: something only they can do, or a question only they can answer")
    c.add_argument("action", choices=("set", "list", "seen", "answered")); c.add_argument("id", nargs="?", default="")
    c.add_argument("--kind", default="", choices=("",) + HAND_KINDS, help="action (default), decision, play, info")
    c.add_argument("--default", default="", help="what you will do if they do not answer")
    c.add_argument("--urgent", action="store_true", help="work is stopped on it"); c.add_argument("--no-urgent", action="store_true")
    c.add_argument("--answer", default="", help="answered: their words, exact, when they answered in chat")
    c.add_argument("--title", default=""); c.add_argument("--detail", default=""); c.add_argument("--detail-file", default="")
    c.add_argument("--gates", default="", help="what waits on it")
    c.add_argument("--time", default="", help="how long it takes the user")
    c.add_argument("--run", default="", help="a line for the user to copy and run")
    c.add_argument("--group", default="", help="Playtest, Machines, Steam, ...")
    c.add_argument("--status", default="", choices=("",) + HAND_STATUS)
    c.set_defaults(fn=cmd_hand)

    c = sub.add_parser("index", help="rewrite INDEX.md and decisions/DECISIONS.md"); c.set_defaults(fn=cmd_index)

    args = p.parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except StudioError as err:
        print(f"studio: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
