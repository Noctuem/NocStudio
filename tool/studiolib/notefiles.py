"""Files on a note: anything the user attaches (a screenshot pasted in, a PDF, a recording), kept beside the
note and out of git, so a big file never lands in the Studio's history.

    notes/files/<note id>/<name>      the files of a note, on this copy (the folder has its own .gitignore: *)

The note's JSON lists them (`files`: name, size, added), so every copy and every session knows what is
attached even where the bytes are not. While a note is open its files live here. When it closes they move
to the archive and leave this copy; when it opens again they come back. Settings, in studio.local.toml:

    [files]
    archive = "user@host:/srv/studio-homes/_archive/MyGame-studio"   # or a folder: "../_archive/MyGame-studio"
    peer = "user@host:/srv/studio-homes/MyGame-studio"              # the other copy of this Studio, if any

`archive` is where closed notes' files go. `peer` is the other copy (the server's, for the phone): files
attached on one copy are carried to the other while the note is open. Remote places are reached with ssh and
tar, so the machine needs `ssh` working without a password prompt. With no archive set, a closed note's files
stay where they are. A relative folder is taken from the home.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import threading
import time
from pathlib import Path

from .notes import OPEN

CHUNK = 1024 * 1024
LOCKS: dict[str, threading.Lock] = {}
FETCHED = "fetched"  # live/fetched/<note>/<name>: a closed note's file brought back to look at, not kept


class FilesError(Exception):
    pass


def folder(home, nid: str) -> Path:
    return Path(home) / "notes" / "files" / nid


def _root(home) -> Path:
    root = Path(home) / "notes" / "files"
    root.mkdir(parents=True, exist_ok=True)
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# files on notes: kept out of git, moved to the archive when the note closes\n*\n", encoding="utf-8")
    return root


def clean_name(name: str) -> str:
    """A file name the user gave, safe to keep: no folders, no control characters, not too long."""
    name = str(name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]", "_", name).strip().strip(".")
    if not name:
        name = "file"
    stem, dot, ext = name.rpartition(".")
    if len(name) > 120:
        name = (stem[:110] + "." + ext[:9]) if dot and len(ext) <= 9 else name[:120]
    return name


def _free(directory: Path, name: str, taken: set[str]) -> str:
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n, out = 1, name
    while out in taken or (directory / out).exists():
        n += 1
        out = f"{stem} ({n})" + (f".{ext}" if ext else "")
    return out


def receive(home, nid: str, name: str, stream, length: int, taken: set[str]) -> dict:
    """Write an upload to the note's folder as it arrives. Returns the entry for the note's list."""
    _root(home)
    target = folder(home, nid)
    target.mkdir(parents=True, exist_ok=True)
    name = _free(target, clean_name(name), taken)
    part = target / f".{name}.{os.getpid()}.{threading.get_ident()}.part"
    left, size = length, 0
    try:
        with open(part, "wb") as fh:
            while left > 0:
                chunk = stream.read(min(CHUNK, left))
                if not chunk:
                    raise FilesError("the upload stopped before the end")
                fh.write(chunk)
                left -= len(chunk)
                size += len(chunk)
        os.replace(part, target / name)
    finally:
        if part.exists():
            part.unlink()
    return {"name": name, "size": size, "added": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def here(home, nid: str, name: str) -> Path | None:
    path = folder(home, nid) / clean_name(name)
    return path if path.is_file() else None


def drop(home, nid: str, name: str) -> None:
    path = here(home, nid, name)
    if path:
        path.unlink()
    try:
        folder(home, nid).rmdir()
    except OSError:
        pass


# --------------------------------------------------------------------------- places: a folder, or ssh
def settings(studio) -> dict:
    raw = studio.config.get("files") or {}
    return {"archive": str(raw.get("archive") or ""), "peer": str(raw.get("peer") or "")}


class Place:
    """A folder that holds note folders (<place>/notes/files/<id> for a peer, <place>/<id> for an archive)."""

    def __init__(self, spec: str, home: Path, sub: str = ""):
        self.ignore = bool(sub)
        m = re.fullmatch(r"([^/\\:@\s]+@[^/\\:\s]+):(/.+)", spec)
        if m:
            self.host, self.dir = m.group(1), m.group(2).rstrip("/") + (f"/{sub}" if sub else "")
        else:
            path = Path(spec)
            self.host, self.dir = "", str((path if path.is_absolute() else home / path).resolve() / sub)

    def __str__(self):
        return f"{self.host}:{self.dir}" if self.host else self.dir

    def _ssh(self, command: str, data=None, timeout=600):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", self.host, command],
                              input=data, capture_output=True, timeout=timeout, creationflags=flags)

    def listing(self) -> dict:
        """{note id: {name: size}} of what this place holds."""
        out: dict = {}
        if not self.host:
            base = Path(self.dir)
            for f in base.glob("*/*") if base.is_dir() else []:
                if f.is_file() and not f.name.endswith(".part"):
                    out.setdefault(f.parent.name, {})[f.name] = f.stat().st_size
            return out
        res = self._ssh(f"cd {shlex.quote(self.dir)} 2>/dev/null && find . -mindepth 2 -maxdepth 2 -type f -printf '%P\\t%s\\n' || true", timeout=60)
        if res.returncode:
            raise FilesError(f"could not list {self}: " + res.stderr.decode("utf-8", "replace").strip()[-200:])
        for line in res.stdout.decode("utf-8", "replace").splitlines():
            rel, _, size = line.rpartition("\t")
            nid, _, name = rel.partition("/")
            if nid and name and not name.endswith(".part") and size.isdigit():
                out.setdefault(nid, {})[name] = int(size)
        return out

    def put(self, src: Path, nid: str, names: list[str]) -> None:
        """Copy these files of one note from a local folder to this place."""
        if not self.host:
            dest = Path(self.dir) / nid
            dest.mkdir(parents=True, exist_ok=True)
            for name in names:
                tmp = dest / f".{name}.part"
                shutil.copy2(src / name, tmp)
                os.replace(tmp, dest / name)
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        d = shlex.quote(self.dir)
        keep_out = ""
        if self.ignore:  # a peer's notes/files must never reach its git, even before its own tool has made this
            keep_out = f" && {{ [ -e {d}/.gitignore ] || printf '%s\\n' '# files on notes: kept out of git' '*' > {d}/.gitignore; }}"
        command = f"mkdir -p {d}{keep_out} && tar -x -C {d}"
        proc = subprocess.Popen(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", self.host, command],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
        try:
            with tarfile.open(fileobj=proc.stdin, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                for name in names:
                    info = tar.gettarinfo(str(src / name), arcname=f"{nid}/{name}")
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = 0o644
                    with open(src / name, "rb") as fh:
                        tar.addfile(info, fh)
            proc.stdin.close()
            err = proc.stderr.read().decode("utf-8", "replace").strip()
            if proc.wait(timeout=600):
                raise FilesError(f"could not copy to {self}: {err[-200:] or 'no reason given'}")
        finally:
            if proc.poll() is None:
                proc.kill()

    def get(self, nid: str, names: list[str], dest: Path) -> None:
        """Copy these files of one note from this place into a local folder."""
        dest.mkdir(parents=True, exist_ok=True)
        if not self.host:
            for name in names:
                tmp = dest / f".{name}.part"
                shutil.copy2(Path(self.dir) / nid / name, tmp)
                os.replace(tmp, dest / name)
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        command = f"tar -c -C {shlex.quote(self.dir)} -- " + " ".join(shlex.quote(f"{nid}/{n}") for n in names)
        proc = subprocess.Popen(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", self.host, command],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        try:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
                for member in tar:
                    nm = member.name.split("/", 1)
                    if not member.isfile() or len(nm) != 2 or nm[0] != nid or clean_name(nm[1]) != nm[1] or nm[1] not in names:
                        continue  # only the plain files asked for, under their own names
                    src = tar.extractfile(member)
                    tmp = dest / f".{nm[1]}.part"
                    with open(tmp, "wb") as fh:
                        shutil.copyfileobj(src, fh, CHUNK)
                    os.replace(tmp, dest / nm[1])
            err = proc.stderr.read().decode("utf-8", "replace").strip()
            if proc.wait(timeout=600):
                raise FilesError(f"could not copy from {self}: {err[-200:] or 'no reason given'}")
        finally:
            if proc.poll() is None:
                proc.kill()


def _places(studio) -> tuple[Place | None, Place | None]:
    s = settings(studio)
    archive = Place(s["archive"], studio.home) if s["archive"] else None
    peer = Place(s["peer"], studio.home, "notes/files") if s["peer"] else None
    return archive, peer


# --------------------------------------------------------------------------- keeping files where they belong
def _notes(home) -> list[dict]:
    out = []
    for path in sorted((Path(home) / "notes").glob("N-*.json")):
        try:
            note = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(note, dict) and note.get("files"):
            out.append(note)
    return out


def tidy(studio) -> dict:
    """Closed notes' files to the archive and off this copy; open notes' files brought here, and to the peer.
    One at a time per home. Returns what it did, also kept in live/files.json for the page."""
    key = str(studio.home)
    lock = LOCKS.setdefault(key, threading.Lock())
    if not lock.acquire(blocking=False):
        return {"busy": True}
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "archived": 0, "fetched": 0, "sent": 0, "error": "", "missing": []}
    try:
        notes = _notes(studio.home)
        if not notes:
            return out
        archive, peer = _places(studio)
        closed = [n for n in notes if n.get("status") not in OPEN and folder(studio.home, n["id"]).is_dir()]
        opened = [n for n in notes if n.get("status") in OPEN]
        try:
            if archive and closed:
                held = archive.listing()
                for n in closed:
                    src = folder(studio.home, n["id"])
                    local = {f.name: f.stat().st_size for f in src.iterdir() if f.is_file() and not f.name.endswith(".part")}
                    send = [nm for nm, size in local.items() if held.get(n["id"], {}).get(nm) != size]
                    if send:
                        archive.put(src, n["id"], send)
                        again = archive.listing().get(n["id"], {})
                        if any(again.get(nm) != size for nm, size in local.items()):
                            raise FilesError(f"{n['id']}: the archive's copy does not match; kept here")
                    shutil.rmtree(src)
                    out["archived"] += len(local)
            want = {n["id"]: [f["name"] for f in n["files"]] for n in opened}
            lacking = {nid: [nm for nm in names if not here(studio.home, nid, nm)] for nid, names in want.items()}
            lacking = {nid: names for nid, names in lacking.items() if names}
            peer_has = peer.listing() if peer and (lacking or any(want.values())) else {}
            for nid, names in lacking.items():
                _root(studio.home)
                dest = folder(studio.home, nid)
                from_peer = [nm for nm in names if nm in peer_has.get(nid, {})]
                if from_peer:
                    peer.get(nid, from_peer, dest)
                    out["fetched"] += len(from_peer)
                rest = [nm for nm in names if nm not in from_peer]
                if rest and archive:
                    held = archive.listing().get(nid, {})
                    got = [nm for nm in rest if nm in held]
                    if got:
                        archive.get(nid, got, dest)
                        out["fetched"] += len(got)
                    rest = [nm for nm in rest if nm not in got]
                out["missing"] += [f"{nid}/{nm}" for nm in rest]
            if peer:
                for nid, names in want.items():
                    send = [nm for nm in names if (p := here(studio.home, nid, nm)) and peer_has.get(nid, {}).get(nm) != p.stat().st_size]
                    if send:
                        peer.put(folder(studio.home, nid), nid, send)
                        out["sent"] += len(send)
        except (FilesError, OSError, subprocess.SubprocessError) as err:
            out["error"] = str(err)
        return out
    finally:
        try:
            live = studio.home / "live"
            live.mkdir(exist_ok=True)
            (live / "files.json").write_text(json.dumps(out), encoding="utf-8")
        except OSError:
            pass
        lock.release()


def kick(studio) -> None:
    """tidy in the background, after a note closes or opens again."""
    threading.Thread(target=tidy, args=(studio,), daemon=True, name="studio-files").start()


def bring(studio, nid: str, name: str) -> Path | None:
    """A file to look at: here if the note holds it, else fetched from the archive (or the peer) into live/."""
    path = here(studio.home, nid, name)
    if path:
        return path
    name = clean_name(name)
    cached = studio.home / "live" / FETCHED / nid / name
    if cached.is_file():
        return cached
    archive, peer = _places(studio)
    for place in (archive, peer):
        if place is None:
            continue
        try:
            if name in place.listing().get(nid, {}):
                place.get(nid, [name], cached.parent)
                if cached.is_file():
                    return cached
        except (FilesError, OSError, subprocess.SubprocessError):
            continue
    return None
