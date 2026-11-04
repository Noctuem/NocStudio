"""Talking to the project's Claude Code sessions from the page: start one, or carry on with one, and talk to it.

Each conversation on the page is one `claude -p` process in the project's repo, kept running between turns and
spoken to through stream-json on its stdin and stdout:

    claude -p --input-format stream-json --output-format stream-json --verbose
           --permission-mode auto --permission-prompt-tool stdio [--resume <id> | --continue]

Auto mode decides what the session may do. Anything it would ask about comes here as a `can_use_tool` request,
and the page shows it with Allow and Deny. What the session says is kept in live/talk/<session>.jsonl (not
history: the session's own transcript under ~/.claude/projects is the record). A conversation nobody has
spoken to for IDLE seconds is stopped; it can be carried on later, from where it stopped.

The earlier part of a session the page did not start is read from its transcript, so carrying on with
yesterday's session shows what was said. Claude Code's hooks see these sessions like any other, so the
Overview shows them and they are handed the user's notes.

A message sent while a session works reaches it at its next step, as one typed in the terminal does; Stop
interrupts the turn (the session stays), and Stop and send interrupts it and then says the message.
`usage()` runs Claude Code's own /usage, which spends nothing, for the page to show.
"""
from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

IDLE = 30 * 60
KEEP = 400            # events kept in memory per conversation; the page asks for what is after the last it saw
HISTORY = 40          # messages read back from a transcript when the page opens an older session
TAIL = 3 * 1024 * 1024
TALKS: dict[str, "Talk"] = {}
LOCK = threading.Lock()


class TalkError(Exception):
    pass


def claude_exe() -> list[str]:
    """How to start Claude Code: STUDIO_CLAUDE (a path, or a JSON list for a command with arguments), else PATH."""
    given = os.environ.get("STUDIO_CLAUDE", "")
    if given.startswith("["):
        return [str(x) for x in json.loads(given)]
    exe = given or shutil.which("claude")
    if not exe:
        raise TalkError("Claude Code is not on this machine's PATH (set STUDIO_CLAUDE to its full path)")
    return [exe]


def projects_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"


def slug(path: Path) -> str:
    """The folder name Claude Code keeps a directory's transcripts under."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------------- the sessions a repo has had
_SEEN: dict[str, tuple] = {}


def _tail_records(path: Path, size: int = TAIL) -> list[dict]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            end = fh.tell()
            fh.seek(max(0, end - size))
            raw = fh.read()
    except OSError:
        return []
    lines = raw.split(b"\n")
    if end > size:
        lines = lines[1:]  # the first is cut
    out = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
    return "\n".join(p for p in parts if p)


def _said_by_user(rec: dict) -> str:
    """What the user typed, or "" for tool results, hook output and the CLI's own messages."""
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isSidechain"):
        return ""
    text = _text_of((rec.get("message") or {}).get("content"))
    if not text or text.startswith(("<command-", "<local-command", "<system-reminder", "Caveat:")):
        return ""
    return text


def past(repo: Path, limit: int = 20) -> list[dict]:
    """The repo's sessions, newest first: id, title, last prompt, when."""
    folder = projects_dir() / slug(repo)
    rows = []
    for path in sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit * 2]:
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_size == 0:
            continue
        key = (st.st_mtime_ns, st.st_size)
        hit = _SEEN.get(str(path))
        if hit and hit[0] == key:
            rows.append(hit[1])
            continue
        title = prompt = ""
        for rec in _tail_records(path, 512 * 1024):
            if rec.get("type") == "ai-title":
                title = rec.get("aiTitle") or title
            elif rec.get("type") == "custom-title":
                title = rec.get("customTitle") or title
            elif rec.get("type") == "last-prompt":
                prompt = rec.get("lastPrompt") or prompt
            elif not prompt and _said_by_user(rec):
                prompt = _said_by_user(rec)
        row = {"id": path.stem, "title": title, "prompt": prompt[:300],
               "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))}
        _SEEN[str(path)] = (key, row)
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def history(repo: Path, sid: str) -> list[dict]:
    """The last things said in a session, from its transcript, as page events."""
    path = projects_dir() / slug(repo) / f"{sid}.jsonl"
    out = []
    for rec in _tail_records(path):
        if rec.get("isSidechain"):
            continue
        said = _said_by_user(rec)
        if said:
            out.append({"kind": "you", "text": said, "at": rec.get("timestamp") or ""})
        elif rec.get("type") == "assistant":
            for block in (rec.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text"):
                    out.append({"kind": "claude", "text": block["text"], "at": rec.get("timestamp") or ""})
                elif block.get("type") == "tool_use":
                    out.append({"kind": "tool", "text": tool_line(block.get("name"), block.get("input")), "at": rec.get("timestamp") or ""})
    return [dict(e, old=True) for e in out[-HISTORY:]]


def tool_line(name, data) -> str:
    data = data if isinstance(data, dict) else {}
    for key in ("command", "file_path", "pattern", "url", "query", "description", "prompt", "skill"):
        if data.get(key):
            return f"{name}: {str(data[key]).splitlines()[0][:200]}"
    return str(name or "a tool")


# ------------------------------------------------------------------------- one live conversation
class Talk:
    def __init__(self, home: Path, repo: Path, resume: str = "", fork: bool = False, system: str = ""):
        self.home, self.repo = Path(home), Path(repo)
        self.key = resume if resume and not fork else f"new-{uuid.uuid4().hex[:8]}"
        self.sid = resume if resume and not fork else ""
        self.events: list[dict] = []
        self.seq = 0
        self.asks: dict[str, dict] = {}   # request id -> what the session asks to do
        self.state = "starting"
        self.error = ""
        self.touched = time.time()
        self.stopping = False  # an interrupt was sent: the turn it ends is "stopped", not an error
        self.replied = 0   # the seq of the last finished turn
        self.seen = 0      # the seq the page last showed while it was in front of the user
        self.lock = threading.Lock()
        if resume:
            for e in history(self.repo, resume):
                self._add(e)
        cmd = [*claude_exe(), "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--permission-mode", os.environ.get("STUDIO_TALK_MODE") or "auto", "--permission-prompts", "host", "--permission-prompt-tool", "stdio"]
        if resume == "last":
            cmd.append("--continue")
        elif resume:
            cmd += ["--resume", resume]
        if resume and fork:
            cmd.append("--fork-session")
        if system:  # kept in the session's record, so it holds when the session is carried on later
            cmd += ["--append-system-prompt", system]
        self.loop = bool(system)
        env = dict(os.environ, STUDIO_TALK="1")
        try:
            self.proc = subprocess.Popen(cmd, cwd=self.repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=env,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as err:
            raise TalkError(f"Claude Code did not start: {err}") from err
        self.log = self.home / "live" / "talk"
        self.log.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._read, daemon=True, name="studio-talk").start()
        threading.Thread(target=self._errors, daemon=True, name="studio-talk-err").start()

    # what the page sees
    def _add(self, event: dict) -> None:
        with self.lock:
            self.seq += 1
            event = dict(event, seq=self.seq, at=event.get("at") or _now())
            self.events.append(event)
            del self.events[:-KEEP]
        if self.sid and not event.get("old"):
            try:
                with open(self.log / f"{self.sid}.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            except OSError:
                pass

    def view(self, after: int = 0) -> dict:
        with self.lock:
            events = [e for e in self.events if e["seq"] > after]
        return {"key": self.key, "id": self.sid, "state": self.state, "error": self.error, "repo": str(self.repo),
                "asks": list(self.asks.values()), "events": events, "seq": self.seq}

    # what the session says
    def _read(self) -> None:
        for raw in self.proc.stdout:
            try:
                msg = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            try:
                self._take(msg)
            except Exception as err:  # noqa: BLE001 - one odd line must not end the conversation
                self._add({"kind": "note", "text": f"(could not read a message from the session: {err})"})
        code = self.proc.wait()
        self.asks.clear()
        self.state = "ended"
        if code and not self.error:
            self.error = f"the session stopped (exit {code})"
        self._add({"kind": "ended", "text": self.error or "The session stopped. Carry on to start it again."})

    def _errors(self) -> None:
        tail = []
        for raw in self.proc.stderr:
            tail = (tail + [raw.decode("utf-8", "replace").rstrip()])[-5:]
        if tail and self.proc.poll():
            self.error = " ".join(t for t in tail if t)[-400:]

    def _take(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "system" and msg.get("subtype") == "init":
            sid = msg.get("session_id") or ""
            if sid and sid != self.sid:
                self.sid = sid
                with LOCK:  # the page may still ask by the first key: both lead here
                    self.key = sid
                    TALKS[sid] = self
            self.state = "working"
        elif kind == "system" and msg.get("subtype") == "permission_denied":
            self._add({"kind": "blocked", "text": msg.get("message") or "", "tool": msg.get("tool_name") or ""})
        elif kind == "assistant":
            self.state = "working"
            for block in (msg.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text"):
                    self._add({"kind": "claude", "text": block["text"]})
                elif block.get("type") == "tool_use":
                    self._add({"kind": "tool", "text": tool_line(block.get("name"), block.get("input"))})
        elif kind == "user":
            for block in (msg.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                    self._add({"kind": "tool-error", "text": _text_of(block.get("content"))[:600] if not isinstance(block.get("content"), str) else block["content"][:600]})
        elif kind == "control_request":
            req = msg.get("request") or {}
            if req.get("subtype") == "can_use_tool":
                ask = {"id": msg.get("request_id"), "tool": req.get("display_name") or req.get("tool_name") or "a tool",
                       "line": tool_line(req.get("tool_name"), req.get("input")), "why": req.get("description") or "",
                       "input": req.get("input") or {}, "at": _now()}
                self.asks[ask["id"]] = ask
                self.state = "asking"
                self._add({"kind": "ask", "text": ask["line"], "ask": ask["id"]})
            else:  # nothing else is answered by this page: say no, so the session never hangs on it
                self._send({"type": "control_response", "response": {"subtype": "error", "request_id": msg.get("request_id"),
                                                                     "error": "not handled by the Studio page"}})
        elif kind == "result":
            self.state = "idle"
            self.asks.clear()  # a question the turn left open is moot once it ends
            if self.stopping:
                self.stopping = False
                self._add({"kind": "note", "text": "Stopped."})
            elif msg.get("is_error") or msg.get("subtype") not in (None, "success"):
                self._add({"kind": "note", "text": "The turn ended with an error: " + str(msg.get("result") or msg.get("subtype"))[:400]})
            self._add({"kind": "turn", "text": "", "cost": msg.get("total_cost_usd")})
            self.replied = self.seq

    def mark_seen(self) -> None:
        self.seen = self.seq

    def waits(self) -> str:
        """What this conversation waits on the user for: "ask" (a question to answer), "reply" (a turn they
        have not read yet) or ""."""
        if self.asks:
            return "ask"
        return "reply" if self.replied > self.seen else ""

    # what the user says
    def _send(self, obj: dict) -> None:
        if self.proc.poll() is not None:
            raise TalkError("the session has stopped; carry on with it to start it again")
        try:
            self.proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError as err:
            raise TalkError(f"could not reach the session: {err}") from err

    def busy(self) -> bool:
        """In the middle of a turn: working, or waiting on an answer from the page."""
        return self.proc.poll() is None and self.state in ("starting", "working", "asking")

    def say(self, text: str, stop: bool = False) -> None:
        """Say something. While it works, the session reads it at its next step; with stop, the turn is
        stopped first and the message starts the next one."""
        text = str(text or "").strip()
        if not text:
            raise TalkError("write something first")
        if stop and self.state in ("working", "asking"):
            self.interrupt()
        self.touched = time.time()
        self._send({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}})
        self.state = "working"
        self._add({"kind": "you", "text": text})

    def answer(self, request_id: str, allow: bool, why: str = "") -> None:
        ask = self.asks.pop(request_id, None)
        if ask is None:
            raise TalkError("that question is no longer open")
        self.touched = time.time()
        if allow:
            reply = {"behavior": "allow", "updatedInput": ask["input"]}
        else:
            reply = {"behavior": "deny", "message": "The user said no on the Studio page" + (f": {why.strip()}" if why.strip() else ".")}
        self._send({"type": "control_response", "response": {"subtype": "success", "request_id": request_id, "response": reply}})
        self.state = "asking" if self.asks else "working"
        self._add({"kind": "answer", "text": ("Allowed: " if allow else "Denied: ") + ask["line"] + (f" ({why.strip()})" if why.strip() and not allow else "")})

    def interrupt(self) -> None:
        if self.state not in ("working", "asking"):
            raise TalkError("it is not doing anything to stop")
        self.stopping = True
        self._send({"type": "control_request", "request_id": f"stop-{uuid.uuid4().hex[:8]}", "request": {"subtype": "interrupt"}})
        self._add({"kind": "note", "text": "Stopping what it is doing…"})

    def stop(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=10)
            except (OSError, subprocess.SubprocessError):
                self.proc.kill()


# ------------------------------------------------------------------------- the conversations of this process
def start(home, repo, text: str = "", resume: str = "", fork: bool = False, system: str = "") -> Talk:
    repo = Path(repo)
    if not repo.is_dir():
        raise TalkError(f"the project's folder {repo} is not there")
    with LOCK:
        if resume and not fork and resume in TALKS and TALKS[resume].proc.poll() is None:
            talk = TALKS[resume]
        else:
            talk = Talk(home, repo, resume=resume, fork=fork, system=system)
            TALKS[talk.key] = talk
    if text.strip():
        talk.say(text)
    _sweeper()
    return talk


def get(key: str) -> Talk:
    talk = TALKS.get(key)
    if talk is None:
        raise TalkError("no such conversation on this page; carry on with the session to open it again")
    return talk


def listing(home) -> list[dict]:
    rows, seen = [], set()
    for talk in list(TALKS.values()):
        if id(talk) in seen or Path(talk.home) != Path(home):
            continue
        seen.add(id(talk))
        if talk.state == "ended" and not talk.waits():
            continue  # stopped: it is among the earlier sessions, to carry on with
        last = next((e for e in reversed(talk.events) if e["kind"] in ("you", "claude")), None)
        rows.append({"key": talk.key, "id": talk.sid, "state": talk.state, "asks": len(talk.asks), "waits": talk.waits(),
                     "last": (last or {}).get("text", "")[:200], "touched": talk.touched})
    return sorted(rows, key=lambda r: -r["touched"])


def waiting(home) -> dict:
    """For the menu: how many of a Studio's conversations ask something, and how many replied unread.
    A reply stays unread after the session is stopped for being idle: it still waits on the user."""
    out, seen = {"asks": 0, "replies": 0}, set()
    for talk in list(TALKS.values()):
        if id(talk) in seen or Path(talk.home) != Path(home):
            continue
        seen.add(id(talk))
        w = talk.waits()
        if w == "ask":
            out["asks"] += 1
        elif w == "reply":
            out["replies"] += 1
    return out


def to_desktop(repo, sid: str) -> None:
    """Carry a session on in the Claude desktop app: `claude --desktop --resume <id>`, which saves it, opens it
    there (the same session, not a copy) and exits. It needs a console of its own: with its output redirected
    it refuses to run, so on Windows it gets one, minimized."""
    repo = Path(repo)
    if not re.fullmatch(r"[0-9a-f-]{8,}", sid or ""):
        raise TalkError("that is not a session id")
    with LOCK:
        running = [t for t in TALKS.values() if t.sid == sid and t.proc.poll() is None]
    for t in running:
        if t.busy():
            raise TalkError("it is in the middle of a turn here: stop it or let it finish, then move it")
        t.stop()
    cmd = [*claude_exe(), "--desktop", "--resume", sid]
    try:
        if os.name == "nt":
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            info.wShowWindow = 7  # minimized, and it does not take the focus
            proc = subprocess.Popen(cmd, cwd=repo, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=info)
        else:
            proc = subprocess.Popen(cmd, cwd=repo, start_new_session=True)
        code = proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        return  # still opening: the app has it
    except OSError as err:
        raise TalkError(f"Claude Code did not start: {err}") from err
    if code:
        raise TalkError(f"Claude Code could not open it in the app (exit {code}). The app needs a Claude "
                        "subscription sign-in, and the session must not be open in a terminal.")


def busy() -> list["Talk"]:
    """The conversations of this process in the middle of a turn: closing the app would cut them off."""
    out, seen = [], set()
    for talk in list(TALKS.values()):
        if id(talk) not in seen and talk.busy():
            seen.add(id(talk))
            out.append(talk)
    return out


# ------------------------------------------------------------------------- the plan's usage
_USAGE: dict = {}
_USAGE_LOCK = threading.Lock()
USAGE_FRESH = 60  # seconds a reading is reused for


def usage(fresh: bool = False) -> dict:
    """Claude Code's /usage, run on its own: no model is called, nothing is spent, no session is kept and no
    hook runs. Returns its text and each limit it names, e.g. {"name": "Current week (all models)",
    "pct": 40, "resets": "Nov 6, 8am (America/Chicago)"}."""
    with _USAGE_LOCK:
        if _USAGE and not fresh and time.time() - _USAGE["t"] < USAGE_FRESH:
            return _USAGE["data"]
        where = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "NocStudio"
        where.mkdir(parents=True, exist_ok=True)
        cmd = [*claude_exe(), "-p", "/usage", "--output-format", "json", "--no-session-persistence",
               "--settings", json.dumps({"disableAllHooks": True})]
        try:
            run = subprocess.run(cmd, cwd=where, capture_output=True, timeout=60, env=dict(os.environ, STUDIO_TALK="1"),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            text = str(json.loads(run.stdout.decode("utf-8", "replace")).get("result") or "")
        except (OSError, subprocess.SubprocessError, ValueError) as err:
            raise TalkError(f"/usage did not answer: {err}") from err
        limits = []
        for line in text.splitlines():
            m = re.match(r"\s*(.+?):\s*(\d+(?:\.\d+)?)% used(?:\s*\W\s*resets\s+(.+))?\s*$", line)
            if m:
                limits.append({"name": m.group(1), "pct": float(m.group(2)), "resets": (m.group(3) or "").strip()})
        data = {"text": text.strip(), "limits": limits, "at": _now()}
        _USAGE.update(t=time.time(), data=data)
        return data


_SWEEPING = False


def _sweeper() -> None:
    """Stop conversations nobody has spoken to in a while; they can be carried on later."""
    global _SWEEPING
    if _SWEEPING:
        return
    _SWEEPING = True

    def run():
        while True:
            time.sleep(60)
            for talk in list(TALKS.values()):
                if talk.state == "idle" and time.time() - talk.touched > IDLE:
                    talk.stop()
    threading.Thread(target=run, daemon=True, name="studio-talk-sweep").start()


@atexit.register
def _stop_all() -> None:
    for talk in list(TALKS.values()):
        if talk.proc.poll() is None:
            try:
                talk.proc.kill()
            except OSError:
                pass
