---
name: studio-create
description: Set up a Studio for the current project - the local web page where the user sees where a project stands, what waits on them, every asset it holds or needs, and every ruling they have made, and where they judge what Claude Code produces. Use when the user says anything like "create a studio page for this", "set up a studio for this project", "move this project into its Studio", or runs /studio-create.
---

# Create a Studio for this project

NocStudio is a shared tool at `{{KIT}}` (Python 3.11, no packages). Each
project gets its own home folder, its own port and its own copy of the
`studio` skill. "Set up" does not mean an empty page: it means the project
moved in.

The user gives the goal; you make the design calls. Ask what only they can
answer, once, up front; then build.

## 1. Make the home

```
py -3.11 "{{KIT}}\tool\studio.py" create "<this project's repo>" [--project "<name as the page shows it>"]
```

It makes `<repo>-studio` beside the repo (its own git repo), picks a free
port, writes `studio.cmd` there, puts `.claude/skills/studio/SKILL.md` in the
project's repo, and prints `S`, the command for everything after. It refuses
if the project already has a Studio; `studio.py studios` lists them all.
If the tool is missing or `py -3.11 tool\selftest.py` fails there, stop and
say so; do not rebuild the tool.

## 2. Teach the project's sessions

- Merge `<home>\CLAUDE-section.md` into the repo's `CLAUDE.md` near the top
  (create the file if there is none). Keep it short, and respect any length
  rule the file states for itself.
- Replace standing instructions that send the user to folders, chat picks or
  another review tool with the Studio. Leave history as written.
- Commit only those documents and the skill, with explicit paths. If another
  session may be working in the repo, re-read each file right before editing.

## 3. Ask, once

Read the project first (README, CLAUDE.md, TODO or plan, specs, the asset
folders) so you ask only what the files cannot answer. Typically:

- What are the milestones to "done", if no document lists them?
- Is there anything waiting on the user right now that is not written down?
- Are there rated or approved assets from before, and where is that record?

## 4. Move the project in

Use the `studio` skill now in the repo for the commands. Do all of it; an
empty Studio is not a finished setup.

- **The road:** `S milestone set` for each milestone, in order, with the goal
  and the question the user's verdict answers. Statuses are your reading of
  the documents; say so in the report.
- **The build in hand:** `S now` with the headline, what is built, what is
  next, what is known and left, and the lines that start it.
- **What only the user can do:** `S hand set` for each, `open` if it can be
  done now, `later` if nothing waits on it yet.
- **The asset list:** one `S slot set` per thing the project holds or needs,
  as the user would name it, with `--game-path` (a file, folder or glob) so
  they can open or hear it in the Library. `in_game` only where the documents
  show the user accepted it; otherwise `placeholder`; `needed` only for what a
  named milestone calls for. Previously approved masters come in with
  `S adopt`, with the user's exact words where a record has them.
- **Rulings:** `S decide` for each standing decision the documents record.
  `--words` only where the user is quoted exactly; otherwise the ruling says
  it is a session's record. Never invent or paraphrase into `--words`.
- **Loose candidates** the user has not judged yet become batches (`S new`,
  `add`, `file`), one decision each.
- **Playtests:** only if the project writes session folders of notes; set
  `[playtests] dirs` in `<home>\studio.toml`.
- **Checks:** set `[checks.*]` in `studio.toml` to the project's own limits
  (they start loose).

For a large project, hand the asset list and the rulings to subagents with a
brief that names the home, the repo, the status rules above, and that they
must not commit or edit the project.

## 5. Prove it and report

- `py -3.11 "{{KIT}}\tool\selftest.py"` must end "All good."
- Start the page without opening a browser (`S serve`, in the background),
  check `/api/state` answers, and look at the Overview in a headless browser
  if one is at hand. Stop the server afterwards.
- `S save` commits the studio home (and pushes, if it has a remote).
- Tell the user, in a few lines: that the project is now in NocStudio's menu
  (Start menu: NocStudio; `studio.cmd` in the home also opens it), what is in
  the Inbox, how many assets and rulings moved in, and every judgment call
  they should correct (milestone statuses, asset statuses, anything read from
  a record).

## Rules that carry over

- Change no product code while setting up: documents and the skill only.
- Nothing acts on a verdict until the user says "process my studio verdicts".
