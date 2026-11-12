"""The idea loop: a loose idea worked over with a session, round by round, until it is a spec.

Started from the menu, an idea gets its own project folder and a Studio straight away, so its talk, its notes and
the rulings made along the way are kept from the first minute. Inside a project that already exists, the same
loop works on that project's spec instead.

The session is told how to run the loop (LOOP, given to it as an added system prompt): each turn a few sharp
questions with a recommendation for each, the holes it sees, and docs/idea.md kept up to date with what is
settled, open and at risk. The page shows that file beside the talk. When the user says it is done, the session
writes docs/spec.md and finishes the project (DONE_NEW or DONE_EXISTING, then anything hub.toml adds).

Where the loop stands is overview/idea.json: {"stage": "idea" | "loop" | "done", "first": the idea as typed}.
"""
from __future__ import annotations

import re
from pathlib import Path

from .store import Studio, StudioError, iso_now, read_json, write_json

LOOP = """You are in an idea loop with the user, run from NocStudio. They started with a loose idea and want to work it
over with you until it is clear what they want: like plan mode, but about the idea, not code.

Every turn:
1. Ask the 3 to 5 questions that matter most right now, numbered. Under each, give your recommendation and why, in a
   line or two, so they can answer "yes" or say otherwise. Ask about what would change the shape of the thing first
   (who it is for, what it must do, what it must not do, what done looks like), details later.
2. Then the holes: what is contradictory, risky, too big, already made by someone else, or would sink it. Be
   straight about it.
3. Before you end the turn, rewrite docs/idea.md in the project folder with exactly these sections:
   # <the idea's name>
   ## The idea      one short paragraph, in their words where you can
   ## Settled       each point decided, with their words quoted after it
   ## Open          the questions still open
   ## At risk       the holes and risks, each in a line
   This file is what they look at beside the talk, so keep it short and true.

Rules: write no code and build nothing during the loop; touch no file but docs/idea.md until they say it is done.
Plain words, no filler, no AI speak. Quote them exactly when you record what they decided; never put words in their
mouth. If an answer of theirs settles something, move it to Settled. If they change their mind, change the file.
"""

DONE_NEW = """They said the idea is done. Now:
1. Write docs/spec.md in the project folder from docs/idea.md and the talk: what it is, who it is for, what it does
   (each settled point), what it does not do, the questions left open, and the first two or three milestones.
2. Write a short README.md (what it is, in two or three lines, and where the spec is) and a TODO.md with the first
   milestone's steps.
3. Write a short CLAUDE.md for the project: what it is in a line, where the spec is, then the Studio section from
   CLAUDE-section.md in the project's Studio home (the studio skill names the home), as it is.
4. Make the folder a git repository if it is not one: git init, add everything, commit "The spec from the idea loop".
5. Record each settled point as a ruling in the project's Studio with their words (the studio skill's `decide`).
Then tell them in a few lines what was made."""

DONE_EXISTING = """They said the idea is done. Now update docs/spec.md from docs/idea.md and the talk: add what was settled,
change what it replaces, and keep what it does not touch. Record each settled point as a ruling in the project's
Studio with their words (the studio skill's `decide`), commit the spec, and tell them in a few lines what changed."""


def _file(studio: Studio) -> Path:
    return studio.overview_dir / "idea.json"


def state(studio: Studio) -> dict:
    return read_json(_file(studio), {}) or {}


def set_state(studio: Studio, **values) -> dict:
    data = dict(state(studio), **values, updated=iso_now())
    write_json(_file(studio), data)
    return data


def view(studio: Studio) -> dict:
    """Where the loop stands, and docs/idea.md as it is now."""
    repo = studio.repo_root()
    text = ""
    if repo is not None:
        try:
            text = (repo / "docs" / "idea.md").read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    data = state(studio)
    return {"stage": data.get("stage", ""), "first": data.get("first", ""), "key": data.get("key", ""), "text": text,
            "new": bool(data.get("new"))}


def done_words(studio: Studio, extra: str = "") -> str:
    words = DONE_NEW if state(studio).get("new") else DONE_EXISTING
    return words + (("\nAlso: " + extra.strip()) if extra.strip() else "")


def hub_settings() -> dict:
    """[ideas] in the app's hub.toml: folder = where new ideas' project folders go; when_done = a last step of the user's own."""
    from . import vault
    path = vault.settings_file()
    if vault.tomllib is None or not path.is_file():
        return {}
    try:
        with open(path, "rb") as fh:
            raw = vault.tomllib.load(fh).get("ideas") or {}
    except (OSError, ValueError):
        return {}
    return {"folder": str(raw.get("folder") or ""), "when_done": str(raw.get("when_done") or "")}


def clean_name(name: str) -> str:
    name = re.sub(r"[^\w .+-]", "", str(name or "")).strip(" .")
    if not name:
        raise StudioError("give the idea a name; it becomes the project's folder name")
    return name[:60]


def new(folder: Path, name: str, text: str, registry: Path | None = None) -> Path:
    """A project folder and a Studio for an idea. Returns the Studio's home."""
    from . import setup
    name = clean_name(name)
    if not str(text or "").strip():
        raise StudioError("write the idea, however loose")
    repo = Path(folder) / name
    if repo.exists():
        raise StudioError(f"{repo} exists already: pick another name, or open that project's Studio")
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "idea.md").write_text(f"# {name}\n\n## The idea\n\n{text.strip()}\n\n## Settled\n\n## Open\n\n## At risk\n",
                                          encoding="utf-8", newline="\n")
    home = Path(setup.create(repo, project=name, registry=registry)["home"])
    set_state(Studio(home), stage="idea", first=text.strip(), new=True)
    return home
