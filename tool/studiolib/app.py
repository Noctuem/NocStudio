"""NocStudio, the Studio app: one window with a menu of every project's Studio.

The user opens it from the Start menu. The menu lists the Studios in studios.json; the one they pick is
started and shown in the same window. Nothing runs before the window opens, and when it closes
every Studio this app started stops with it. Standard library only; the window is the browser
already on the machine (Edge, else Chrome) in its app mode, with a profile of its own so that the
window's life can be told apart from the user's everyday browser's.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import setup, sync
from .server import MAX_BODY, TYPES, WEB, glance, make_handler
from .store import Studio, StudioError

HUB_PORT = 8760
IDLE_SECONDS = 180  # with no window of its own to wait on, the app stops this long after the pages go quiet
NAME = "NocStudio"
DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / NAME
SHORTCUT = NAME + ".lnk"
OLD = ("Studio", "Studio.lnk")  # what the app's folder and shortcut were called before it had its name


class Server(ThreadingHTTPServer):
    allow_reuse_address = False  # on Windows the default would let two servers share a port
    daemon_threads = True


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=3) as res:
            return json.loads(res.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


class Hub:
    """The menu's own small server, and the Studios it has started."""

    def __init__(self, registry: Path | None = None, port: int = HUB_PORT):
        self.registry = registry
        self.lock = threading.Lock()
        self.running: dict[int, Server] = {}
        self.seen = time.monotonic()
        self.httpd = Server(("127.0.0.1", port), self._handler())
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def touch(self) -> None:
        self.seen = time.monotonic()

    def rows(self) -> list[dict]:
        out = []
        for r in setup.studios(self.registry):
            row = {"name": r.get("name") or Path(r["home"]).name, "home": r["home"], "repo": r.get("repo", ""),
                   "running": r.get("port") in self.running, "missing": False}
            try:
                row.update(glance(r["home"]))
            except StudioError as err:
                row.update(missing=True, why=str(err))
            out.append(row)
        return out

    def open(self, home: str) -> str:
        """Start the Studio at `home` if it is not up, and say where it is."""
        row = next((r for r in setup.studios(self.registry) if Path(r["home"]) == Path(home)), None)
        if row is None:
            raise StudioError("that Studio is not in the list any more")
        Studio(row["home"])  # the folder must still be there
        port = int(row["port"])
        url = f"http://127.0.0.1:{port}/"
        with self.lock:
            if port in self.running:
                return url
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            try:
                httpd = Server(("127.0.0.1", port), make_handler(Path(row["home"]), allowed, quiet=True,
                                                                  hub=self.url, seen=self.touch))
            except OSError:
                state = _get(url + "api/state") or {}
                if state.get("home") and Path(state["home"]) == Path(row["home"]).resolve():
                    return url  # started some other way (studio.cmd): use it, and leave it running
                raise StudioError(f"port {port} is taken by something that is not this Studio") from None
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            self.running[port] = httpd
            sync.start(row["home"])  # when its studio.local.toml asks to be kept in step with another copy
        return url

    def close(self) -> None:
        for httpd in [self.httpd, *self.running.values()]:
            httpd.shutdown()
            httpd.server_close()
        self.running.clear()

    def _handler(self):
        hub = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "StudioApp/0.1"
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                pass

            def send(self, body: bytes, ctype: str, status: int = 200):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def send_json(self, data, status: int = 200):
                self.send(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

            def guard(self) -> bool:
                """Refuse anything that is not this machine talking to itself."""
                hub.touch()
                ours = {f"127.0.0.1:{hub.port}", f"localhost:{hub.port}"}
                origin = self.headers.get("Origin")
                if (self.headers.get("Host") or "").lower() not in ours or (
                        self.command == "POST" and (origin and urlsplit(origin).netloc.lower() not in ours
                                                    or "application/json" not in (self.headers.get("Content-Type") or ""))):
                    self.send_json({"error": "this server answers only on its own address"}, 403)
                    return False
                return True

            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                if not self.guard():
                    return
                parts = [unquote(p) for p in urlsplit(self.path).path.split("/") if p]
                if not parts:
                    return self.send((WEB / "hub.html").read_bytes(), TYPES[".html"])
                if parts == ["api", "hub"]:
                    return self.send_json({"studio_hub": True, "studios": hub.rows(), "ui": Studio.ui()})
                if parts[0] == "web" and len(parts) > 1:
                    path = (WEB / "/".join(parts[1:])).resolve()
                    if path.is_relative_to(WEB.resolve()) and path.is_file():
                        return self.send(path.read_bytes(), TYPES.get(path.suffix.lower(), "application/octet-stream"))
                return self.send_json({"error": "no such page"}, 404)

            def do_POST(self):
                if not self.guard():
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    if length > MAX_BODY:
                        raise StudioError("request too large")
                    data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                    if urlsplit(self.path).path != "/api/open" or not isinstance(data, dict):
                        return self.send_json({"error": "no such route"}, 404)
                    return self.send_json({"ok": True, "url": hub.open(str(data.get("home") or ""))})
                except (StudioError, ValueError) as err:
                    return self.send_json({"error": str(err)}, 400)

        return Handler


# ------------------------------------------------------------------------------ the window
def browser() -> str:
    """The program that draws the window: Edge, else Chrome. STUDIO_APP_BROWSER names another."""
    given = os.environ.get("STUDIO_APP_BROWSER")
    if given:
        return given
    roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
        for root in roots:
            if root and (Path(root) / rel).is_file():
                return str(Path(root) / rel)
    return shutil.which("msedge") or shutil.which("chrome") or ""


def window(url: str, quiet: bool = False) -> subprocess.Popen | None:
    """Open the app's window on `url`. With a profile of its own, the process lives as long as the window."""
    exe = browser()
    if not exe:
        return None
    info = None
    if quiet and hasattr(subprocess, "STARTUPINFO"):  # for a test: minimised, and it takes no focus
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 7
    old = DATA.with_name(OLD[0])
    if old.is_dir() and not DATA.exists():  # keep the window's place and size across the rename
        try:
            old.rename(DATA)
        except OSError:
            pass
    profile = DATA / "app-profile"
    profile.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
                             "--no-default-browser-check", "--disable-background-mode"], startupinfo=info)


def main(quiet: bool = False) -> int:
    if sys.stderr is None or sys.stdout is None:  # started with no console: keep what would be printed
        DATA.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(DATA / "app.log", "w", encoding="utf-8", buffering=1)
    try:
        hub = Hub()
    except OSError:
        other = f"http://127.0.0.1:{HUB_PORT}/"
        if (_get(other + "api/hub") or {}).get("studio_hub"):  # the app is open already: one more window on it
            window(other, quiet)
            return 0
        hub = Hub(port=0)  # something else holds the usual port
    print(f"{NAME} at {hub.url}")
    started = time.monotonic()
    proc = window(hub.url, quiet)
    if proc is None:
        import webbrowser
        webbrowser.open(hub.url)
    else:
        proc.wait()
    if proc is None or time.monotonic() - started < 8:
        # no window of its own to wait on (an everyday browser took the page): stop when the pages go quiet
        hub.touch()
        while time.monotonic() - hub.seen < IDLE_SECONDS:
            time.sleep(2)
    hub.close()
    print("closed")
    return 0


# ---------------------------------------------------------------------------- the shortcut
def install() -> Path:
    """Put NocStudio in the Start menu. It starts the app with no console window."""
    runner = shutil.which("pyw") or str(Path(sys.executable).with_name("pythonw.exe"))
    args = ("-3.11 " if Path(runner).stem.lower() == "pyw" else "") + f'"{WEB.parent / "studio_app.pyw"}"'
    start = Path(os.environ.get("APPDATA") or "") / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    if not start.is_dir():
        raise StudioError(f"{start}: no Start menu folder here")
    link = start / SHORTCUT
    (start / OLD[1]).unlink(missing_ok=True)  # the shortcut this one replaces
    quote = lambda s: "'" + str(s).replace("'", "''") + "'"  # noqa: E731
    script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({quote(link)}); "
              f"$s.TargetPath = {quote(runner)}; $s.Arguments = {quote(args)}; "
              f"$s.WorkingDirectory = {quote(WEB.parent)}; $s.IconLocation = {quote(WEB / 'studio.ico')}; "
              f"$s.Description = 'Every project''s Studio, one window'; $s.Save()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True,
                       capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as err:
        raise StudioError(f"the shortcut could not be made: {err}") from err
    return link
