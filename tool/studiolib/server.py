"""The web server. Standard library only; listens on this machine alone unless told the names it may answer to."""
from __future__ import annotations

import json
import mimetypes
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .store import Studio, StudioError, slugify

WEB = Path(__file__).resolve().parent.parent / "web"
TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".html": "text/html; charset=utf-8", ".json": "application/json", ".md": "text/markdown; charset=utf-8",
         ".txt": "text/plain; charset=utf-8", ".glb": "model/gltf-binary", ".gltf": "model/gltf+json",
         ".wav": "audio/wav", ".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".flac": "audio/flac",
         ".mp4": "video/mp4", ".webm": "video/webm", ".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"}
MAX_BODY = 2 * 1024 * 1024
LOCK = threading.Lock()  # one writer at a time; the files are the database


def make_handler(home: Path, allowed_hosts: set[str], quiet: bool = False, hub: str = "", seen=None):
    """`hub` is the Studio app's menu, when this Studio was started from it; `seen` is called on every request."""
    class Handler(BaseHTTPRequestHandler):
        server_version = "Studio/0.1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # quiet: one line per write, none per read
            if self.command != "GET" and not quiet:
                sys.stderr.write("  %s %s\n" % (self.command, self.path))

        # ------------------------------------------------------------ helpers
        def studio(self) -> Studio:
            return Studio(home)  # read fresh: Claude Code edits these files while the page is open

        def send_json(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def fail(self, status, message):
            self.send_json({"error": message}, status)

        def send_file(self, path: Path):
            try:
                size = path.stat().st_size
            except OSError:
                return self.fail(404, "no such file")
            ctype = TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
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
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "no-cache")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD":
                return
            with open(path, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(65536, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        def under(self, root: Path, rel: str) -> Path | None:
            root = root.resolve()
            path = (root / rel).resolve()
            return path if path.is_relative_to(root) and path.is_file() else None

        def guard(self) -> bool:
            """Refuse anything that is not this machine talking to itself."""
            if seen:
                seen()
            host = (self.headers.get("Host") or "").lower()
            if host not in allowed_hosts:
                self.fail(403, "this server answers only on its own address")
                return False
            if self.command != "GET" and self.command != "HEAD":
                origin = self.headers.get("Origin")
                if origin and urlsplit(origin).netloc.lower() not in allowed_hosts:
                    self.fail(403, "cross-site request refused")
                    return False
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    self.fail(415, "send JSON")
                    return False
            return True

        def body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise StudioError("request too large")
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError) as err:
                raise StudioError(f"bad JSON: {err}") from err
            if not isinstance(data, dict):
                raise StudioError("send a JSON object")
            return data

        # ------------------------------------------------------------- routes
        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self.guard():
                return
            parts = [unquote(p) for p in urlsplit(self.path).path.split("/") if p]
            try:
                if not parts:
                    return self.send_file(WEB / "index.html")
                head = parts[0]
                if head == "web" and len(parts) > 1:
                    path = self.under(WEB, "/".join(parts[1:]))
                    return self.send_file(path) if path else self.fail(404, "no such file")
                if head == "api":
                    studio = self.studio()
                    if parts[1:] == ["state"]:
                        return self.send_json(dict(studio.state(), hub=hub))
                    if parts[1:] == ["pulse"]:
                        return self.send_json({"stamp": studio.stamp()})
                    if parts[1:] == ["live"]:
                        from . import board
                        return self.send_json(board.live(studio))
                    if len(parts) == 3 and parts[1] == "batch":
                        return self.send_json(studio.load_batch(parts[2]))
                    return self.fail(404, "no such route")
                if head == "files" and len(parts) > 2:
                    studio = self.studio()
                    path = self.under(studio.batch_dir(parts[1]), "/".join(parts[2:]))
                    return self.send_file(path) if path else self.fail(404, "no such file")
                if head == "library" and len(parts) > 1:
                    path = self.under(self.studio().library_dir, "/".join(parts[1:]))
                    return self.send_file(path) if path else self.fail(404, "no such file")
                if head == "motions" and len(parts) == 2:
                    path = self.under(self.studio().motions_dir, parts[1])
                    return self.send_file(path) if path else self.fail(404, "no such file")
                if head == "game" and len(parts) > 1:
                    return self.send_file(self.studio().game_file("/".join(parts[1:])))
                if head == "pt" and len(parts) > 2 and parts[1].isdigit():
                    return self.send_file(self.studio().playtest_file(int(parts[1]), "/".join(parts[2:])))
                return self.fail(404, "no such page")
            except StudioError as err:
                return self.fail(404, str(err))

        def do_PUT(self):
            self.write()

        def do_POST(self):
            self.write()

        def write(self):
            started = time.time_ns()
            try:
                self._write()
            finally:  # what this click changed, so a sync can send it while a session works on other files
                from . import sync
                try:
                    sync.page_wrote(home, started, urlsplit(self.path).path)
                except Exception:  # noqa: BLE001 - the click itself went through
                    pass

        def _write(self):
            if not self.guard():
                return
            parts = [unquote(p) for p in urlsplit(self.path).path.split("/") if p]
            try:
                data = self.body()
                with LOCK:
                    studio = self.studio()
                    if len(parts) == 4 and parts[:2] == ["api", "batch"]:
                        batch_id, verb = parts[2], parts[3]
                        if verb == "draft":
                            studio.save_draft(batch_id, data)
                            return self.send_json({"ok": True})
                        if verb == "submit":
                            return self.send_json({"ok": True, "verdict": studio.submit(batch_id, data),
                                                   "pending": len(studio.todo())})
                        if verb == "reopen":
                            studio.reopen(batch_id)
                            return self.send_json({"ok": True})
                        if verb == "reset":
                            studio.reset_sample(batch_id)
                            return self.send_json({"ok": True})
                    if parts == ["api", "decisions"]:
                        record = studio.add_decision(title=str(data.get("title") or ""),
                                                     his_words=str(data.get("his_words") or ""),
                                                     ruling=str(data.get("ruling") or ""),
                                                     source_type="studio", ref="written by hand",
                                                     tags=[str(t) for t in data.get("tags") or []][:12])
                        return self.send_json({"ok": True, "decision": record})
                    if parts == ["api", "triage"]:
                        key = str(data.get("key") or "")
                        if not re.fullmatch(r"[^/\\]+/f8-\d+", key):
                            raise StudioError("bad playtest note key")
                        confirmed = data.get("confirmed")
                        entry = studio.set_triage(key, confirmed=confirmed if isinstance(confirmed, bool) else None,
                                                  confirm_note=str(data.get("confirm_note") or ""))
                        return self.send_json({"ok": True, "triage": entry})
                    if parts == ["api", "ui"]:
                        return self.send_json({"ok": True, "ui": studio.set_ui(scale=data.get("scale"), theme=data.get("theme"))})
                    if parts == ["api", "note"]:
                        note = studio.add_note(str(data.get("text") or ""), kind=str(data.get("kind") or ""),
                                               urgent=bool(data.get("urgent")))
                        return self.send_json({"ok": True, "note": note})
                    if len(parts) == 3 and parts[:2] == ["api", "note"]:
                        note = studio.answer_note(parts[2], str(data.get("action") or ""), text=str(data.get("text") or ""),
                                                  kind=str(data.get("kind") or ""), session=str(data.get("session") or ""))
                        return self.send_json({"ok": True, "note": note})
                    if parts == ["api", "hand"]:
                        row = studio.answer_hand(str(data.get("id") or ""), str(data.get("action") or ""),
                                                 str(data.get("note") or ""))
                        return self.send_json({"ok": True, "hand": row})
                return self.fail(404, "no such route")
            except StudioError as err:
                return self.fail(400, str(err))

    return Handler


def serve(home, port: int = 0, host: str = "", open_browser: bool = False, hosts=()) -> None:
    """`hosts`: other names the page is reached by, as the browser and any proxy in front say them
    (a server's copy behind a login, such as "apps.example.com" and "studio-app:8771"); also [serve] hosts."""
    from . import sync
    studio = Studio(home)
    served = studio.config.get("serve") or {}
    port = port or int(served.get("port") or studio.config.get("port") or 8770)
    host = host or str(served.get("host") or "127.0.0.1")
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if host not in ("127.0.0.1", "localhost", "0.0.0.0"):
        allowed.add(f"{host}:{port}")
    allowed |= {str(x).lower() for x in [*(served.get("hosts") or []), *hosts] if x}
    httpd = ThreadingHTTPServer((host, port), make_handler(studio.home, allowed))
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    syncing = sync.start(studio.home)
    print(f"Studio for {studio.config.get('project')}")
    print(f"  home  {studio.home}")
    print(f"  open  {url}   (Ctrl+C stops it)")
    if syncing:
        print(f"  sync  every {sync.settings(studio)['every']} s with the git remote (live/sync.json)")
    if open_browser:
        import webbrowser
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


def glance(home) -> dict:
    """What waits in one Studio, for a menu of them all."""
    studio = Studio(home)
    status = [studio.load_batch(b)["status"] for b in studio.batch_ids()]
    return {"judge": sum(s in ("open", "draft") for s in status), "sent": status.count("submitted"),
            "hands": sum(1 for x in studio.hands() if x.get("status") == "open"),
            "notes": sum(1 for n in studio.notes_view() if n.get("waits") == "you")}


def studios_by_name(homes) -> dict:
    """Each Studio home under the name it is served at, from its project's name."""
    studios = {}
    for home in homes:
        studio = Studio(home)
        slug = slugify(str(studio.config.get("project") or studio.home.name))
        if slug in studios or slug in ("web", "api"):
            raise StudioError(f"two Studios would both be at /{slug}/: give one another project name")
        studios[slug] = studio.home
    return studios


def menu_handler(studios: dict, allowed: set[str]):
    """The handler for several Studios behind one address: the menu at /, each Studio at /<its name>/."""
    handlers = {slug: make_handler(home, allowed, quiet=True, hub="../") for slug, home in studios.items()}

    class Menu(handlers[next(iter(handlers))]):
        def pass_on(self, verb: str) -> bool:
            """A request for one Studio goes to it, with its name taken off the path. The handler is that
            Studio's for this one request only: the next one on the same connection may be for another."""
            split = urlsplit(self.path)
            parts = split.path.split("/")
            if len(parts) < 2 or unquote(parts[1]) not in handlers:
                return False
            self.__class__ = handlers[unquote(parts[1])]
            self.path = "/" + "/".join(parts[2:]) + ("?" + split.query if split.query else "")
            try:
                getattr(self, verb)()
            finally:
                self.__class__ = Menu
            return True

        def do_GET(self):
            if self.pass_on("do_GET"):
                return
            if not self.guard():
                return
            parts = [unquote(p) for p in urlsplit(self.path).path.split("/") if p]
            if not parts:
                return self.send_file(WEB / "hub.html")
            if parts == ["api", "hub"]:
                rows = []
                for slug, home in studios.items():
                    try:
                        rows.append(dict(glance(home), name=Studio(home).config.get("project") or slug, url=slug + "/", home=str(home)))
                    except StudioError as err:
                        rows.append({"name": slug, "url": slug + "/", "missing": True, "why": str(err)})
                return self.send_json({"studio_hub": True, "served": True, "studios": rows, "ui": Studio.ui()})
            if parts[0] == "web" and len(parts) > 1:
                path = self.under(WEB, "/".join(parts[1:]))
                return self.send_file(path) if path else self.fail(404, "no such file")
            return self.fail(404, "no such page")

        def write(self):
            if self.pass_on("write"):
                return
            return self.fail(404, "no such route") if self.guard() else None

    return Menu


def serve_all(homes, port: int = 0, host: str = "", hosts=()) -> None:
    """Several Studios behind one address, for a server. The first home's [serve] settings are used for all
    (host, port, the names it answers to)."""
    from . import sync
    studios = studios_by_name(homes)
    first = Studio(next(iter(studios.values())))
    served = first.config.get("serve") or {}
    port = port or int(served.get("port") or 8771)
    host = host or str(served.get("host") or "127.0.0.1")
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if host not in ("127.0.0.1", "localhost", "0.0.0.0"):
        allowed.add(f"{host}:{port}")
    allowed |= {str(x).lower() for x in [*(served.get("hosts") or []), *hosts] if x}
    httpd = ThreadingHTTPServer((host, port), menu_handler(studios, allowed))
    httpd.daemon_threads = True
    for home in studios.values():
        sync.start(home)
    print(f"{len(studios)} Studio{'s' if len(studios) != 1 else ''} at http://127.0.0.1:{port}/   (Ctrl+C stops them)")
    for slug, home in studios.items():
        print(f"  /{slug}/  {home}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
