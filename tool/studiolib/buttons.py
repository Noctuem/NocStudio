"""Buttons on asks: a session files a command or a file to open, and the user's click runs it on this PC.

Only what a session filed with `studio.py hand set <id> --button ...` can run. The page sends the ask's
id and nothing else, so no text from the page is ever run. A copy with `site` set (the server's copy, for
the phone) is not the PC and runs nothing.

    live/runs/<ask id>.json   the last run: when, the line, the folder, running or its exit code
    live/runs/<ask id>.log    what it printed, stdout and stderr together

A command runs in Windows PowerShell on Windows (/bin/sh elsewhere), in the folder it was filed with,
with no window and nothing to type into. The page reads the last lines while it runs, so a long build
never holds the page up. A file or folder opens in its default app, as a double click would.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from .store import Studio, StudioError, iso_now, read_json, safe_id, write_json

TAIL_LINES = 40
RUNNABLE = ("open", "later")  # an ask that is done or set aside keeps its button, but it does nothing
PROCS: dict = {}  # (home, ask id) -> the process this server started; a restart loses them
LOCK = threading.Lock()
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _open_default(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - the default app for the file, as a double click
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


OPENER = _open_default  # the self-test swaps this, so it never opens anything on the machine


def _runs(studio: Studio) -> Path:
    live = studio.home / "live"
    live.mkdir(exist_ok=True)
    if not (live / ".gitignore").exists():  # this can be the first thing a home writes in live/
        (live / ".gitignore").write_text("# what sessions are doing right now: not history\n*\n", encoding="utf-8")
    return live / "runs"


def _button(studio: Studio, hid: str) -> dict:
    if studio.config.get("site"):
        raise StudioError("buttons run on the PC; this copy runs nothing")
    safe_id(hid, "ask")
    row = next((r for r in studio.hands() if r["id"] == hid), None)
    if row is None or not row.get("button"):
        raise StudioError(f"no button on {hid!r}")
    if row.get("status") not in RUNNABLE:
        raise StudioError("that ask is closed; open it again to use its button")
    return row


def _command(line: str) -> list[str]:
    if sys.platform != "win32":
        return ["/bin/sh", "-c", line]
    script = "\n".join([  # the exit code of what it ran, as a terminal would show it
        "$ProgressPreference = 'SilentlyContinue'",
        "try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}",
        "$global:LASTEXITCODE = 0",
        line,
        "if (-not $?) { if ($LASTEXITCODE) { exit $LASTEXITCODE }; exit 1 }",
        "exit $LASTEXITCODE"])
    return ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
            "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode("ascii")]


def press(studio: Studio, hid: str) -> dict:
    """The user's click: open the file, or start the command and come back at once."""
    row = _button(studio, hid)
    folder = _runs(studio)
    meta_path = folder / f"{hid}.json"
    if row.get("open"):
        path = Path(row["open"])
        if not path.exists():
            raise StudioError(f"{path} is not there")
        OPENER(path)
        meta = {"id": hid, "kind": "open", "path": str(path), "started": iso_now(), "state": "opened"}
        write_json(meta_path, meta)
        return meta
    key = (str(studio.home), hid)
    with LOCK:
        proc = PROCS.get(key)
        if proc is not None and proc.poll() is None:
            raise StudioError("it is still running")
        cwd = Path(row.get("cwd") or studio.repo_root() or studio.home)
        if not cwd.is_dir():
            raise StudioError(f"the folder {cwd} is not there")
        log_path = folder / f"{hid}.log"
        folder.mkdir(parents=True, exist_ok=True)
        log = open(log_path, "wb")
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            proc = subprocess.Popen(_command(row["run"]), cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, creationflags=flags, start_new_session=not flags)
        except OSError as err:
            log.close()
            raise StudioError(f"it did not start: {err}") from err
        PROCS[key] = proc
        meta = {"id": hid, "kind": "run", "line": row["run"], "cwd": str(cwd), "pid": proc.pid,
                "started": iso_now(), "state": "running"}
        write_json(meta_path, meta)

    def wait() -> None:
        code = proc.wait()
        log.close()
        done = dict(meta, state="stopped" if meta_path.with_suffix(".stop").exists() else "done", code=code, ended=iso_now())
        meta_path.with_suffix(".stop").unlink(missing_ok=True)
        write_json(meta_path, done)

    threading.Thread(target=wait, daemon=True, name=f"button {hid}").start()
    return meta


def stop(studio: Studio, hid: str) -> dict:
    """Stop a run the user started, and whatever it started in turn."""
    _button(studio, hid)
    proc = PROCS.get((str(studio.home), hid))
    if proc is None or proc.poll() is not None:
        raise StudioError("it is not running")
    (_runs(studio) / f"{hid}.stop").write_text(iso_now(), encoding="utf-8")
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        import signal
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            proc.terminate()
    return {"id": hid, "state": "stopping"}


def tail(path: Path, lines: int = TAIL_LINES) -> list[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 64 * 1024))
            data = fh.read()
    except OSError:
        return []
    text = ANSI.sub("", data.decode("utf-8", errors="replace"))
    rows = [row.split("\r")[-1].rstrip() for row in text.replace("\r\n", "\n").split("\n")]  # a progress line: its last state
    while rows and not rows[-1]:
        rows.pop()
    return rows[-lines:]


def last(studio: Studio, hid: str, with_tail: bool = False) -> dict | None:
    """The last time the button was pressed, as the page shows it."""
    safe_id(hid, "ask")
    folder = studio.home / "live" / "runs"
    meta = read_json(folder / f"{hid}.json", None)
    if not isinstance(meta, dict):
        return None
    if meta.get("state") == "running":
        proc = PROCS.get((str(studio.home), hid))
        if proc is None:  # this server did not start it, or has restarted since
            meta = dict(meta, state="lost")
    if with_tail and meta.get("kind") == "run":
        meta = dict(meta, tail=tail(folder / f"{hid}.log"))
    return meta


def attach(studio: Studio, rows: list[dict]) -> list[dict]:
    """Each ask with a button, with its last press, for the page."""
    if studio.config.get("site"):
        return [dict(r, ran=None, can_run=False) if r.get("button") else r for r in rows]
    return [dict(r, ran=last(studio, r["id"]), can_run=True) if r.get("button") else r for r in rows]
