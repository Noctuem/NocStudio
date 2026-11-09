# Plan: starting phone work from the web copy

On the phone, the user looks at the project in the Studio and talks to Claude in the Claude app. The web copy
(`serve-all` on the server) does not need its own Talk page. It needs one thing: a button that starts a
remote-controlled Claude session on the desktop, in that Studio's project, so the Claude app can pick it up.

The ruling (2026-11-09, D-0006): "For mobile work, which is what that wake button would be used for, I want
to see things in studio and talk to you through the claude app on my phone.  So the only thing I need in
studio is a button to start a remote controlled claude session on the desktop so I can start dev over the
phone with both studio and the claude app."

This replaces the 2026-11-05 plan (a bridge from the server to the PC app, the PC app running at login, and
Talk, Usage and Start from an idea on the web copy). None of that is built.

## How

Ignition already does the hard part: it wakes the desktop, starts `claude remote-control` in a project folder,
carries on that folder's last conversation, and reports how it went. The web copy and Ignition sit on the
same address behind the same sign-in, so the button is page code only:

1. `POST <site>/ignition/launch` with `{"tool": "claude", "repo": "p:<the project's folder name>"}`.
   Add `"fresh": true` for a new conversation instead of the last one.
2. Poll `GET <site>/ignition/launch/<id>` every 2 s while `status` is `running`, showing the last line of
   `log` (waking, starting).
3. `launched` or `already-running`: say "Open the Claude app, Code tab". `failed`: show `result`.

No new key, no new container, nothing new on the server or the desktop. The button shows only on the web copy
(`site` set in `studio.local.toml`), never on the PC app, and only when the Studio names its project folder.

## Steps (milestone `phone`)

1. `start`: a Start Claude button on the web Studio, with "new conversation" as an option
2. `names`: projects whose folder name has a space (`Jev and Drones`, `Factory V`) can be started.
   Ignition's `p:<name>` takes only letters, digits, `.`, `_` and `-`, so this is a change in Ignition.

## Traps already known

- The page must work out the folder name from the Studio's project folder (`game_repo` in `studio.toml`, the
  PC's path), since the server copy's own `game_repo` is empty.
- Ignition allows one launch in flight at a time; a 202 means a launch is already running, so poll that id.
- Ignition's API answers only behind the sign-in (`Remote-User`); a page opened another way gets 401.

## Set aside

- Notes on the web menu from Nextcloud (decided 2026-11-05) is outside the ruling. Parked, not dropped.
