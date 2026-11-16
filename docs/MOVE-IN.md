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

- Windows 10 or 11, Python 3.11 or newer with the `py` launcher, git, and Edge or Chrome.
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
- It shows you a short outline (the goal, the milestones, the steps for the one in hand) and
  asks, once, only what it cannot find in the files. The goal is yours to say, in your words.
- It asks before it installs the hooks that let your sessions report in and hand you their
  questions. That is a change to your agent's own settings, once per machine.
- It changes no product code. It adds the Studio skill and a short section in your agent's
  instructions file, and commits only those.
- When it is done, your project is in the NocStudio menu, every line of Getting organised is
  ticked, and the box is gone. If you would rather not see the box before then, Hide puts it
  away for that project.

---

## For the agent

The user has asked you to move the project you are working in into NocStudio. Work through
the steps below in order and skip any that are already done. When you finish, every line of
the Getting organised list is ticked. Do not stop at an empty Studio.

### The rules while you do this

- Change no product code. You write documents, the skill and the Studio's own records.
- Read before you ask. Ask the user once, in one round, only what the files cannot answer.
- The goal and the house rules are theirs. Quote their words, never paraphrase them into a
  record.
- Never invent a step, a status or a date. For a project with history, statuses and dates are
  your reading of the documents and the git log; say so when you report.
- Commit with explicit paths. If another session may be working in the repo, re-read each file
  right before you edit it.

### 0. Find the tool

NocStudio's folder is the one that holds the `docs` folder this file is in. Call it `<kit>`.
Below, `K` means:

```
py -3.11 "<kit>\tool\studio.py"
```

If `py -3.11 --version` fails, or `py -3.11 "<kit>\tool\selftest.py"` does not end with
`All good.`, stop and tell the user. Do not repair or rebuild the tool.

Note which agent you are: Claude Code, or Codex. Every command below that takes `--for`
needs `--for codex` when you are Codex, and nothing when you are Claude Code. If both work in
this project, give `--for claude --for codex`.

### 1. The Studio (makes the home)

`K studios` lists every Studio on this machine. If this project already has one, take its
home from that list and go to step 2.

If it has none:

```
K create "<the project's folder>" --project "<its name as the page should show it>" [--for codex]
```

It makes `<folder>-studio` beside the project (its own git repository), picks a free port,
puts the skill in the project, and prints the command for everything after. Below, that
command is `S`:

```
py -3.11 "<kit>\tool\studio.py" --home "<the Studio's home>"
```

Then run `S status`. Its Getting organised list is the same as the Overview's, and tells you
which of the steps below are left.

### 2. The skill (line: "The project's sessions know the Studio's rules")

- The skill lives at `.claude\skills\studio\SKILL.md` for Claude Code and
  `.agents\skills\studio\SKILL.md` for Codex, inside the project. `create` puts it there. If
  this project's Studio is older than that, write it with
  `S skill > "<project>\.claude\skills\studio\SKILL.md"` (or the Codex path).
- Read it now. From here on it is how you use the Studio.
- Merge `<home>\CLAUDE-section.md` into the project's instructions file near the top:
  `CLAUDE.md` for Claude Code, `AGENTS.md` for Codex. Make the file if there is none. Keep the
  section short and follow any length rule the file sets for itself.
- Where the instructions send the user to folders, to picks in chat, or to another review
  tool, change them to send the user to the Studio. Leave history as it is.
- Commit only the skill and the instructions file, by path.

### 3. Read, draft, ask once (lines: goal, milestones, steps)

Read what the project has: the README, the instructions file, any plan or TODO, specs, the
code's shape, the asset folders, the git log. Then draft the whole plan yourself and show it to
the user in chat as a short outline to correct, not a form to fill in. Put every open point in
the same message. A plan has:

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

Wait for their answer, then write it all in at once. `S plan` prints the shape:

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

Step statuses: `planned`, `building`, `built`, `tested`, `done`, `parked`, `dropped`. A step
that landed on an earlier day takes `"date": "YYYY-MM-DD"`, so the chart starts with the
project's real history. Then:

- `S ask set` for each thing only they can do and each open question, every decision with the
  `--default` you will use.
- `S decide` for the goal and each house rule. `--words` only where they are quoted exactly.

### 4. The asset list (line: "A list of what the project holds or still needs", if it has any)

A project with art, sound, models, video or writing lists them as slots, one per thing, named
as the user would name it:

```
S slot set <id> --title "<name>" --kind <image|texture|model|audio|video|text|...> --group <group> \
      --status in_use|placeholder|needed --project-path "<file, folder or glob in the project>"
```

`in_use` only where the documents show the user accepted it, `placeholder` for anything else
the project holds, `needed` only for what a named milestone calls for. A project that is all
code skips this step; the line is marked "if it has any" and does not hold the box open.

For a large project, hand the asset list to a subagent with a brief that names the home, the
project, these status rules, and that it must not commit or change the project.

### 5. Live reporting (line: "Sessions report in on their own while they work")

`S hooks status` says whether your agent already reports to NocStudio and is handed the notes
the user types in the Studio. If not, tell the user in two lines what installing does: it adds
one entry per event to their own agent settings (Claude Code: `~\.claude\settings.json`;
Codex: `~\.codex\hooks.json`), keeps a copy of the file from before, works for every project
that has a Studio and for none that has not, and makes a session wait a moment at the end of a
turn and after each tool call so their notes can reach it. When they agree:

```
S hooks install [--for codex]
```

It is once per machine; `S hooks remove` takes it out. Codex runs new hooks only after the
user trusts them: ask them to run `/hooks` in Codex once.

### 6. Prove it and report

- `S status` lists no unticked line in Getting organised (the asset line may stay open on a
  project with none) and no advice about the board.
- `S save` commits the Studio's home.
- Tell the user in a few lines: the project is in the NocStudio menu (Start menu: NocStudio),
  the milestones you wrote and how far along it is, what is in Needs you, and every judgement
  call they should check (statuses and dates you read from history, asset statuses).

From here on, the skill's standing rules keep the Overview true as the project's sessions work.
