# Moving a project into NocStudio

NocStudio is a studio designed to help with the judgement and reviewal process for AI game devs,
artists, and content creators. Your coding agent files what it makes (art, models, sounds,
clips, choices) for you to judge on one page, and keeps the project's plan, progress and your
rulings there too.

This guide has two halves. The first is for you. The second is for your agent: you hand it this
file and it does the rest.

---

## For you

### What you need

- Windows 10 or 11; Python 3.11 with the `py` launcher (every command runs `py -3.11`, so
  3.11 itself must be installed, even beside a newer one); git; Edge or Chrome.
- Claude Code or Codex, working in your project's folder.
- NocStudio itself, cloned somewhere it can stay. Every Studio runs from that one folder.

```
git clone https://github.com/Noctuem/NocStudio.git
cd NocStudio
py -3.11 tool\studio.py app --install
```

The last line puts NocStudio in the Start menu.

### The one line

Open your agent in your project, at any point in its life, and paste this, with the path to
this file where you cloned NocStudio:

```
Read C:\path\to\NocStudio\docs\MOVE-IN.md and move this project into NocStudio.
```

A Studio's Overview shows the same line, with the right path filled in, under Getting
organised.

### What happens

- The agent reads your project first: the README, its instructions file, any plan, the code's
  shape, the asset folders, the git log.
- It sends you one message: a short outline (the goal, the milestones, the steps for the one in
  hand), the few things it cannot find in the files, and whether it may install the hooks. The
  goal is yours to say, in your words. That is the only time it asks in chat; anything you
  leave open goes in Needs you with the default it will use.
- The hooks let your sessions report in while they work and pick up the notes and verdicts you
  leave in the Studio. Installing them changes your agent's own settings, once per machine. In
  Codex you also type `/hooks` once and trust NocStudio's.
- It changes no product code. It adds the Studio skill and a short section in your agent's
  instructions file, and commits only those.
- When it is done, the project is in the NocStudio menu, Getting organised is ticked and the box
  is gone. The asset list counts only if the project has art, sound or the like. If you would
  rather not see the box before then, Hide puts it away for that project.

---

## For the agent

The user has asked you to move the project you are working in into NocStudio. Work through
the steps below in order and skip any that are already done. When you finish, every needed line
of the Getting organised list is ticked. Do not stop at an empty Studio.

### The rules while you do this

- Change no product code. You write documents, the skill and the Studio's own records.
- Read before you ask. You ask the user once, in one message (step 3). This is the one time a
  question goes in chat; the Studio skill sends every later one to Needs you.
- The goal and the house rules are theirs. Quote their words, never paraphrase them into a
  record.
- Never invent a status or a date. Statuses for work from before the Studio are your reading
  of the documents and the git log: an item a TODO ticks, where the code does not show it, is
  `built`, not `done`, until the user says otherwise. Steps you draft for the outline are fine;
  they are the plan once the user has seen the outline.
- Commit with explicit paths. If another session may be working in the repo, re-read each file
  right before you edit it.

### 0. Find the tool

NocStudio's folder is the one that holds the `docs` folder this file is in. Call it `<kit>`.
Below, `K` means:

```
py -3.11 "<kit>\tool\studio.py"
```

`K` is only for `K studios` and `K create`. Every other command is `S` (below), which names the
Studio's home with `--home`: the shell may have `STUDIO_HOME` set for another project's Studio,
and a command without `--home` would act on that one.

If `py -3.11 --version` fails, stop and tell the user they need Python 3.11. Do not repair or
rebuild the tool.

Note which agent you are: Claude Code, or Codex. Every command below that takes `--for` needs
`--for codex` when you are Codex, and nothing when you are Claude Code. If both work in this
project, give `--for claude --for codex`.

### 1. The Studio (makes the home)

`K studios` lists every Studio on this machine. If this project already has one, take its
home from that list and go to step 2.

If it has none:

```
K create "<the project's folder>" --project "<its name as the page should show it>" [--for codex]
```

It makes `<folder>-studio` beside the project (its own git repository), picks a free port
(`--port` sets one), puts the skill in the project, and prints the command for everything
after. Below, that command is `S`:

```
py -3.11 "<kit>\tool\studio.py" --home "<the Studio's home>"
```

Then run `S status`. Its Getting organised list is the same as the Overview's and shows which
lines are left. The count is of the needed lines; the asset line is "only if it has any".

### 2. The skill (line: "The project's sessions know the Studio's rules")

The line is ticked once the skill is in the project and an instructions file names this
Studio's home. Both parts:

- **The skill** lives at `.claude\skills\studio\SKILL.md` for Claude Code and
  `.agents\skills\studio\SKILL.md` for Codex, inside the project. `create` puts it there for the
  agent it was made for. If it is not at your agent's path (an older Studio, or one made for
  the other agent), write it with `S skill --out "<project>\.claude\skills\studio\SKILL.md"` (or
  the Codex path). Use `--out`, not `>`: PowerShell's `>` writes a file the tool cannot read.
- Read the skill now. From here on it is how you use the Studio.
- **The section.** Merge `<home>\CLAUDE-section.md` into the project's instructions file, near
  the top: `CLAUDE.md` for Claude Code, `AGENTS.md` for Codex (it reads the same for both). Make
  the file if there is none. Paste it as it is; it names the home, which is what ticks the line.
  Trim it only if the file limits its own length ("keep this file under 40 lines"); a limit on
  the code is not one.
- Where the instructions send the user to folders, to picks in chat, or to another review
  tool, change them to send the user to the Studio. Leave history as it is.
- Commit only the skill and the instructions file, by path, with a message like
  `Studio: the project's sessions know its Studio`.

### 3. Read, draft, ask once (lines: goal, milestones, steps)

Read what the project has: the README, the instructions file, any plan or TODO, specs, the
code's shape, the asset folders, the git log. Run `S hooks status` too. Then draft the whole
plan yourself and send the user one message: the outline to correct, not a form to fill in,
with every open point in it. A plan has:

- **The goal.** What the project is, who it is for, what done looks like, in a sentence or
  two. Theirs to say; if the files already hold it in their words, quote it and ask them to
  confirm.
- **The milestones.** Three to seven, from here to done. Each ends in something they can see
  or try, and names the question their verdict will answer.
- **The steps of the milestone in hand.** Five to twelve, each done or not, each small enough
  to land in a day or two. Later milestones get a few coarse steps.
- **Counters**, if they count the project by something: levels, pages, songs.
- **What only they can do**, known today: an account, a test on another machine, a purchase.
- **House rules**, in their words: the look, hard limits, what never to do.
- **Dates**, only if they want them. Leave them out otherwise; nothing needs one.
- **The hooks** (step 5), if `S hooks status` says they are not installed for your agent: the
  two lines step 5 gives, and whether you may install them. For Codex, ask them also to type
  `/hooks` in Codex once and trust NocStudio's.

Wait for their answer. If it does not fit what the files say (a different project, a goal the
code has nothing of), say so and ask again before you write anything. Then write the plan in at
once, from a file outside the project (your
temp folder), so the project gets no stray file:

```
S plan <file.json>
```

```
{"goal": "<their words>", "headline": "<where the project stands today>",
 "counters": ["Levels=1/3"], "next": ["<what comes next>"],
 "milestones": [{"id": "M1", "name": "<name>", "status": "current",
                 "goal": "<what it is>", "question": "<what their verdict answers>",
                 "steps": [{"id": "<short-id>", "name": "<the step, as they would say it>", "status": "planned"}]}]}
```

- `S plan` with no file prints what is there now (empty on a new Studio). The file may also
  hold `"asks"` and `"slots"` lists, or you can add those with the commands below.
- A milestone takes `"eta": "<a date>"` and a `next` line takes ` :: <when>` only when the
  user or the files give the date.
- Step statuses: `planned`, `building`, `built`, `tested`, `done`, `parked`, `dropped`. A step
  that landed on an earlier day takes `"date": "YYYY-MM-DD"`, so the chart starts with the
  project's real history.
- The goal in the plan is the same as `S now --goal`; either sets it.
- A milestone the documents mark finished before the Studio may go in as `done`; say so in
  your report so the user can correct it.

Then:

- `S ask set <id> --kind decision|action --title "..." --default "..."` for each thing only
  they can do and each question they left open.
- `S decide --title "The goal" --words "<their words, exact>" --ruling "<what follows>" --type chat --ref <today>`
  for the goal, and one the same way for each house rule.

### 4. The asset list (line: "A list of what the project holds or still needs", if it has any)

A project with art, sound, models, video or writing lists them as slots, one per thing, named
as the user would name it:

```
S slot set <id> --title "<name>" --kind <image|texture|model|audio|video|text|...> --group <group> \
      --status in_use|placeholder|needed --project-path "<file, folder or glob in the project>" [--needed-by <milestone>]
```

`in_use` only where the documents show the user accepted it; `placeholder` for anything else
the project holds, and for an asset the plan says to replace (with `--needed-by` the milestone
that replaces it); `needed` only for what a named milestone calls for and the project does not
have. A project that is all code skips this step.

For a large project, hand the asset list to a subagent with a brief that names the home, the
project, these status rules, and that it must not commit or change the project.

### 5. Live reporting (line: "Sessions report in on their own while they work")

`S hooks status` says whether your agent already reports to NocStudio and is handed the notes
the user types in the Studio. If not, the two lines for the user (in the step 3 message):
installing adds one entry per event to their own agent settings (Claude Code:
`~\.claude\settings.json`; Codex: `~\.codex\hooks.json`) and keeps a copy of that file as it
was, if there was one; it works for every project that has a Studio and for none that has not; and a session
waits a moment at the end of a turn and after each tool call, so their notes can reach it.
When they have agreed:

```
S hooks install [--for codex]
```

It is once per machine; `S hooks remove [--for codex]` takes it out. A Codex install does
nothing until the user has trusted it with `/hooks` in Codex.

### 6. Prove it and report

- `S status` shows no Getting organised list (it is gone once the needed lines are ticked), or
  only the asset line on a project with no assets, and no advice about the board.
- `S hooks status` says your agent reports in and its sessions are handed the user's notes.
  The hooks line is ticked when any agent's hooks are in, so check your own.
- `S log note "Moved into NocStudio"`, then `S save`, which commits the Studio's home. A new
  Studio has no git remote, so `NOT pushed: no remote is set` is expected; say so in one line.
- Tell the user in a few lines: that `K studios` lists the project, so it is in the NocStudio
  menu (the Start menu has NocStudio once they have run `app --install`); the milestones you
  wrote and how far along it is; what is in Needs you; and every judgement call they should
  check (statuses and dates you read from history, asset statuses).

From here on, the skill's standing rules keep the Overview true as the project's sessions work.
