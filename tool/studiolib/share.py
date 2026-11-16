"""Share links: a few files from a Studio's library or inbox, for someone outside, until a set time.

A share is one record in the home, kept in git so the server's copy has it a minute later:

    <home>/shares/<id>.json    {"id", "token", "title", "files": [{"path", "name", "size", "group"?}], "batches"?,
                                "items", "created", "expires", "stopped"}

A live link's end can be moved to now plus a new time (`retime`), and a clip's still can follow the link (`add_still`).

The link is the public address of the share server, then the token: https://example.com/share/<token>/
Only the files named in the record are reachable through it, and only until it expires or is stopped. A file is
either in the library, or one of a candidate's own files in a batch as its batch.json lists it
(batches/<batch>/files/<candidate>/<name>: nothing else in the batch, no sample, nothing reached through a link);
the share server checks that again for every file it sends. A batch's files carry the candidate's name as their
"group", and the page shows them under it. A file gone since (a batch deleted) is left off the page, which says
how many are gone; a link whose files are all gone answers as a stopped one. The share server is its own small process (`studio.py serve-shares`): it reads the homes, never
writes them, answers GET and HEAD alone, and has no route to anything else in a Studio.

When the first file is a clip, the record may carry "still": true, and one frame of the clip is kept beside it as
<home>/shares/<id>.jpg; the link serves it at <token>/still.jpg, and nothing else from shares/. The page a link opens
carries Open Graph tags (its title, and the clip with its still, or the picture) so a chat such as Discord shows it;
their addresses start from STUDIO_SHARE_URL where the share server runs, else the public address the record was made
with ("base"). A link that does not open says why: it ended, it was stopped, or it is not here (yet: a new one takes
a minute or two to reach the server's copy). A link is made only in a Studio that has a copy on the server (a [sync]
in its settings, or the server's copy itself), since only that copy is served.

Where the public address comes from, first found: STUDIO_SHARE_URL, then [share] url in the home's
studio.toml or studio.local.toml, then [share] url in the app's hub.toml.
"""
from __future__ import annotations

import base64
import binascii
import datetime
import hmac
import html
import os
import re
import secrets
import shutil
import subprocess
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from .store import SAMPLE, Studio, StudioError, iso_now, read_json, tomllib, write_json

TOKEN = re.compile(r"[A-Za-z0-9_-]{32,64}")
SHARE_ID = re.compile(r"sh-[0-9a-f]{8}")
BATCH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
MAX_HOURS = 24 * 90          # three months at most: every link ends
MAX_FILES = 200
LENGTHS = {"h": 1, "d": 24, "w": 24 * 7}
# shown in the page itself; anything else is a download
INLINE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
          ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".m4v": "video/mp4",
          ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac", ".m4a": "audio/mp4",
          ".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8"}
HIDDEN = {"provenance.json"}
STILL_MAX = 1024 * 1024      # one frame of a clip, as JPEG
STILL_SIDE = 1280            # its long side at most, in pixels


def hours_of(text: str | int) -> int:
    """"36h", "7d", "2w" or a number of hours."""
    if isinstance(text, int):
        hours = text
    else:
        m = re.fullmatch(r"\s*(\d+)\s*([hdw]?)\s*", str(text).lower())
        if not m:
            raise StudioError(f"how long: say 12h, 7d or 2w, not {text!r}")
        hours = int(m.group(1)) * LENGTHS[m.group(2) or "h"]
    if not 1 <= hours <= MAX_HOURS:
        raise StudioError(f"a link lasts from 1 hour to {MAX_HOURS // 24} days")
    return hours


def _parse(stamp: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def state_of(rec: dict, now: datetime.datetime | None = None) -> str:
    if rec.get("stopped"):
        return "stopped"
    try:
        ends = _parse(rec["expires"])
    except (KeyError, ValueError):
        return "stopped"
    return "live" if (now or _now()) < ends else "expired"


def base_url(studio: Studio) -> str:
    url = os.environ.get("STUDIO_SHARE_URL") or str((studio.config.get("share") or {}).get("url") or "")
    if not url and tomllib is not None:
        from . import vault
        path = vault.settings_file()
        try:
            with open(path, "rb") as fh:
                url = str((tomllib.load(fh).get("share") or {}).get("url") or "")
        except (OSError, ValueError):
            url = ""
    return url if not url or url.endswith("/") else url + "/"


def link(studio: Studio, rec: dict) -> str:
    base = base_url(studio)
    return base + rec["token"] + "/" if base else ""


def clip_link(studio: Studio, rec: dict) -> str:
    """The clip's own address under the token, for a link that holds one clip and nothing else; a chat plays it in place."""
    base, files = base_url(studio), rec.get("files") or []
    if not base or len(files) != 1 or not _is_clip(str(files[0].get("name") or "")):
        return ""
    return base + rec["token"] + "/0/" + quote(str(files[0]["name"]))


def _folder(studio: Studio) -> Path:
    return studio.home / "shares"


def may_share(studio: Studio) -> None:
    """Links open only on the server's copy: refused in a Studio that has none, as every link made there would be dead."""
    if "sync" not in studio.config and not studio.config.get("site"):
        raise StudioError("this Studio has no copy on the server, so a link made here could never open; "
                          "put it on the server first (the studio-phone skill), then make the link")


def _is_clip(name: str) -> bool:
    return INLINE.get(Path(name).suffix.lower(), "").startswith("video/")


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """The width and height a JPEG states, or None when it is not one."""
    if not data.startswith(b"\xff\xd8"):
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = int.from_bytes(data[i + 5:i + 7], "big"), int.from_bytes(data[i + 7:i + 9], "big")
            return (width, height) if width and height else None
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


def check_still(data) -> bytes:
    """One frame of a clip, as the page or ffmpeg made it: a JPEG, 1 MB and 1280 px on its long side at most."""
    if isinstance(data, str):  # from the page: a data: address, or the bare base64
        try:
            data = base64.b64decode(data.split(",", 1)[1] if data.startswith("data:") else data, validate=True)
        except (binascii.Error, ValueError, IndexError):
            raise StudioError("the still is not a picture; send one frame of the clip as JPEG") from None
    if not isinstance(data, (bytes, bytearray)):
        raise StudioError("the still is not a picture; send one frame of the clip as JPEG")
    if len(data) > STILL_MAX:
        raise StudioError("the still is over 1 MB; send a smaller JPEG")
    size = jpeg_size(bytes(data))
    if not size:
        raise StudioError("the still is not a JPEG; send one frame of the clip as JPEG")
    if max(size) > STILL_SIDE:
        raise StudioError(f"the still is {size[0]} x {size[1]}; send one at most {STILL_SIDE} px on its long side")
    return bytes(data)


def grab_still(path: Path) -> bytes | None:
    """One frame of a clip, about a second in (the middle of a shorter one), made with ffmpeg; None without ffmpeg on PATH."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return None
    at = 1.0
    if path.suffix.lower() in (".mp4", ".m4v", ".mov"):
        from .checks import video_facts
        try:
            seconds = video_facts(path).get("seconds") or 0
        except Exception:  # noqa: BLE001 - a clip this cannot read is taken at one second
            seconds = 0
        if 0 < seconds < 2:
            at = seconds / 2
    for t in (at, 0.0):
        try:
            done = subprocess.run([exe, "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                                   "-vf", f"scale=w='min({STILL_SIDE},iw)':h='min({STILL_SIDE},ih)':force_original_aspect_ratio=decrease",
                                   "-q:v", "4", "-f", "mjpeg", "pipe:1"], capture_output=True, timeout=60,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return None
        try:
            if done.returncode == 0 and done.stdout:
                return check_still(done.stdout)
        except StudioError:
            pass
    return None


def _library_files(studio: Studio, given: list) -> list[Path]:
    lib = studio.library_dir.resolve()
    out: list[Path] = []
    for item in given:
        raw = Path(str(item).lstrip("/\\"))
        path = (raw if raw.is_absolute() else studio.home / raw).resolve()
        if not path.is_relative_to(lib) or path == lib:
            raise StudioError(f"{item}: only files in the library can be shared")
        if path.is_dir():
            found = sorted(p for p in path.rglob("*") if p.is_file() and not p.is_symlink() and p.name not in HIDDEN)
            if not found:
                raise StudioError(f"{item}: no files in it")
            out += found
        elif path.is_file():
            out.append(path)
        else:
            raise StudioError(f"{item}: no such file")
    seen, unique = set(), []
    for p in out:
        if p not in seen and p.resolve().is_relative_to(lib):
            seen.add(p)
            unique.append(p)
    if not unique:
        raise StudioError("name at least one file to share")
    if len(unique) > MAX_FILES:
        raise StudioError(f"one link holds {MAX_FILES} files at most")
    return unique


def candidate_file(home: Path, rel: str) -> Path | None:
    """A candidate's own file in a batch, as its batch.json lists it; None for anything else in the batch or the home."""
    parts = str(rel).split("/")
    if (len(parts) != 5 or parts[0] != "batches" or parts[2] != "files" or any(p in ("", ".", "..") for p in parts)
            or not BATCH_ID.fullmatch(parts[1]) or parts[1].startswith(SAMPLE) or parts[3].startswith("_")):
        return None
    home = Path(home).resolve()
    want = home.joinpath(*parts)
    try:
        if want.resolve().as_posix() != want.as_posix() or not want.is_file():  # a link on the way, or a name in the wrong case: refused
            return None
        batch = read_json(home / "batches" / parts[1] / "batch.json")
    except (OSError, StudioError):
        return None
    if not isinstance(batch, dict) or batch.get("sample") or not batch.get("filed"):
        return None
    for cand in batch.get("candidates") or []:
        if isinstance(cand, dict) and cand.get("id") == parts[3]:
            listed = [f.get("path") for f in cand.get("files") or [] if isinstance(f, dict)]
            return want if f"files/{parts[3]}/{parts[4]}" in listed else None
    return None


def _batch_files(studio: Studio, item: str) -> tuple[dict, list[tuple[Path, str]]]:
    """A batch, or one candidate of it as <batch>/<candidate>: its candidates' own files, each with the candidate's name."""
    parts = [p for p in item.replace("\\", "/").split("/") if p]
    if parts[:1] in (["batches"], ["samples"]):
        parts = parts[1:]
    if not 1 <= len(parts) <= 2 or not BATCH_ID.fullmatch(parts[0]):
        raise StudioError(f"{item}: share files in the library, a batch, or one candidate of it as <batch>/<candidate>")
    if parts[0].startswith(SAMPLE):
        raise StudioError(f"{parts[0]}: a sample is made up and is never shared; share a real batch")
    batch = read_json(studio.batches_dir / parts[0] / "batch.json")
    if not isinstance(batch, dict) or batch.get("id") != parts[0]:
        raise StudioError(f"no batch {parts[0]!r}; see: studio.py status")
    if batch.get("sample"):
        raise StudioError(f"{parts[0]}: a sample is made up and is never shared; share a real batch")
    if not batch.get("filed"):
        raise StudioError(f"{parts[0]} is not filed yet; share it once it is in the Inbox")
    cands = [c for c in batch.get("candidates") or [] if isinstance(c, dict)]
    if len(parts) == 2:
        cands = [c for c in cands if c.get("id") == parts[1]]
        if not cands:
            raise StudioError(f"batch {parts[0]} has no candidate {parts[1]!r}")
    out = []
    for cand in cands:
        name = str(cand.get("title") or cand.get("id") or "").strip()
        for f in cand.get("files") or []:
            path = candidate_file(studio.home, f"batches/{parts[0]}/{f.get('path') if isinstance(f, dict) else ''}")
            if path is not None:  # anything batch.json names outside the candidate's own folder is left out
                out.append((path, name))
    if not out:
        raise StudioError(f"{item}: nothing to share; " + ("this candidate has" if len(parts) == 2 else "its candidates have") + " no files")
    return batch, out


def make(studio: Studio, files: list, *, title: str = "", hours: str | int = "7d", by: str = "",
         still=None, grab: bool = False) -> dict:
    """A link to library files, to a batch's candidates (<batch>), or to one of them (<batch>/<candidate>).

    When the first file is a clip, `still` (one frame of it, as JPEG) is kept beside the record for a chat's preview,
    and `grab` makes one with ffmpeg when none is given. A still sent with anything else is left out."""
    may_share(studio)
    found: list[tuple[Path, str, str]] = []  # the file, the candidate's name, its batch
    batches: list[dict] = []
    for item in files:
        raw = Path(str(item).lstrip("/\\"))
        if raw.is_absolute() or raw.parts[:1] == ("library",):
            found += [(p, "", "") for p in _library_files(studio, [item])]
        else:
            batch, got = _batch_files(studio, str(item))
            if batch["id"] not in [b["id"] for b in batches]:
                batches.append(batch)
            found += [(p, name, batch["id"]) for p, name in got]
    seen, unique = set(), []
    for p, name, bid in found:
        if p not in seen:
            seen.add(p)
            unique.append((p, name, bid))
    if not unique:
        raise StudioError("name at least one file to share")
    if len(unique) > MAX_FILES:
        raise StudioError(f"one link holds {MAX_FILES} files at most")
    titles = {b["id"]: str(b.get("title") or b["id"]) for b in batches}
    hours = hours_of(hours)
    clip = _is_clip(unique[0][0].name)
    still = check_still(still) if clip and still else None
    if clip and still is None and grab:
        still = grab_still(unique[0][0])
    now = _now().replace(microsecond=0)
    first = unique[0]
    rec = {
        "id": "sh-" + secrets.token_hex(4),
        "token": secrets.token_urlsafe(32),
        "title": (title or "").strip()[:120] or (titles[first[2]] if first[2] else first[0].parent.name),
        "files": [dict({"path": p.relative_to(studio.home.resolve()).as_posix(), "name": p.name, "size": p.stat().st_size},
                       **({"group": titles[bid] + ": " + name if len(batches) > 1 else name} if bid else {}))
                  for p, name, bid in unique],
        "created": iso_now(),
        "expires": (now + datetime.timedelta(hours=hours)).isoformat().replace("+00:00", "Z"),
        "hours": hours,
        "stopped": None,
        "by": by,
        "items": [str(i) for i in files],  # as asked, so the page finds the link it made for the same files
    }
    if batches:
        rec["batches"] = [b["id"] for b in batches]
    if base_url(studio):
        rec["base"] = base_url(studio)  # so the page the link opens names its own files in full, for a chat's preview
    if still:
        rec["still"] = True
        _folder(studio).mkdir(parents=True, exist_ok=True)
        (_folder(studio) / f"{rec['id']}.jpg").write_bytes(still)  # before the record, so a record that says so has it
    write_json(_folder(studio) / f"{rec['id']}.json", rec)
    return dict(rec, state="live", url=link(studio, rec), clip_url=clip_link(studio, rec), clip=clip, still=bool(still))


def listing(studio: Studio) -> list[dict]:
    folder = _folder(studio)
    if not folder.is_dir():
        return []
    now = _now()
    out = []
    for p in folder.glob("sh-*.json"):
        try:
            rec = read_json(p)
        except StudioError:
            continue
        if isinstance(rec, dict) and rec.get("token"):
            out.append(dict(rec, state=state_of(rec, now), url=link(studio, rec), clip_url=clip_link(studio, rec)))
    out.sort(key=lambda r: r.get("created") or "", reverse=True)
    return out


def stop(studio: Studio, share_id: str) -> dict:
    if not SHARE_ID.fullmatch(share_id or ""):
        raise StudioError(f"no share {share_id!r}")
    path = _folder(studio) / f"{share_id}.json"
    rec = read_json(path)
    if not rec:
        raise StudioError(f"no share {share_id!r}")
    if not rec.get("stopped"):
        rec["stopped"] = iso_now()
        write_json(path, rec)
    return dict(rec, state="stopped", url=link(studio, rec))


def _live(studio: Studio, share_id: str) -> tuple[Path, dict]:
    """A live link's record and where it is kept; refused for any other id."""
    if not SHARE_ID.fullmatch(share_id or ""):
        raise StudioError(f"no share {share_id!r}")
    path = _folder(studio) / f"{share_id}.json"
    rec = read_json(path)
    if not isinstance(rec, dict) or rec.get("id") != share_id or not rec.get("token"):
        raise StudioError(f"no share {share_id!r}")
    if state_of(rec) != "live":
        raise StudioError(f"{share_id} has ended; share it again for a new link")
    return path, rec


def retime(studio: Studio, share_id: str, time: str | int) -> dict:
    """A live link's end moved to now plus that time, 1 hour to 90 days."""
    path, rec = _live(studio, share_id)
    hours = hours_of(time)
    now = _now().replace(microsecond=0)
    rec["expires"] = (now + datetime.timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    rec["hours"] = hours
    write_json(path, rec)
    return dict(rec, state=state_of(rec), url=link(studio, rec), clip_url=clip_link(studio, rec))


def add_still(studio: Studio, share_id: str, still) -> dict:
    """One frame of a live link's first clip, kept beside its record for a chat's preview."""
    path, rec = _live(studio, share_id)
    files = rec.get("files") or []
    if not files or not _is_clip(str(files[0].get("name") or "")):
        raise StudioError(f"{share_id} does not open with a clip; a still goes only with a clip")
    data = check_still(still)
    (_folder(studio) / f"{share_id}.jpg").write_bytes(data)  # before the record, so a record that says so has it
    rec["still"] = True
    write_json(path, rec)
    return dict(rec, state=state_of(rec), url=link(studio, rec), clip_url=clip_link(studio, rec))


class _Stay(urllib.request.HTTPRedirectHandler):
    """Refuse to follow a redirect, so a sign-in page elsewhere never reads as the link working."""

    def redirect_request(self, *a, **k):
        return None


def check_live(studio: Studio, share_id: str, timeout: float = 4.0) -> dict:
    """Whether the link answers on the public server yet: one HEAD to the public address, asked by the PC, never by the page."""
    if not SHARE_ID.fullmatch(share_id or ""):
        raise StudioError(f"no share {share_id!r}")
    rec = read_json(_folder(studio) / f"{share_id}.json")
    if not isinstance(rec, dict) or not rec.get("token"):
        raise StudioError(f"no share {share_id!r}")
    url = link(studio, rec)
    if state_of(rec) != "live":  # stopped or run out, here or elsewhere: the page lets it go
        return {"public": bool(url), "live": False, "ended": True}
    if not url:
        return {"public": False, "live": False}
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "NocStudio link check"})
    try:
        with urllib.request.build_opener(_Stay).open(req, timeout=timeout) as res:  # a 3xx raises, so it is not live
            live = res.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        live = False
    return {"public": True, "live": live}


# ------------------------------------------------------------------ the public server
def homes_under(roots: list) -> list[Path]:
    """Each root that is a Studio home, and each folder right under a root that is one."""
    out = []
    for root in roots:
        root = Path(root)
        if (root / "studio.toml").is_file():
            out.append(root)
        elif root.is_dir():
            out += sorted(p for p in root.iterdir() if p.is_dir() and (p / "studio.toml").is_file())
    return out


def find(roots: list, token: str) -> tuple[Path, dict] | None:
    """The live share with this token, and its home; None for anything else, all alike."""
    found = lookup(roots, token)
    return found if found and state_of(found[1]) == "live" else None


def lookup(roots: list, token: str) -> tuple[Path, dict] | None:
    """The share with this token, live or not, and its home; None when no record has it."""
    if not TOKEN.fullmatch(token or ""):
        return None
    for home in homes_under(roots):
        folder = home / "shares"
        if not folder.is_dir():
            continue
        for p in folder.glob("sh-*.json"):
            try:
                rec = read_json(p)
            except StudioError:
                continue
            if (isinstance(rec, dict) and isinstance(rec.get("token"), str)
                    and hmac.compare_digest(rec["token"].encode(), token.encode())):
                return home, rec
    return None


def shared_file(home: Path, rec: dict, index: int) -> Path | None:
    files = rec.get("files") or []
    if not 0 <= index < len(files):
        return None
    lib = (home / "library").resolve()
    rel = str(files[index].get("path") or "")
    path = (home / rel).resolve()
    if path.is_relative_to(lib) and path.is_file():
        return path
    return candidate_file(home, rel)  # one of a candidate's own files, still listed in its batch, or nothing


def still_file(home: Path, rec: dict) -> Path | None:
    """The still kept beside a record that says it has one: shares/<its id>.jpg, and never any other file there."""
    sid = str(rec.get("id") or "")
    if rec.get("still") is not True or not SHARE_ID.fullmatch(sid):
        return None
    path = Path(home) / "shares" / f"{sid}.jpg"
    try:
        own = read_json(path.with_suffix(".json"), {}) or {}  # the record kept under that id is this one: no record reaches another's still
        if not (isinstance(own, dict) and own.get("token") == rec.get("token")):
            return None
        return path if path.is_file() and not path.is_symlink() else None
    except (OSError, StudioError):
        return None


def public_base(rec: dict) -> str:
    """Where the share server is reached from outside: STUDIO_SHARE_URL where it runs, else the address the link was made with."""
    url = os.environ.get("STUDIO_SHARE_URL") or str(rec.get("base") or "")
    if not re.fullmatch(r"https?://[^\s\"'<>]+", url):
        return ""
    return url if url.endswith("/") else url + "/"


def og_tags(home: Path, rec: dict, present: list | None = None) -> str:
    """The tags a chat reads to show a link (Discord runs no script): its title, and the clip with its still, or the picture."""
    esc = html.escape
    files = rec.get("files") or []
    shown = [i for i in range(len(files)) if present is None or (i < len(present) and present[i])]
    title = str(rec.get("title") or "Shared files")
    ends = _parse(rec["expires"]).strftime("%d %b %Y")
    tags = [("og:title", title), ("og:site_name", "NocStudio"),
            ("og:description", f"{len(shown)} {'file' if len(shown) == 1 else 'files'}, shared until {ends}.")]
    base = public_base(rec)
    page_url = base + quote(str(rec.get("token") or "")) + "/" if base else ""
    name = str(files[shown[0]].get("name") or "") if shown else ""
    kind = INLINE.get(Path(name).suffix.lower(), "")
    still = still_file(home, rec) if page_url else None
    card = "summary"
    if page_url:
        tags.append(("og:url", page_url))
    if page_url and kind.startswith("video/") and still:  # a record from before stills has none: its title alone
        clip = page_url + f"{shown[0]}/{quote(name)}"
        size = None
        path = shared_file(home, rec, shown[0])
        if path is not None and path.suffix.lower() in (".mp4", ".m4v", ".mov"):
            from .checks import video_facts
            try:
                facts = video_facts(path)
                size = (facts["width"], facts["height"]) if facts.get("width") else None
            except Exception:  # noqa: BLE001 - a clip this cannot read takes its shape from the still
                size = None
        try:
            frame = jpeg_size(still.read_bytes())
        except OSError:
            frame = None
        if frame and not size:
            size = frame
        elif frame and size and size[0] != size[1] and (size[0] > size[1]) != (frame[0] > frame[1]):
            size = (size[1], size[0])  # a phone clip stored on its side and turned when played: the still shows how it plays
        tags += [("og:type", "video.other"), ("og:video", clip), ("og:video:url", clip)]
        if clip.startswith("https://"):
            tags.append(("og:video:secure_url", clip))
        tags.append(("og:video:type", kind))
        if size:
            tags += [("og:video:width", str(size[0])), ("og:video:height", str(size[1]))]
        tags += [("og:image", page_url + "still.jpg"), ("og:image:type", "image/jpeg")]
        if frame:
            tags += [("og:image:width", str(frame[0])), ("og:image:height", str(frame[1]))]
        card = "player"
        tags += [("twitter:player", clip), ("twitter:player:stream", clip), ("twitter:player:stream:content_type", kind)]
        if size:
            tags += [("twitter:player:width", str(size[0])), ("twitter:player:height", str(size[1]))]
        tags.append(("twitter:image", page_url + "still.jpg"))
    elif page_url and kind.startswith("image/"):
        pic = page_url + f"{shown[0]}/{quote(name)}"
        tags += [("og:type", "website"), ("og:image", pic), ("og:image:type", kind), ("twitter:image", pic)]
        card = "summary_large_image"
    else:
        tags.append(("og:type", "website"))
    tags += [("twitter:card", card), ("twitter:title", title)]
    return "\n".join(f'<meta {"name" if k.startswith("twitter:") else "property"}="{k}" content="{esc(v)}">' for k, v in tags)


PAGE_CSP = ("default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
FILE_CSP = "sandbox; default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'"
# a clip or a sound opened on its own (the link straight to a clip): a sandbox would make the browser's player a page of
# no origin that may not load the file it shows; it runs no script either way, as its type is fixed and never sniffed
MEDIA_CSP = "default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'"


def _size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def page(rec: dict, present: list | None = None, og: str = "") -> str:
    """The page a link opens: its files, under each candidate's name when they came from a batch; none that are gone."""
    esc = html.escape
    ends = _parse(rec["expires"]).strftime("%d %b %Y, %H:%M UTC")
    items, groups = [], {}
    for i, f in enumerate(rec.get("files") or []):
        if present is not None and not (i < len(present) and present[i]):
            continue
        name = str(f.get("name") or "file")
        href = f"{i}/{quote(name)}"
        ext = Path(name).suffix.lower()
        kind = INLINE.get(ext, "").split("/")[0]
        if kind == "image":
            show = f'<a href="{href}"><img src="{href}" alt="{esc(name)}" loading="lazy"></a>'
        elif kind == "video":
            show = f'<video src="{href}" controls playsinline preload="metadata"></video>'
        elif kind == "audio":
            show = f'<audio src="{href}" controls preload="metadata"></audio>'
        else:
            show = ""
        items.append(f'<li>{show}<div class="row"><span class="name">{esc(name)}</span>'
                     f'<span class="size">{_size(int(f.get("size") or 0))}</span>'
                     f'<a class="dl" href="{href}?dl=1">Download</a></div></li>')
        groups.setdefault(str(f.get("group") or ""), []).append(items[-1])
    if any(groups):  # from a batch: each candidate's files under its name
        body = "".join(f'<section><h2>{esc(g or "Other files")}</h2><ul>{"".join(lis)}</ul></section>' for g, lis in groups.items())
    else:
        body = f'<ul>{"".join(items)}</ul>'
    gone = len(rec.get("files") or []) - len(items)
    if gone:
        body = f'<p class="gone">{"One file" if gone == 1 else f"{gone} files"} in this link {"is" if gone == 1 else "are"} no longer here.</p>' + body
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><meta name="referrer" content="no-referrer">
<title>{esc(rec.get("title") or "Shared files")}</title>
{og}
<style>
:root {{ color-scheme: light dark; --bg: #f6f6f4; --fg: #1b1b1b; --muted: #666; --card: #fff; --line: #ddd; --accent: #c4262f; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #111214; --fg: #ececec; --muted: #9a9a9a; --card: #1a1b1e; --line: #2c2d31; --accent: #e0484f; }} }}
body {{ margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; padding: 24px 16px 48px; }}
h1 {{ font-size: 22px; margin: 0 0 4px; overflow-wrap: anywhere; }}
p.until {{ color: var(--muted); margin: 0 0 20px; }}
ul {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 16px; }}
li {{ background: var(--card); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
img, video {{ display: block; width: 100%; max-height: 80vh; object-fit: contain; background: #000; }}
audio {{ display: block; width: calc(100% - 24px); margin: 12px; }}
.row {{ display: flex; gap: 12px; align-items: center; padding: 10px 12px; flex-wrap: wrap; }}
.name {{ flex: 1 1 200px; overflow-wrap: anywhere; }}
.size {{ color: var(--muted); font-size: 13px; }}
a.dl {{ color: var(--accent); font-weight: 600; text-decoration: none; }}
section {{ margin: 0 0 28px; }}
h2 {{ font-size: 17px; margin: 0 0 10px; overflow-wrap: anywhere; }}
p.gone {{ color: var(--muted); margin: 0 0 16px; }}
</style></head>
<body><main><h1>{esc(rec.get("title") or "Shared files")}</h1>
<p class="until">This link stops working on {esc(ends)}.</p>
{body}</main></body></html>
"""


GONE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>{title}</title>
<style>body{{margin:0;font:15px/1.5 system-ui,sans-serif;background:#111214;color:#ececec;display:grid;place-items:center;min-height:100vh}}
p{{max-width:36ch;text-align:center;padding:16px}}</style></head>
<body><p>{said}</p></body></html>
"""
NOT_HERE = "This link is not here. A new link takes a minute or two to reach the server; try again shortly."
STOPPED = "This link was stopped."
NOT_IN_LINK = "This file is not part of the link."


def gone_page(rec: dict | None, said: str = "") -> str:
    """The page for a link that does not open, saying which it is: ended, stopped or not here; never its token or its files."""
    if not said:
        if rec and state_of(rec) == "expired":
            said = "This link ended on " + _parse(rec["expires"]).strftime("%d %b %Y, %H:%M UTC") + "."
        else:
            said = STOPPED if rec else NOT_HERE
    title = "Link ended" if said.startswith("This link ended") else "Link stopped" if said == STOPPED else "Link not found"
    return GONE.format(title=title, said=html.escape(said))


def make_share_handler(roots: list, quiet: bool = True):
    class Handler(BaseHTTPRequestHandler):
        server_version = "share"
        sys_version = ""

        def log_message(self, fmt, *args):  # never the token in a log
            if not quiet:
                super().log_message("%s", re.sub(r"/[A-Za-z0-9_-]{32,64}", "/<token>", fmt % args))

        def common(self, csp: str):
            self.send_header("Content-Security-Policy", csp)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")

        def gone(self, rec: dict | None = None, said: str = ""):
            body = gone_page(rec, said).encode()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.common(PAGE_CSP)
            self.end_headers()
            if self.command == "GET":
                self.wfile.write(body)

        def do_POST(self):
            self.send_error(405)

        do_PUT = do_DELETE = do_PATCH = do_POST

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            split = urlsplit(self.path)
            parts = [unquote(p) for p in split.path.split("/") if p]
            if parts[:1] == ["share"]:  # reached without the proxy taking its prefix off
                parts = parts[1:]
            found = lookup(roots, parts[0]) if parts else None
            if not found:
                return self.gone()
            home, rec = found
            if state_of(rec) != "live":  # ended or stopped: it says which, and nothing of what it held
                return self.gone(rec)
            if len(parts) == 1 and not split.path.endswith("/"):
                self.send_response(301)
                self.send_header("Location", quote(parts[0]) + "/")
                self.send_header("Content-Length", "0")
                self.common(PAGE_CSP)
                return self.end_headers()
            if len(parts) == 1 or parts[1:] == ["still.jpg"]:
                present = [shared_file(home, rec, i) is not None for i in range(len(rec.get("files") or []))]
                if not any(present):  # every file gone: the link is over
                    return self.gone(rec, STOPPED)
                if len(parts) == 2:  # the frame of the clip a chat shows: the one file in shares/ a link reaches
                    still = still_file(home, rec)
                    return self.send_shared(still, download=False, name="still.jpg") if still else self.gone(rec, NOT_IN_LINK)
                body = page(rec, present, og_tags(home, rec, present)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.common(PAGE_CSP)
                self.end_headers()
                if self.command == "GET":
                    self.wfile.write(body)
                return
            if len(parts) != 3 or not parts[1].isdigit():
                return self.gone(rec, NOT_IN_LINK)
            path = shared_file(home, rec, int(parts[1]))
            if path is None or path.name != parts[2]:
                return self.gone(rec, NOT_IN_LINK)
            self.send_shared(path, download="dl=1" in split.query)

        def send_shared(self, path: Path, download: bool, name: str = ""):
            size = path.stat().st_size
            known = INLINE.get(path.suffix.lower())  # anything not on the list goes out as bytes to save, never to run
            ctype = known or "application/octet-stream"
            disposition = "inline" if known and not download else "attachment"
            start, end, status = 0, size - 1, 200
            rng = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "") or "")
            if rng and size:
                a, b = rng.groups()
                if a == "" and b:
                    start = max(0, size - int(b))
                elif a:
                    start = int(a)
                    end = min(int(b), size - 1) if b else size - 1
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(name or path.name)}")
            self.common(MEDIA_CSP if disposition == "inline" and ctype.startswith(("video/", "audio/")) else FILE_CSP)
            self.end_headers()
            if self.command != "GET":
                return
            with open(path, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(1 << 16, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):  # the player stopped asking: seeking, or closed
                        return
                    left -= len(chunk)

    return Handler


def serve(roots: list, host: str = "127.0.0.1", port: int = 8780, quiet: bool = True) -> None:
    homes = homes_under(roots)
    if not homes:
        raise StudioError("no Studio home under " + ", ".join(str(r) for r in roots))
    server = ThreadingHTTPServer((host, port), make_share_handler(roots, quiet=quiet))
    server.daemon_threads = True
    print(f"Share links on http://{host}:{port}/ for {len(homes)} Studio home(s); read only", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
