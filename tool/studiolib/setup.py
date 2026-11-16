"""Make a Studio for another project: a home of its own, a launcher, and what its repo's sessions need.

The tool is shared (this folder's parent, the kit). Each project gets its own home folder, its own
port, and a copy of the skill that names that home. `studios.json` in the kit lists them all.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .store import Studio, StudioError, iso_now, read_json, write_json

KIT = Path(__file__).resolve().parents[2]
REGISTRY = KIT / "studios.json"
TEMPLATES = KIT / "claude" / "templates"
FIRST_PORT = 8772  # 8770 is the first studio's, 8771 the demo's

# The agents a Studio can work with. Each reads skills from its own folders and its own instructions file.
AGENTS = {
    "claude": {"name": "Claude Code", "skills": (".claude", "skills"), "doc": "CLAUDE.md"},
    "codex": {"name": "Codex", "skills": (".agents", "skills"), "doc": "AGENTS.md"},
}


def agent(name: str) -> dict:
    if name not in AGENTS:
        raise StudioError(f"{name!r} is not an agent the Studio knows; it knows: {', '.join(AGENTS)}")
    return AGENTS[name]


def skill_path(repo: Path, who: str = "claude") -> Path:
    """Where the project's repo carries the `studio` skill for that agent."""
    return Path(repo).joinpath(*agent(who)["skills"], "studio", "SKILL.md")


def skill_copies(repo: Path) -> list[Path]:
    """Every copy of the `studio` skill the repo carries, one per agent that has one."""
    return [p for p in (skill_path(repo, who) for who in AGENTS) if p.is_file()]


INSTRUCTION_FILES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md")


def taught(repo: Path, home: Path) -> bool:
    """Whether the repo's instructions file (CLAUDE.md, CLAUDE.local.md or AGENTS.md) names this Studio's home, as the merged section does."""
    want = str(Path(home)).replace("/", "\\").lower()
    for name in INSTRUCTION_FILES:
        try:
            if want in (Path(repo) / name).read_text(encoding="utf-8", errors="replace").replace("/", "\\").lower():
                return True
        except OSError:
            continue
    return False

GENERIC_TOML = '''# Studio settings for {project}. Edit freely; the tool reads this file on every start.

project = "{project}"

# The project's repo: where approved assets are copied to, and what the Library and the Overview read.
project_repo = "{repo}"

port = {port}

[review]
max_candidates = 6      # per batch; past this, judging gets sloppy
max_open_batches = 8    # filing warns when the inbox is already this full

# A candidate that breaks a rule is held back before it is ever shown. These start loose:
# set them to this project's own rules (0 or false turns a rule off).
[checks.audio]
max_peak_dbfs = 0.0
max_seconds = 0
sample_width_bits = 0

[checks.model]
max_triangles = 0

[checks.texture]
max_size = 8192
power_of_two = false

[checks.image]
min_width = 0

[checks.file]
max_mb = 256

# Folders the project writes test-run sessions into (each holds f8-<n>/ reports). Leave empty
# and the Test runs tab stays hidden.
[test_runs]
dirs = []

# The notes box: how long a note you typed waits before it is handed to a session in the middle
# of its work. A session that finishes a turn is handed it at once.
[notes]
after_minutes = 10

# What "ship the winner" means for each kind of asset, as steps for Claude Code.
[recipes.audio]
steps = []
[recipes.model]
steps = []
[recipes.texture]
steps = []
[recipes.image]
steps = []
[recipes.in_app]
steps = []
'''

LAUNCHER = '''@echo off
rem Starts the Studio page for {project} and opens the browser. Close this window to stop it.
py -3.11 "{tool}" --home "%~dp0." serve --open
if errorlevel 1 (
  echo.
  echo The Studio did not start. Python 3.11 or newer is needed: py -3.11 --version
  pause
)
'''

README = '''# The Studio for {project}

Double-click `studio.cmd` to open it. Then tell Claude Code in `{repo}`:
**process my studio verdicts**.

This folder holds only this project's records (batches, slots, library, decisions, overview).
The tool itself is shared and lives at `{kit}`; its `README.md` says what each tab is for.
'''


def studios(registry: Path | None = None) -> list[dict]:
    return (read_json(registry or REGISTRY, {}) or {}).get("studios", [])


def _fill(text: str, values: dict) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def skill_text(project: str, home_dir: Path, repo: Path) -> str:
    """The `studio` skill a project's repo carries, filled in for that project."""
    values = {"PROJECT": project, "HOME": str(home_dir), "REPO": str(repo),
              "S": f'py -3.11 "{KIT / "tool" / "studio.py"}" --home "{home_dir}"'}
    return _fill((TEMPLATES / "SKILL.template.md").read_text(encoding="utf-8"), values)


def install_create_skill(skills: Path | None = None, who: str = "claude") -> Path:
    """Put the `studio-create` skill where the agent finds it in every project: the user's own skills folder."""
    a = agent(who)
    target = (skills or Path.home().joinpath(*a["skills"])) / "studio-create" / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    values = {"KIT": str(KIT), "AGENT": a["name"], "DOC": a["doc"], "SKILLS": "/".join(a["skills"]),
              "FOR": "" if who == "claude" else f" --for {who}",
              "SETTINGS": "~/.claude/settings.json" if who == "claude" else "~/.codex/hooks.json",
              "TRUST": "" if who == "claude" else " Codex runs a new hook only after the user has looked it over: they type "
                                                  "`/hooks` in Codex once and trust NocStudio's."}
    target.write_text(_fill((TEMPLATES / "CREATE-SKILL.template.md").read_text(encoding="utf-8"), values),
                      encoding="utf-8", newline="\n")
    return target


def register(name: str, home: Path, repo: Path, port: int, registry: Path | None = None) -> None:
    rows = [r for r in studios(registry) if Path(r["home"]) != home]
    rows.append({"name": name, "home": str(home), "repo": str(repo), "port": port, "created": iso_now()})
    write_json(registry or REGISTRY, {"studios": rows})


def create(repo, project: str = "", home: str = "", port: int = 0, registry: Path | None = None,
           git: bool = True, agents=("claude",)) -> dict:
    """A new, empty Studio for the project at `repo`. Nothing existing is overwritten. `agents` names whose
    sessions work in the project: each gets the skill where it looks for skills."""
    agents = list(dict.fromkeys(agents)) or ["claude"]
    for who in agents:
        agent(who)
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise StudioError(f"{repo}: no such folder; give the project's repo")
    project = project.strip() or repo.name
    home_dir = Path(home).resolve() if home else repo.parent / f"{repo.name}-studio"
    if home_dir == repo or home_dir.is_relative_to(repo):
        raise StudioError("the studio home must be outside the project's repo (worktrees would each get a copy)")
    if (home_dir / "studio.toml").exists():
        raise StudioError(f"{home_dir} is a studio already; open it with its studio.cmd")
    skills = [skill_path(repo, who) for who in agents]
    for skill in skills:
        if skill.exists():
            raise StudioError(f"{skill} exists: this project already has a Studio skill; remove it first if it is stale")
    taken = {int(r.get("port") or 0) for r in studios(registry)} | {8770, 8771}
    if port and port in taken:
        raise StudioError(f"port {port} is another studio's; leave --port out to get a free one")
    port = port or next(p for p in range(FIRST_PORT, FIRST_PORT + 500) if p not in taken)

    home_dir.mkdir(parents=True, exist_ok=True)
    tool = KIT / "tool" / "studio.py"
    (home_dir / "studio.toml").write_text(
        GENERIC_TOML.format(project=project.replace('"', "'"), repo=repo.as_posix(), port=port),
        encoding="utf-8", newline="\n")
    Studio.init(home_dir, project, str(repo))
    (home_dir / "studio.cmd").write_text(LAUNCHER.format(project=project, tool=tool), encoding="ascii",
                                         errors="replace", newline="\r\n")
    (home_dir / "README.md").write_text(README.format(project=project, repo=repo, kit=KIT), encoding="utf-8", newline="\n")
    with open(home_dir / ".gitattributes", "a", encoding="utf-8", newline="\n") as fh:
        fh.write("*.cmd text eol=crlf\n")

    values = {"PROJECT": project, "HOME": str(home_dir), "REPO": str(repo),
              "S": f'py -3.11 "{tool}" --home "{home_dir}"'}
    for skill in skills:
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(skill_text(project, home_dir, repo), encoding="utf-8", newline="\n")
    section = home_dir / "CLAUDE-section.md"  # the same words go into AGENTS.md for Codex; the file keeps its name
    section.write_text(_fill((TEMPLATES / "CLAUDE-section.template.md").read_text(encoding="utf-8"), values),
                       encoding="utf-8", newline="\n")
    register(project, home_dir, repo, port, registry)
    try:  # something to try the page on from the first minute
        from . import samples
        samples.build(Studio(home_dir))
    except StudioError:
        pass  # the kit's demo files are gone: the home works without samples

    committed = False
    if git:
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", f"Studio for {project}: a new home"]):
                subprocess.run(["git", "-C", str(home_dir), *args], check=True, capture_output=True, timeout=30,
                               creationflags=flags)
            committed = True
        except (OSError, subprocess.SubprocessError):
            pass  # no git, or no identity set: the home works without history
    return {"project": project, "home": str(home_dir), "repo": str(repo), "port": port, "skill": str(skills[0]),
            "skills": [str(p) for p in skills], "docs": [AGENTS[who]["doc"] for who in agents],
            "section": str(section), "launcher": str(home_dir / "studio.cmd"), "s": values["S"], "git": committed}


# ------------------------------------------------- the agent's hooks, in the user's own settings
HOOK = KIT / "tool" / "hook.py"
HOOK_EVENTS = ("SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest", "Notification",
               "Stop", "StopFailure", "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted", "CwdChanged")
# these finish before the session goes on: two tell it its own id, three hand it what the user left for it
WAITED_FOR = ("SessionStart", "CwdChanged", "Stop", "PostToolUse", "UserPromptSubmit")
HOOK_TIMEOUT = 20  # seconds: a hook the session waits for must never hold it up for long
# and on these, a second one waits in the background for the user to press Send verdicts (studiolib/wake.py)
WAKE_EVENTS = ("SessionStart", "Stop")
# Codex sends fewer kinds of event, in the same shape. It waits only for the three that hand over what the user
# left, and it gives a hook three seconds at most as a session ends or the user stops a turn.
CODEX_EVENTS = ("SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest",
                "Stop", "SubagentStart", "SubagentStop", "Interrupt")
CODEX_WAITED = ("Stop", "PostToolUse", "UserPromptSubmit")
CODEX_SHORT = ("SessionEnd", "Interrupt")


def claude_settings() -> Path:
    import os
    return Path(os.environ.get("STUDIO_CLAUDE_SETTINGS") or Path.home() / ".claude" / "settings.json")


def codex_hooks() -> Path:
    import os
    return Path(os.environ.get("STUDIO_CODEX_HOOKS") or Path.home() / ".codex" / "hooks.json")


def hooks_file(who: str = "claude") -> Path:
    """The file of the user's own that holds that agent's hooks."""
    agent(who)
    return codex_hooks() if who == "codex" else claude_settings()


def hook_events(who: str = "claude") -> tuple:
    agent(who)
    return CODEX_EVENTS if who == "codex" else HOOK_EVENTS


def _words(hook) -> list[str]:
    """A hook's command as its words: Claude Code keeps them apart (`args`), Codex in one line."""
    if not isinstance(hook, dict):
        return []
    words = [str(a) for a in hook.get("args") or []]
    line = str(hook.get("command") or "")
    if "hook.py" in line:
        import shlex
        try:
            words += [w.strip('"') for w in shlex.split(line, posix=False)]
        except ValueError:
            pass
    return words


def _ours(hook) -> bool:
    return any(Path(w).name == "hook.py" and "tool" in Path(w).parts for w in _words(hook))


def _hook_command(who: str = "claude") -> dict:
    import sys
    windows = sys.platform == "win32"  # the launcher outlives a Python upgrade; a path to python.exe would not
    start = ["py", f"-{sys.version_info[0]}.{sys.version_info[1]}"] if windows else [sys.executable]
    if who == "codex":  # one line, and the hook is told whose it is
        import shlex
        words = [*start, str(HOOK), "--agent", "codex"]
        line = " ".join(f'"{w}"' if " " in w or "\\" in w else w for w in words) if windows else shlex.join(words)
        return {"type": "command", "command": line}
    return {"type": "command", "command": start[0], "args": [*start[1:], str(HOOK)]}


def _handlers(hooks: dict, event: str) -> list:
    return [h for g in hooks.get(event) or [] if isinstance(g, dict) for h in g.get("hooks") or []]


def _read_hooks(path: Path | None, who: str) -> dict:
    try:
        data = read_json(path or hooks_file(who), {}) or {}
    except StudioError:
        return {}
    hooks = data.get("hooks") if isinstance(data, dict) else None
    return hooks if isinstance(hooks, dict) else {}


def hooks_installed(path: Path | None = None, who: str = "claude") -> list[str]:
    """The events that agent reports to this kit's hook today."""
    hooks = _read_hooks(path, who)
    return [event for event in hooks if any(_ours(h) and str(HOOK) in _words(h) for h in _handlers(hooks, event))]


def hooks_hand_over(path: Path | None = None, who: str = "claude") -> bool:
    """Whether the hooks as installed can hand a session the user's notes: an install from before the notes box cannot."""
    hooks = _read_hooks(path, who)
    return all(any(_ours(h) and not h.get("async") for h in _handlers(hooks, event))
               for event in ("Stop", "PostToolUse", "UserPromptSubmit"))


def hooks_wake(path: Path | None = None) -> bool:
    """Whether the hooks as installed let the Send verdicts button wake an idle session. Claude Code only:
    Codex has no hook that can wake a session sitting at its prompt."""
    hooks = _read_hooks(path, "claude")
    return all(any(_ours(h) and h.get("asyncRewake") and "--wait" in (h.get("args") or []) for h in _handlers(hooks, event))
               for event in WAKE_EVENTS)


def hooks_on() -> list[str]:
    """The agents that report to this kit's hook today."""
    return [who for who in AGENTS if hooks_installed(who=who)]


def hooks_hand_over_all() -> bool:
    """Whether every agent that reports in is also handed the user's notes. False when none reports in."""
    on = hooks_on()
    return bool(on) and all(hooks_hand_over(who=who) for who in on)


def install_hooks(path: Path | None = None, remove: bool = False, who: str = "claude") -> dict:
    """Add this kit's hook to that agent's settings, or take it out. Every other setting is left as it is."""
    path = path or hooks_file(who)
    data = read_json(path, {}) or {}  # a settings file that does not parse is refused, never rewritten
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise StudioError(f"{path}: not the shape {agent(who)['name']}'s settings have; nothing was changed")
    backup = ""
    if path.exists():
        import shutil
        copy = path.with_name(path.name + ".before-nocstudio")
        if not copy.exists():
            shutil.copy2(path, copy)
        backup = str(copy)
    hooks = data.setdefault("hooks", {})
    for event in list(hooks):  # take out any earlier copy of ours, wherever the kit lived then
        groups = []
        for g in hooks[event] if isinstance(hooks[event], list) else []:
            if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                g = dict(g, hooks=[h for h in g["hooks"] if not _ours(h)])
                if not g["hooks"]:
                    continue
            groups.append(g)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not remove and who == "codex":
        for event in CODEX_EVENTS:
            mine = _hook_command("codex")
            if event in CODEX_SHORT:
                mine["timeout"] = 3
            elif event in CODEX_WAITED:  # the limit is on what a hook may hand over: none, so a long note arrives whole
                mine.update(timeout=HOOK_TIMEOUT, additionalContextLimit=0)
            else:
                mine["async"] = True
            hooks.setdefault(event, []).append({"matcher": "*", "hooks": [mine]})
    elif not remove:
        from . import wake
        for event in HOOK_EVENTS:
            mine = [dict(_hook_command(), **({"timeout": HOOK_TIMEOUT} if event in WAITED_FOR else {"async": True}))]
            if event in WAKE_EVENTS:
                waiter = _hook_command()
                mine.append(dict(waiter, args=[*waiter["args"], "--wait"], asyncRewake=True, timeout=wake.WAIT))
            hooks.setdefault(event, []).append({"hooks": mine})
    if not hooks:
        del data["hooks"]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, data)
    return {"settings": str(path), "backup": backup, "events": [] if remove else list(hook_events(who)), "agent": who}
