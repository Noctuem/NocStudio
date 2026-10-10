---
name: studio-create
description: Set up or plan a project in NocStudio - the local page where the user sees how far along a project is, what is running now, what waits on them, every asset it holds or needs and every ruling they have made, and where they judge what Claude Code produces. Use when the user says anything like "start a new project", "set up a studio for this project", "create a studio page for this", "move this project into its Studio", "plan this project in its Studio", "turn on the Studio's live reporting", or runs /studio-create.
---

# A project in NocStudio, organised from the start

NocStudio is a shared tool at `{{KIT}}` (Python 3.11, no packages). Each
project gets its own home folder, its own port and its own copy of the
`studio` skill. "Set up" does not mean an empty page: it means the project
has a goal, a road of milestones, steps for the one in hand, and everything
that waits on the user written down, so the Overview is true from day one.

The user gives the goal; you make the design calls. Read first, propose a
plan, and ask only what they alone can answer, once, up front. Then build.

Which of these you do depends on where the project is:

- **A new idea, no folder yet:** all six parts, starting with the folder.
- **A project that exists but has no Studio:** all six parts.
- **A project whose Studio says "Getting organised"** (they said "plan this
  project in its Studio"): parts 3 to 6. `S status` shows what is missing.
- **"Turn on the Studio's live reporting":** part 5 alone.

## 1. Make the home

A new idea first needs a place: make the project's folder where the user
keeps their projects, `git init` it, and write a README that says in their
words what it is. Then:

```
py -3.11 "{{KIT}}\tool\studio.py" create "<the project's repo>" [--project "<name as the page shows it>"]
```

It makes `<repo>-studio` beside the repo (its own git repo), picks a free
port, puts `.claude/skills/studio/SKILL.md` in the project's repo, and prints
`S`, the command for everything after. It refuses if the project already has
a Studio; `studio.py studios` lists them all. If the tool is missing or
`py -3.11 tool\selftest.py` fails there, stop and say so; do not rebuild the
tool.

## 2. Teach the project's sessions

- Merge `<home>\CLAUDE-section.md` into the repo's `CLAUDE.md` near the top
  (create the file if there is none). Keep it short, and respect any length
  rule the file states for itself.
- Replace standing instructions that send the user to folders, chat picks or
  another review tool with the Studio. Leave history as written.
- Commit only those documents and the skill, with explicit paths. If another
  session may be working in the repo, re-read each file right before editing.

## 3. Read, propose, ask once

Read what the project already has (README, CLAUDE.md, a plan or TODO, specs,
the code's shape, the asset folders, the git log) so you ask only what the
files cannot answer. Then draft the whole plan yourself and show it to the
user in chat as a short outline to correct, not a form to fill in. Ask the
open points in one round; use options where there are real options. What a
plan needs:

- **The goal.** What the project is, who it is for, and what "done" looks
  like, in a sentence or two. Theirs to say; quote it.
- **The road.** Three to seven milestones from here to done. Each ends in
  something they can see or try, and names the question their verdict will
  answer ("Is one level fun on its own?").
- **The milestone in hand.** Five to twelve steps, each either done or not
  and small enough to land in a day or two. Later milestones get a few coarse
  steps; they are broken down when they are near.
- **What they count the project by**, if anything: levels, pages, endpoints,
  songs. These become counters on the Overview.
- **What the project holds or needs that is not code**: art, sound, models,
  writing. Skip this for a project that has none.
- **House rules.** Standing decisions that every session must follow: the
  look, hard limits, what never to do. In their words.
- **What only they can do**, known today: an account to open, a machine to
  test on, a purchase.
- **How they want to be asked.** What may go ahead on your default, and what
  must wait for them.

For a project with history, statuses and dates are your reading of the
documents and the git log; say so in the report, and never invent a step or
a date.

## 4. Write the plan in

Use the `studio` skill now in the repo for the commands. Do all of it; a
Studio with holes in it is not a finished setup.

- **The road and its steps** in one go: write the plan as JSON and load it.
  `S plan` prints the shape.
  ```
  S plan <file.json>
  ```
  ```
  {"goal": "<their words>", "headline": "<where the project stands today>",
   "counters": ["Levels=0/9"], "next": ["<what comes next> :: <when>"],
   "milestones": [{"id": "M1", "name": "<name>", "status": "current", "eta": "<a date>",
                   "goal": "<what it is>", "question": "<what their verdict answers>",
                   "steps": [{"id": "<short-id>", "name": "<the step, as they would say it>", "status": "planned"}]}]}
  ```
  Step statuses: `planned`, `building`, `built`, `tested`, `done`, `parked`,
  `dropped`; a step that landed on an earlier day takes `"date": "YYYY-MM-DD"`
  so the chart starts with the project's real history.
- **The build in hand**, if there is one: `S now --build ... --built ...
  --start ...`.
- **Needs you:** `S ask set` for each thing only they can do and each open
  question, every decision with the `--default` you will use.
- **The asset list:** one `S slot set` per thing the project holds or needs,
  as the user would name it, with `--game-path` (a file, folder or glob) so
  they can open or hear it in the Library. `in_game` only where the documents
  show they accepted it; otherwise `placeholder`; `needed` only for what a
  named milestone calls for. Previously approved masters come in with
  `S adopt`, with their exact words where a record has them.
- **Rulings:** `S decide` for the goal, each house rule and each standing
  decision the documents record. `--words` only where the user is quoted
  exactly; otherwise the ruling says it is a session's record. Never invent
  or paraphrase into `--words`.
- **Loose candidates** they have not judged yet become batches (`S new`,
  `add`, `file`), one decision each.
- **Playtests:** only if the project writes session folders of notes; set
  `[playtests] dirs` in `<home>\studio.toml`.
- **Checks:** set `[checks.*]` in `studio.toml` to the project's own limits
  (they start loose).

For a large project, hand the asset list and the rulings to subagents with a
brief that names the home, the repo, the status rules above, and that they
must not commit or edit the project.

## 5. Live reporting

`S hooks status` says whether Claude Code already reports what each session
is doing to NocStudio. If not, tell the user in two lines what installing
does (it adds one entry per event to their own Claude Code settings,
`~/.claude/settings.json`, keeps a copy of the file from before, and applies
to every project that has a Studio and to none that has not) and, when they
agree, run:

```
S hooks install
```

It is once per machine. `S hooks remove` takes it out again.

## 6. Prove it and report

- `py -3.11 "{{KIT}}\tool\selftest.py"` must end "All good."
- `S status` must print the percentage and no advice about the board.
- Start the page without opening a browser (`S serve`, in the background),
  check `/api/state` answers, and look at the Overview in a headless browser
  if one is at hand. Stop the server afterwards.
- `S save` commits the studio home (and pushes, if it has a remote).
- Tell the user, in a few lines: that the project is in NocStudio's menu
  (Start menu: NocStudio; `studio.cmd` in the home also opens it), the road
  you wrote and how far along the project is, what is in Needs you and the
  Inbox, and every judgment call they should correct (milestone and step
  statuses, dates read from history, asset statuses).

## Rules that carry over

- Change no product code while setting up: documents and the skill only.
- Nothing acts on a verdict until the user says "process my studio verdicts".
- From here on the project's sessions keep the Overview true as they work:
  the `studio` skill's standing rules say how.
