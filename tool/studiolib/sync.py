"""Two copies of one Studio kept in step through its git remote: the PC's, where Claude Code works, and a server's, for the phone.

Settings, in the home's studio.local.toml (kept out of git, since each copy has its own):

    site = "p"                    # a letter after the numbers of the notes and decisions made here (N-0012p),
                                  # so two copies never hand out the same number
    [sync]
    every_seconds = 60            # how often the page's server syncs; 0 or absent: never by itself
    commit = "quiet"              # "always": commit and push what changed here (the server's copy);
                                  # "quiet": everything while no Claude Code session is live here; while one is,
                                  #   only what the user changed on the page, the moment they change it (the PC's);
                                  # "never": pull only

A sync commits (when it may), fetches, takes the remote's commits, and pushes. It never stashes and never forces:
when the remote's commits touch a file that has unsaved changes here, it waits for the next try and says why.
JSON records merge by meaning (tool/jsonmerge.py), the logs line by line, and the index files keep this copy's,
since `save` writes them again. What happened last is in live/sync.json, which the page shows.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from .store import Studio, StudioError, iso_now, read_json, write_json

TOOL = Path(__file__).resolve().parent.parent
ATTRS = ("*.json merge=studio-json", "*.jsonl merge=union", "INDEX.md merge=studio-ours", "decisions/DECISIONS.md merge=studio-ours")
STARTED: set[str] = set()
KICKS: dict[str, threading.Lock] = {}
CLICKED = "page-wrote.json"  # live/: the files the page changed that no sync has sent yet


def settings(studio: Studio) -> dict:
    raw = studio.config.get("sync") or {}
    commit = raw.get("commit", "quiet")
    if commit not in ("always", "quiet", "never"):
        raise StudioError('[sync] commit is "always", "quiet" or "never"')
    return {"every": max(0, int(raw.get("every_seconds") or 0)), "commit": commit}


def setup(studio: Studio) -> list[str]:
    """Teach this clone the merge rules: the attributes travel with the repository, the drivers live in .git/config."""
    if not (studio.home / ".git").exists():
        raise StudioError(f"{studio.home} keeps no history yet: run `git init` in it once")
    done = []
    attrs = studio.home / ".gitattributes"
    lines = attrs.read_text(encoding="utf-8").splitlines() if attrs.exists() else ["* text=auto eol=lf"]
    missing = [a for a in ATTRS if a not in lines]
    if missing:
        attrs.write_text("\n".join(lines + missing) + "\n", encoding="utf-8", newline="\n")
        done.append(".gitattributes: " + ", ".join(missing))
    python = Path(sys.executable).as_posix().replace("pythonw.exe", "python.exe")
    drivers = {"merge.studio-json.name": "the Studio's JSON records, merged by meaning",
               "merge.studio-json.driver": f'"{python}" "{(TOOL / "jsonmerge.py").as_posix()}" %O %A %B',
               "merge.studio-ours.name": "a file the Studio writes again: keep this copy's",
               "merge.studio-ours.driver": "true"}
    for key, value in drivers.items():
        if studio._git("config", "--get", key).stdout.strip() != value:
            studio._git("config", key, value)
            done.append(f"git config {key}")
    return done


def _count(studio: Studio) -> tuple[int, int]:
    out = studio._git("rev-list", "--left-right", "--count", "HEAD...@{u}").stdout.split()
    return (int(out[0]), int(out[1])) if len(out) == 2 else (0, 0)


def _sessions_live(studio: Studio) -> bool:
    from . import notes as notebox
    return bool(notebox.alive(studio.home))


def page_wrote(home, since_ns: int, path: str) -> None:
    """Remember which files a click on the page changed, and send them now. A Studio that does not sync is left alone."""
    studio = Studio(home)
    if "sync" not in studio.config:
        return
    found = set()
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 3 and parts[:2] == ["api", "batch"]:
        found.add(f"{studio.batch_dir(parts[2]).relative_to(studio.home).as_posix()}")  # a verdict made or taken back
    for sub in ("notes", "overview", "playtests", "decisions"):
        for f in (studio.home / sub).glob("*"):
            try:
                if f.is_file() and f.stat().st_mtime_ns >= since_ns:
                    found.add(f.relative_to(studio.home).as_posix())
            except OSError:
                continue
    if not found:
        return
    listed = studio.home / "live" / CLICKED
    write_json(listed, sorted(set(read_json(listed, []) or []) | found))
    kick(studio.home)


def kick(home) -> None:
    """A sync now, in the background; one at a time per home, and one more if asked while it ran."""
    key = str(Path(home).resolve())
    lock = KICKS.setdefault(key, threading.Lock())

    def run():
        for _ in range(2):  # a click made while this ran gets one more; a failing sync waits for the next minute
            if not lock.acquire(blocking=False):
                return
            try:
                step(Studio(key))
            except Exception as err:  # noqa: BLE001 - a sync must never take the page down
                write_json(Path(key) / "live" / "sync.json", {"at": iso_now(), "error": f"the sync broke: {err}"})
            finally:
                lock.release()
            if not read_json(Path(key) / "live" / CLICKED, []):
                return

    threading.Thread(target=run, daemon=True, name="studio-sync-now").start()


def _commit_clicked(studio: Studio, out: dict) -> None:
    """While a session works here: commit only the files the user changed on the page, nothing of the session's."""
    listed = studio.home / "live" / CLICKED
    paths = read_json(listed, []) or []
    if not paths:
        return
    studio._git("add", "-A", "--", *paths)
    if studio._git("diff", "--cached", "--quiet", "--", *paths).returncode:
        done = studio._git("commit", "-q", "-m", "From the page: " + ", ".join(paths[:4]) + (f" and {len(paths) - 4} more" if len(paths) > 4 else ""),
                           "--", *paths)
        if done.returncode:
            raise StudioError("the commit failed: " + (done.stderr or done.stdout).strip())
        out["committed"] = studio._git("rev-parse", "--short", "HEAD").stdout.strip()
    write_json(listed, [])


def step(studio: Studio, commit: str = "") -> dict:
    """One sync. Returns, and keeps in live/sync.json, what happened."""
    commit = commit or settings(studio)["commit"]
    out = {"at": iso_now(), "committed": "", "took": 0, "pushed": 0, "error": "", "waiting": ""}
    try:
        if not (studio.home / ".git").exists() or not studio._git("remote").stdout.split():
            raise StudioError("this Studio has no git remote to sync with")
        if studio._git("rev-parse", "--abbrev-ref", "@{u}").returncode:
            raise StudioError("the branch tracks no remote branch: push it once with `studio.py save`")
        if (studio.home / ".git" / "rebase-merge").exists() or (studio.home / ".git" / "MERGE_HEAD").exists():
            raise StudioError("a merge or rebase is half done in this clone; finish or abort it by hand")
        may = commit == "always" or (commit == "quiet" and not _sessions_live(studio))
        if may and studio.unsaved():
            studio._git("add", "-A")
            areas = {}
            for line in studio._git("diff", "--cached", "--name-only").stdout.splitlines():
                top = line.split("/")[0] if "/" in line else "the home"
                areas[top] = areas.get(top, 0) + 1
            message = "Synced from " + (studio.config.get("site") and "the phone" or "the PC") + ": " + \
                ", ".join(f"{n} in {a}" for a, n in sorted(areas.items(), key=lambda kv: -kv[1])[:6])
            done = studio._git("commit", "-q", "-m", message)
            if done.returncode:
                raise StudioError("the commit failed: " + (done.stderr or done.stdout).strip())
            out["committed"] = studio._git("rev-parse", "--short", "HEAD").stdout.strip()
            write_json(studio.home / "live" / CLICKED, [])
        elif commit == "quiet":
            _commit_clicked(studio, out)
        fetched = studio._git("fetch", "-q", timeout=120)
        if fetched.returncode:
            raise StudioError("the fetch failed: " + ((fetched.stderr or fetched.stdout).strip().splitlines() or ["no reason given"])[-1])
        ahead, behind = _count(studio)
        if behind and ahead:
            if studio.unsaved():
                out["waiting"] = "both copies have new commits and this one has unsaved changes; `studio.py save` joins them"
            else:
                moved = studio._git("rebase", "-q", "@{u}", timeout=120)
                if moved.returncode:
                    studio._git("rebase", "--abort")
                    raise StudioError("the two copies changed the same thing and could not be joined: "
                                      + ((moved.stderr or moved.stdout).strip().splitlines() or ["no reason given"])[0])
                out["took"] = behind
        elif behind:
            moved = studio._git("merge", "-q", "--ff-only", "@{u}", timeout=120)
            if moved.returncode:
                out["waiting"] = "the other copy changed files that have unsaved changes here; trying again later"
            else:
                out["took"] = behind
        ahead, behind = _count(studio)
        if ahead and not behind and commit != "never":
            pushed = studio._git("push", "-q", timeout=180)
            if pushed.returncode:
                raise StudioError("the push failed: " + ((pushed.stderr or pushed.stdout).strip().splitlines() or ["no reason given"])[-1])
            out["pushed"] = ahead
    except StudioError as err:
        out["error"] = str(err)
    live = studio.home / "live"
    live.mkdir(exist_ok=True)
    if not (live / ".gitignore").exists():
        (live / ".gitignore").write_text("# what sessions are doing right now: not history\n*\n", encoding="utf-8")
    last = read_json(live / "sync.json", {}) or {}
    out["ok"] = last.get("ok", "") if out["error"] else out["at"]  # when it last went through
    write_json(live / "sync.json", out)
    return out


def start(home) -> bool:
    """Sync this home in the background while its page is served, when its settings ask for it."""
    try:
        studio = Studio(home)
        every = settings(studio)["every"]
    except (StudioError, ValueError):
        return False
    key = str(studio.home)
    if not every or key in STARTED:
        return False
    STARTED.add(key)

    def loop():
        while True:
            try:
                step(Studio(key))
            except Exception as err:  # noqa: BLE001 - a sync must never take the page down
                write_json(Path(key) / "live" / "sync.json", {"at": iso_now(), "error": f"the sync broke: {err}"})
            time.sleep(every)

    threading.Thread(target=loop, daemon=True, name="studio-sync").start()
    return True
