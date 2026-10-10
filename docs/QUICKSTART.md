# Quick start

Ten minutes from a clone to judging your first batch.

## What you need

- Windows 10 or 11
- [Python 3.11 or newer](https://www.python.org/downloads/), installed with the `py` launcher
  (the default installer includes it). Check with `py -3.11 --version`.
- git
- Edge or Chrome, for the app window
- A project in a folder of its own. It does not have to be a git repository, and it does not
  have to be a game.

Nothing else is installed, and nothing is downloaded when it runs.

## 1. Get it and prove it works

```
git clone https://github.com/Noctuem/NocStudio.git
cd NocStudio
py -3.11 tool\selftest.py
```

The self-test builds a throwaway Studio in a temp folder, runs every feature against it and
prints one line per step. It must end with `All good.`

Keep this folder where it is: every Studio you make runs from it, so a `git pull` here updates
them all.

## 2. Make a Studio for your project

```
py -3.11 tool\studio.py create C:\path\to\your\project
```

This makes four things:

| What | Where | What it is |
|---|---|---|
| The Studio's home | `C:\path\to\your\project-studio` | Folders of plain files: batches, the asset list, the decisions log, the overview. Its own git repository. |
| The skill | `your project\.claude\skills\studio\SKILL.md` | Teaches Claude Code the rules and the commands. |
| A section for CLAUDE.md | `project-studio\CLAUDE-section.md` | A short paragraph to paste into your project's `CLAUDE.md`, so every session knows the Studio exists. |
| Samples | `project-studio\samples` | Made-up batches to try the page on. |

It also prints `S`, the full command your agent uses for everything else.

## 3. Open it

```
py -3.11 tool\studio.py app --install
```

That puts **NocStudio** in the Start menu. Open it, pick your project, and the Studio starts and
opens in a window of its own. Closing the window stops it.

Two other ways to open one, if you prefer:

- Double-click `studio.cmd` in the Studio's home: the page opens in your browser, and closing
  the console window stops it.
- `py -3.11 tool\studio.py app` runs the app without installing the shortcut.

## 4. Try judging

Go to **Inbox**, then **Samples**. There is one made-up batch for each kind of work. Open
*Pictures* and try the whole flow:

1. Click a picture to see it large. Scroll to zoom, drag to pan, arrow keys to step.
2. Tick two and press **Compare**: they zoom and pan together.
3. Mark one **Winner** (`W`), one **Keep** (`K`), one **Redo** (`R`) with a note, one **Reject** (`X`).
   Number keys give a score.
4. At the bottom, choose what happens next and press **Submit verdict**.

Nothing in a sample is counted, recorded or acted on, and **Start over** clears your marks.
*Motions* and *Models* show the 3D viewer; *Sounds* shows the players; *A question with
options* shows how a design question arrives.

**Size** and **Light / Dark** are at the right of the top bar and are remembered.

## 5. Teach your agent

1. Paste the contents of `project-studio\CLAUDE-section.md` into your project's `CLAUDE.md`
   (create the file if there is none).
2. Start Claude Code in your project. The `studio` skill is already there.

From now on, when a session makes something you must judge, it files a batch and tells you in
one line: *"Pistol shots is in the Studio (4 to judge)."* You judge it in the page. Then you say:

> process my studio verdicts

and the session reads what you marked, ships the winner, starts another round from your notes,
or parks it, and records the decision.

### Let the agent move your project in

An empty Studio is not much use. If your project already has milestones, assets and decisions
written down, ask the agent to move them in. Install the setup skill once:

```
py -3.11 tool\studio.py install-skill
```

Then, in any project, say to Claude Code:

> create a studio page for this

It makes the Studio, reads your project, asks you what the files cannot answer, and fills in the
road of milestones, the build in hand, the asset list, your standing rulings and the things only
you can do.

## The daily loop

| You | Your agent |
|---|---|
| Open NocStudio, read the Overview | Keeps the Overview true when a build is delivered or the plan changes |
| Judge what is in the Inbox | Files batches; the checks hold back what breaks a rule |
| Say "process my studio verdicts" | Runs `studio.py todo`, acts on each verdict, closes it with a decision |
| Mark chores Done or Not now | Reads your answers the next time it processes |
| | Ends its work with `studio.py save`, which commits the Studio's record (and pushes, if you gave the home a remote) |

## Commands your agent uses

You rarely type these yourself; the skill teaches them. `S` is
`py -3.11 <clone>\tool\studio.py --home <the Studio's home>`.

```
S new / add / context / file      make a batch, add candidates and references, run the checks and file it
S todo                            the verdicts you submitted, with the steps for each
S import / done                   copy a winner into the project; close a verdict with a decision
S decide                          record a ruling you made in chat
S slot set / adopt                the asset list; bring in something approved before the Studio existed
S now / milestone set / hand set  the Overview: the build in hand, the road, what only you can do
S motion bake / set / link        motions that loop in the 3D viewer
S status / save                   what waits on whom; commit and push the record
```

`S --help` and `S <command> --help` list every flag.

## Settings

Each Studio has a `studio.toml` in its home:

- `[checks.*]` are the limits a candidate must pass (loudness, length, triangle count, texture
  size). They start loose; set them to your project's own.
- `[review]` sets how many candidates a batch may hold and when the inbox counts as full.
- `[playtests] dirs` names folders of playtest sessions, if your project writes them; the
  Playtests tab appears when it is set.

## Moving, updating, removing

- **Update:** `git pull` in the NocStudio folder. Every Studio uses the new code the next time
  it starts.
- **Back up or share history:** a Studio's home is a git repository. Give it a remote and
  `studio.py save` will push to it.
- **Remove a Studio:** delete its home folder and its line in `studios.json`, and delete
  `.claude\skills\studio` from the project.
- **Remove NocStudio:** delete the Start menu shortcut and the cloned folder. The app keeps a
  browser profile and a log in `%LOCALAPPDATA%\NocStudio`; delete that too.
