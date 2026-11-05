# Plan: the web copy does what the PC does

The web copy (`serve-all` on the server, for the phone) shows every Studio and keeps it in step with the PC.
Five things still exist only in the PC app:

| On the PC | Why the web copy lacks it |
|---|---|
| Talk: sessions, carry on, send, stop, allow and deny | sessions run on the PC; the server copy refuses (`talk_repo`: "comes later") |
| Usage at the top of every page | `claude -p /usage` runs on the PC (`app.py`, `/api/usage`) |
| Now, Ideas and the Dump box on the menu | `vault.py` reads the notes folder on the PC; `serve-all`'s menu has no `/api/vault` |
| Start from an idea | `idea.new` makes a project folder on the PC (`app.py`, `/api/idea`) |
| Waking the PC, launching a session | done by Ignition's page, not NocStudio |

The ruling this follows: "Ignition folds in ... PC first, phone next."

## How

**One bridge, server to PC.** Talk, Usage and Start from an idea need the PC, so they all go through one path:
the web copy passes those calls on to the PC app and shows what comes back. The path copies Ignition's shape,
which has run since 2026-09:

- The container holds no key to the PC. It asks a forced command on the server host, which accepts a short
  fixed list of requests (open the tunnel, wake, status) and nothing else.
- The host opens an ssh tunnel to the PC's NocStudio port on `127.0.0.1`. The PC listens on no new address.
- The PC app answers only its own address (`guard`), so the bridge sends the PC's own `Host`. Every call
  still passes the PC's guard, and auto mode on the PC still decides what a session may do.

**The PC app runs with its window closed.** The bridge needs something to talk to. The app starts at login
with no window and stays up; opening NocStudio opens a window on it (it does that already when it runs).
`linger` and the idle stop apply only to a window someone opened.

**A sleeping PC says so.** When the bridge gets no answer, the page shows "The PC is asleep" with **Wake**,
which sends Ignition's wake (`ignite wake`) and waits for the app. Pages that need nothing from the PC
(the Studio itself, verdicts, notes) work as now.

**Notes on the menu come from Nextcloud, not the PC** (decided). The vault is a
Nextcloud folder, so the server can read Now and Ideas and add to Dump over WebDAV with the PC off. Writing
through WebDAV, not the data folder on disk, keeps Nextcloud's index right.

## Steps (milestone `phone`)

1. `bridge`: the server reaches the PC app through a forced command and an ssh tunnel
2. `headless`: NocStudio keeps running on the PC with the window closed, and starts at login
3. `wake`: a sleeping PC shows as asleep on the web pages, with Wake
4. `relay`: the web Talk page drives PC sessions through the bridge: list, carry on, send, stop, allow, deny, files
5. `usage`: Usage on the web pages, through the bridge
6. `notes`: Now, Ideas and the Dump box on the web menu, from Nextcloud
7. `ideas`: Start from an idea on the web menu, through the bridge
8. `ignition`: waking and launching move from Ignition's page into NocStudio

Steps 1 to 3 come first; the rest each need only those. Step 6 needs none of them.

## Traps already known

- `serve-all` serves every Studio under one address, so a bridged call must name its Studio, and the PC's
  port for it comes from the PC's `studios.json`, not the server's.
- A call that starts a session must not run twice if the phone retries. Send a request id and drop a repeat.
- The tunnel carries what a session prints, the user's files included. It stays inside ssh and the server's
  sign-in; nothing is opened to the internet.
- Talk's stream on the PC is long-polled by the page. Keep it long-polled through the bridge, not buffered.

## Decided (2026-11-05)

- Notes on the menu come from Nextcloud on the server. The user gives the Nextcloud app password when that
  step is reached; ask for it then.
- The PC app starts at login with no window.

## Not decided yet (in the Studio, with defaults)

- Tapping Send when the PC is asleep: wake it and send (default), or ask first.
