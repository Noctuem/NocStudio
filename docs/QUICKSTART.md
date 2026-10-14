# Quick start

Ten minutes from a clone to a planned project and your first judged batch.

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

## 6. Plan the project with your agent

An empty Studio is not much use: the Overview counts progress from a plan, so the project needs
one. Install the setup skill once:

```
py -3.11 tool\studio.py install-skill
```

Then say one of these to Claude Code:

| Say | When |
|---|---|
| **start a new project** | You have an idea and no folder yet. It makes the folder, the Studio and the plan. |
| **set up a studio for this project** | The project exists and has no Studio. This replaces step 2 and step 5. |
| **plan this project in its Studio** | The Studio exists and its Overview says "Getting organised". |

It reads what the project already has, drafts the plan and shows it to you as a short outline to
correct, and asks only what you alone can answer:

- the **goal**: what the project is and what done looks like, in your words
- the **milestones** from here to done, each ending in something you can see or try
- the **steps** of the first milestone, each small enough to land in a day or two
- what you **count** the project by (levels, pages, endpoints), if anything
- your **house rules**: standing decisions every session must follow
- what **only you can do**, and what may go ahead on its default without waiting for you

Then it writes the plan in. The Overview's "Getting organised" checklist shows what is still
missing until nothing is.

## 7. Turn on live reporting

```
py -3.11 tool\studio.py hooks install
```

This adds NocStudio's hook to your own Claude Code settings (`~/.claude/settings.json`), one
entry per event, and keeps a copy of the file as it was (`settings.json.before-nocstudio`). From
then on every Claude Code session in a project that has a Studio shows under **Running now** on
its Overview: working or waiting for you, the last thing it did, which subagents and background
workflows are running. Sessions in a git worktree of the project are found too.

The same hook hands a session the notes you type on the Studio's **Notes** page: when the
session finishes a turn, and between tool calls once a note has waited ten minutes (`[notes]
after_minutes` in `studio.toml`) or is marked urgent. Nothing polls, so an empty notes box costs
no tokens. For that, the session waits a moment for the hook at those two points; every other
entry runs in the background.

With no note waiting the hook prints nothing. It never fails a session, writes only to the
Studio's `live` folder (which is left out of the Studio's git history), and does nothing at all
in a project without a Studio. `py -3.11 tool\studio.py hooks remove` takes it out again. If you
installed the hook before the notes box existed, run `hooks install` once more.

## The daily loop

| You | Your agent |
|---|---|
| Open NocStudio and look at the Overview instead of asking for a status update | Moves steps as they land, keeps a lane with an ETA for each piece of work in progress, logs merges, publishes and setbacks |
| Answer what is in Needs you, or leave it and let the default stand | Puts every question there with the default it will use, and goes on working |
| Judge what is in the Inbox | Files batches; the checks hold back what breaks a rule |
| Type a note whenever a thought comes; confirm a change, answer a thread | Is handed your notes at its next break, says what it takes each to mean, works in what you confirm |
| Say "process my studio verdicts" | Runs `studio.py todo`, acts on each verdict and each answer, closes it with a decision |
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
S milestone set / step set / plan the road and its steps; the whole plan as one document
S lane set / lane done / log      work in progress with an ETA; merges, publishes and setbacks
S ask set / ask answered          what waits on you: a chore, a build to try, a question with a default
S note sort / reply / done        your notes: say what one means, answer a discussion, close what was done
S now                             the build in hand, the goal, counters, what comes next
S hooks install / remove / status live reporting from Claude Code's sessions
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
- **Remove NocStudio:** run `py -3.11 tool\studio.py hooks remove`, then delete the Start menu
  shortcut and the cloned folder. The app keeps a
  browser profile and a log in `%LOCALAPPDATA%\NocStudio`; delete that too.
