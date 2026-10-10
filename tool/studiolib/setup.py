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

GENERIC_TOML = '''# Studio settings for {project}. Edit freely; the tool reads this file on every start.

project = "{project}"

# The project's repo: where approved assets are copied to, and what the Library and the Overview read.
game_repo = "{repo}"

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

# Folders the project writes playtest sessions into (each holds f8-<n>/ reports). Leave empty
# and the Playtests tab stays hidden.
[playtests]
dirs = []

# What "ship the winner" means for each kind of asset, as steps for Claude Code.
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


def install_create_skill(skills: Path | None = None) -> Path:
    """Put the `studio-create` skill where Claude Code finds it in every project: the user's own skills folder."""
    target = (skills or Path.home() / ".claude" / "skills") / "studio-create" / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_fill((TEMPLATES / "CREATE-SKILL.template.md").read_text(encoding="utf-8"), {"KIT": str(KIT)}),
                      encoding="utf-8", newline="\n")
    return target


def register(name: str, home: Path, repo: Path, port: int, registry: Path | None = None) -> None:
    rows = [r for r in studios(registry) if Path(r["home"]) != home]
    rows.append({"name": name, "home": str(home), "repo": str(repo), "port": port, "created": iso_now()})
    write_json(registry or REGISTRY, {"studios": rows})


def create(repo, project: str = "", home: str = "", port: int = 0, registry: Path | None = None,
           git: bool = True) -> dict:
    """A new, empty Studio for the project at `repo`. Nothing existing is overwritten."""
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise StudioError(f"{repo}: no such folder; give the project's repo")
    project = project.strip() or repo.name
    home_dir = Path(home).resolve() if home else repo.parent / f"{repo.name}-studio"
    if home_dir == repo or home_dir.is_relative_to(repo):
        raise StudioError("the studio home must be outside the project's repo (worktrees would each get a copy)")
    if (home_dir / "studio.toml").exists():
        raise StudioError(f"{home_dir} is a studio already; open it with its studio.cmd")
    skill = repo / ".claude" / "skills" / "studio" / "SKILL.md"
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
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(skill_text(project, home_dir, repo), encoding="utf-8", newline="\n")
    section = home_dir / "CLAUDE-section.md"
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
    return {"project": project, "home": str(home_dir), "repo": str(repo), "port": port, "skill": str(skill),
            "section": str(section), "launcher": str(home_dir / "studio.cmd"), "s": values["S"], "git": committed}
