"""Your own notes beside the menu: a few pages of a notes folder (an Obsidian vault, say) shown to read, and a
box that adds what you type to the end of one page (an inbox page you empty on your own time).

Settings, in hub.toml in the app's data folder (%LOCALAPPDATA%\\NocStudio\\hub.toml), or the file STUDIO_HUB names:

    [vault]
    folder = "C:/Users/you/Notes"
    show = ["Now.md", "Ideas.md"]      # pages inside the folder, shown in this order
    dump = "Inbox.md"                   # the page the box adds to; leave it out for no box

With no [vault], the menu shows only the projects. Nothing here edits a page except the box, and the box only
ever adds to the end.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python older than 3.11
    tomllib = None

MAX_PAGE = 512 * 1024  # a page bigger than this is not a page to read on a menu


class VaultError(Exception):
    pass


def settings_file() -> Path:
    given = os.environ.get("STUDIO_HUB")
    if given:
        return Path(given)
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "NocStudio" / "hub.toml"


def settings(path: Path | None = None) -> dict:
    """{"folder": Path, "show": [...], "dump": "..."}, or {} when there is no [vault]."""
    path = path or settings_file()
    if tomllib is None or not path.is_file():
        return {}
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh).get("vault") or {}
    except (OSError, ValueError) as err:
        raise VaultError(f"{path} does not parse: {err}") from err
    if not raw.get("folder"):
        return {}
    return {"folder": Path(str(raw["folder"])), "show": [str(x) for x in raw.get("show") or []], "dump": str(raw.get("dump") or "")}


def _inside(cfg: dict, rel: str) -> Path:
    root = cfg["folder"].resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise VaultError(f"{rel} is outside the notes folder")
    return path


def view(cfg: dict) -> dict:
    pages = []
    for rel in cfg.get("show") or []:
        path = _inside(cfg, rel)
        try:
            if path.stat().st_size > MAX_PAGE:
                text, missing = f"(too big to show here: {path.name})", False
            else:
                text, missing = path.read_text(encoding="utf-8", errors="replace"), False
            when = datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc).replace(microsecond=0)
            updated = when.isoformat().replace("+00:00", "Z")
        except OSError:
            text, missing, updated = "", True, ""
        pages.append({"name": Path(rel).stem, "path": rel, "text": text, "missing": missing, "updated": updated})
    return {"vault": True, "pages": pages, "dump": Path(cfg["dump"]).stem if cfg.get("dump") else ""}


def add(cfg: dict, text: str) -> str:
    """Add the words to the end of the dump page, as typed, after a blank line. Returns the page's name."""
    if not cfg.get("dump"):
        raise VaultError("no dump page is set: add dump = \"<page>.md\" under [vault] in " + str(settings_file()))
    text = str(text or "").strip()
    if not text:
        raise VaultError("write something first")
    path = _inside(cfg, cfg["dump"])
    try:
        old = path.read_bytes() if path.exists() else b""
    except OSError as err:
        raise VaultError(f"could not read {path.name}: {err}") from err
    nl = "\r\n" if b"\r\n" in old else "\n"
    if not old.strip() or old.endswith((nl * 2).encode()):
        lead = ""  # empty, or a blank line already ends it
    else:
        lead = nl if old.endswith(nl.encode()) else nl * 2
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(lead + nl.join(text.splitlines()) + nl)
    return path.stem
