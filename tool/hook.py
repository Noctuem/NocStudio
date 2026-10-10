"""What Claude Code runs on its own while a session works: one small note per event, so the Studio's
Overview can show what every session in a project is doing right now.

`studio.py hooks install` points Claude Code's hooks here. Each call reads one event (JSON on stdin),
finds the Studio of the project the session is working in, and updates that session's file under
`<studio home>/live/`. A project without a Studio costs one cache lookup and nothing is written.

It only watches. It prints nothing, never blocks a session, and always exits 0. What it keeps is on
this machine and is not history: the live folder is left out of the Studio's git record.
"""
import json
import os
import sys
import time
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
REGISTRY = Path(os.environ.get("STUDIO_REGISTRY") or KIT / "studios.json")
CACHE = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "NocStudio" / "hook-cache.json"
KEEP_ENDED = 24 * 3600   # a session that ended stays on file this long
EVENTS = ("SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PermissionRequest", "Notification",
          "Stop", "StopFailure", "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted", "CwdChanged")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def short(text, n: int = 140) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= n else line[:n - 1].rstrip() + "…"


# --------------------------------------------------------- which Studio, if any
def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _main_repo(cwd: Path) -> str:
    """The repo a worktree belongs to: sessions often work in a worktree beside the project's folder."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return ""
    common = out.stdout.strip()
    return str(Path(common).parent) if out.returncode == 0 and common else ""


def home_for(cwd: str) -> str:
    """The studio home of the project `cwd` is in, or ''. Remembered per folder until the list of Studios changes."""
    if not cwd:
        return ""
    try:
        stamp = REGISTRY.stat().st_mtime_ns
    except OSError:
        return ""
    cache = read(CACHE, {})
    if cache.get("registry") != [str(REGISTRY), stamp]:
        cache = {"registry": [str(REGISTRY), stamp], "homes": {}}
    key = os.path.normcase(cwd)
    if key in cache["homes"]:
        return cache["homes"][key]
    rows = (read(REGISTRY, {}) or {}).get("studios", [])
    here = Path(cwd).resolve()

    def find(folder: Path) -> str:
        best = None
        for row in rows:
            repo = row.get("repo")
            if repo and _inside(folder, Path(repo).resolve()) and (best is None or len(repo) > len(best["repo"])):
                best = row
        return (best or {}).get("home") or ""

    home = find(here)
    if not home:
        main = _main_repo(here)
        home = find(Path(main)) if main else ""
    if home and not Path(home, "studio.toml").is_file():
        home = ""
    cache["homes"][key] = home
    try:
        write(CACHE, cache)
    except OSError:
        pass
    return home


# ------------------------------------------------------------- one event in
def doing(tool: str, given: dict) -> str:
    """A few words on what a tool call is, as the user would say it."""
    given = given if isinstance(given, dict) else {}
    name = lambda key: Path(str(given.get(key) or "")).name  # noqa: E731
    if tool in ("Bash", "PowerShell"):
        return short(given.get("description") or given.get("command"), 90)
    if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        return "Editing " + (name("file_path") or name("notebook_path") or "a file")
    if tool == "Read":
        return "Reading " + (name("file_path") or "a file")
    if tool in ("Grep", "Glob"):
        return "Searching for " + short(given.get("pattern"), 60)
    if tool in ("Agent", "Task"):
        return "Starting an agent: " + short(given.get("description") or given.get("subagent_type"), 70)
    if tool == "Workflow":
        return "Running a workflow" + (": " + short(given.get("name"), 60) if given.get("name") else "")
    if tool == "Skill":
        return "Using the skill " + short(given.get("skill"), 40)
    if tool in ("WebSearch", "WebFetch"):
        return "Looking up " + short(given.get("query") or given.get("url"), 70)
    if tool == "AskUserQuestion":
        return "Asking you a question"
    return tool.replace("mcp__", "").replace("__", ": ")


def apply(rec: dict, e: dict) -> dict:
    """Fold one event into what is known about its session."""
    kind, stamp, agent = e.get("hook_event_name") or "", now(), e.get("agent_id") or ""
    rec.setdefault("started", stamp)
    rec["updated"] = stamp
    if e.get("cwd"):
        rec["cwd"] = e["cwd"]
    if e.get("session_title"):
        rec["title"] = short(e["session_title"], 80)

    def state(value: str) -> None:
        if rec.get("state") != value:
            rec["state"], rec["since"] = value, stamp

    agents = rec.setdefault("agents", {})
    if kind == "SessionStart":
        if not agent:
            rec.pop("ended", None)
            if e.get("model"):
                rec["model"] = e["model"]
            if rec.get("state") in (None, "ended"):
                state("waiting")
    elif kind == "SessionEnd":
        if not agent:
            state("ended")
            rec["ended"], rec["agents"] = stamp, {}
            rec["doing"] = ""
    elif kind == "UserPromptSubmit":
        rec["prompt"], rec["doing"] = short(e.get("prompt"), 160), ""
        rec["turns"] = int(rec.get("turns") or 0) + 1
        state("working")
    elif kind == "PreToolUse":
        what = doing(e.get("tool_name") or "", e.get("tool_input"))
        if agent:
            agents.setdefault(agent, {"type": e.get("agent_type") or "agent", "started": stamp})["doing"] = what
        else:
            rec["doing"] = what
            state("working")
        rec["tools"] = int(rec.get("tools") or 0) + 1
    elif kind == "PermissionRequest":
        if not agent:
            rec["doing"] = "Wants to: " + doing(e.get("tool_name") or "", e.get("tool_input"))
        state("asking")
    elif kind == "Notification":
        note = e.get("notification_type") or ""
        if note in ("permission_prompt", "elicitation_dialog"):
            state("asking")
        elif note == "idle_prompt" and rec.get("state") == "working":
            state("waiting")
    elif kind == "Stop":
        if not agent:
            running = [t for t in e.get("background_tasks") or [] if isinstance(t, dict) and t.get("status") in (None, "running", "in_progress")]
            rec["background"] = [{"type": t.get("type") or "task", "what": short(t.get("description"), 80)} for t in running][:8]
            rec["said"], rec["doing"] = short(e.get("last_assistant_message"), 200), ""
            state("background" if running else "waiting")
    elif kind == "StopFailure":
        rec["doing"] = "Stopped on an error: " + short(e.get("error"), 100)
        state("stuck")
    elif kind == "SubagentStart":
        if agent:
            agents[agent] = {"type": e.get("agent_type") or "agent", "started": stamp, "doing": ""}
    elif kind == "SubagentStop":
        agents.pop(agent, None)
    elif kind in ("TaskCreated", "TaskCompleted"):
        tasks = rec.setdefault("tasks", {})
        task = tasks.setdefault(str(e.get("task_id") or len(tasks)), {"what": short(e.get("task_subject"), 90), "done": False})
        task["done"] = kind == "TaskCompleted"
    return rec


def record(home: str, e: dict) -> None:
    session = "".join(c for c in str(e.get("session_id") or "") if c.isalnum() or c in "-_")[:80]
    if not session:
        return
    live = Path(home) / "live"
    live.mkdir(exist_ok=True)
    ignore = live / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# what sessions are doing right now: not history\n*\n", encoding="utf-8")
    lock, path = live / f"{session}.lock", live / f"{session}.json"
    for _ in range(40):  # events of one session can arrive together
        try:
            os.mkdir(lock)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 5:
                    os.rmdir(lock)
            except OSError:
                pass
            time.sleep(0.025)
        except OSError:
            return
    try:
        write(path, apply(dict(read(path, {}), id=session), e))
        if e.get("hook_event_name") == "SessionStart":
            for old in live.glob("*.json"):  # forget sessions that ended a day ago
                if old != path and time.time() - old.stat().st_mtime > KEEP_ENDED:
                    old.unlink(missing_ok=True)
    finally:
        try:
            os.rmdir(lock)
        except OSError:
            pass


def main() -> int:
    try:
        e = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace") or "{}")
        if not isinstance(e, dict):
            return 0
        home = home_for(e.get("cwd") or os.getcwd())
        if not home:
            return 0
        env = os.environ.get("CLAUDE_ENV_FILE")
        if env and e.get("session_id") and e.get("hook_event_name") in ("SessionStart", "CwdChanged") and not e.get("agent_id"):
            with open(env, "a", encoding="utf-8", newline="\n") as fh:  # so `studio.py lane` knows which session it is
                fh.write(f"export STUDIO_SESSION={e['session_id']}\n")
        record(home, e)
    except Exception:  # a watcher must never get in a session's way
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
