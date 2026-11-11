"""Share links: a few files from a Studio's library, for someone outside, until a set time.

A share is one record in the home, kept in git so the server's copy has it a minute later:

    <home>/shares/<id>.json    {"id", "token", "title", "files": [{"path", "name", "size"}], "created", "expires", "stopped"}

The link is the public address of the share server, then the token: https://example.com/share/<token>/
Only the files named in the record are reachable through it, only from the library, and only until it expires
or is stopped. The share server is its own small process (`studio.py serve-shares`): it reads the homes, never
writes them, answers GET and HEAD alone, and has no route to anything else in a Studio.

Where the public address comes from, first found: STUDIO_SHARE_URL, then [share] url in the home's
studio.toml or studio.local.toml, then [share] url in the app's hub.toml.
"""
from __future__ import annotations

import datetime
import hmac
import html
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from .store import Studio, StudioError, iso_now, read_json, tomllib, write_json

TOKEN = re.compile(r"[A-Za-z0-9_-]{32,64}")
SHARE_ID = re.compile(r"sh-[0-9a-f]{8}")
MAX_HOURS = 24 * 90          # three months at most: every link ends
MAX_FILES = 200
LENGTHS = {"h": 1, "d": 24, "w": 24 * 7}
# shown in the page itself; anything else is a download
INLINE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
          ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".m4v": "video/mp4",
          ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac", ".m4a": "audio/mp4",
          ".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8"}
HIDDEN = {"provenance.json"}


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


def _folder(studio: Studio) -> Path:
    return studio.home / "shares"


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


def make(studio: Studio, files: list, *, title: str = "", hours: str | int = "7d", by: str = "") -> dict:
    paths = _library_files(studio, files)
    hours = hours_of(hours)
    now = _now().replace(microsecond=0)
    rec = {
        "id": "sh-" + secrets.token_hex(4),
        "token": secrets.token_urlsafe(32),
        "title": (title or "").strip()[:120] or paths[0].parent.name,
        "files": [{"path": p.relative_to(studio.home.resolve()).as_posix(), "name": p.name, "size": p.stat().st_size}
                  for p in paths],
        "created": iso_now(),
        "expires": (now + datetime.timedelta(hours=hours)).isoformat().replace("+00:00", "Z"),
        "hours": hours,
        "stopped": None,
        "by": by,
    }
    write_json(_folder(studio) / f"{rec['id']}.json", rec)
    return dict(rec, state="live", url=link(studio, rec))


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
            out.append(dict(rec, state=state_of(rec, now), url=link(studio, rec)))
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
    if not TOKEN.fullmatch(token or ""):
        return None
    now = _now()
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
                return (home, rec) if state_of(rec, now) == "live" else None
    return None


def shared_file(home: Path, rec: dict, index: int) -> Path | None:
    files = rec.get("files") or []
    if not 0 <= index < len(files):
        return None
    lib = (home / "library").resolve()
    path = (home / str(files[index].get("path") or "")).resolve()
    return path if path.is_relative_to(lib) and path.is_file() else None


PAGE_CSP = ("default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
FILE_CSP = "sandbox; default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'"


def _size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def page(rec: dict) -> str:
    esc = html.escape
    ends = _parse(rec["expires"]).strftime("%d %b %Y, %H:%M UTC")
    items = []
    for i, f in enumerate(rec.get("files") or []):
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
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><meta name="referrer" content="no-referrer">
<title>{esc(rec.get("title") or "Shared files")}</title>
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
</style></head>
<body><main><h1>{esc(rec.get("title") or "Shared files")}</h1>
<p class="until">This link stops working on {esc(ends)}.</p>
<ul>{"".join(items)}</ul></main></body></html>
"""


GONE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>Link not found</title>
<style>body{margin:0;font:15px/1.5 system-ui,sans-serif;background:#111214;color:#ececec;display:grid;place-items:center;min-height:100vh}
p{max-width:34ch;text-align:center;padding:16px}</style></head>
<body><p>This link has expired, was stopped, or never existed.</p></body></html>
"""


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

        def gone(self):
            body = GONE.encode()
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
            found = find(roots, parts[0]) if parts else None
            if not found:
                return self.gone()
            home, rec = found
            if len(parts) == 1 and not split.path.endswith("/"):
                self.send_response(301)
                self.send_header("Location", quote(parts[0]) + "/")
                self.send_header("Content-Length", "0")
                self.common(PAGE_CSP)
                return self.end_headers()
            if len(parts) == 1:
                body = page(rec).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.common(PAGE_CSP)
                self.end_headers()
                if self.command == "GET":
                    self.wfile.write(body)
                return
            if len(parts) != 3 or not parts[1].isdigit():
                return self.gone()
            path = shared_file(home, rec, int(parts[1]))
            if path is None or path.name != parts[2]:
                return self.gone()
            self.send_shared(path, download="dl=1" in split.query)

        def send_shared(self, path: Path, download: bool):
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
            self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(path.name)}")
            self.common(FILE_CSP)
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
                    except (BrokenPipeError, ConnectionResetError):
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
