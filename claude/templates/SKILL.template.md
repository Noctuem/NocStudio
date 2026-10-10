---
name: studio
description: The Studio is where the user sees where {{PROJECT}} stands, judges everything its makers produce, and where their rulings are kept. Use this skill whenever work produces something the user must judge (concept art, textures, models, animations, sounds, tuning or feel options, design questions with options), whenever they say anything like "process my verdicts", "process my studio verdicts", "act on my reviews", "what did I pick", "what is waiting on me" or "plan this project in its Studio", whenever they rule on something in chat or in a playtest note, before asking them to look at any file, folder or in-app option or to do something only they can do, whenever you have a question for them, and whenever work starts, lands, merges, is published or hits a setback, a build is delivered, a milestone moves or the plan changes (the Overview must stay true).
---

# The Studio for {{PROJECT}}

One folder outside this repo: `{{HOME}}`. The user reads and judges in a local
web page (Overview, Inbox, Library, Decisions, Build, and Playtests when a
playtest folder is set); you work through one command. Below, `S` is

    {{S}}

`S --help` and `S <command> --help` list every flag. Never hand-edit the JSON
under the studio home; the commands keep slots, the log and the batches in step.

## The rules

1. **Anything the user must judge is a batch.** Never ask them to open a
   folder, and never ask for a pick in chat. That includes "which of these two
   do you prefer" and every design question with options to weigh. A
   question with a plain answer goes in Needs you as a decision, with your
   default (below); ask in chat only when nothing can go on without it.
2. **One batch, one decision, six candidates at most.** If you made twelve,
   choose the six worth their time, or split by what is being decided.
3. **They see only what passes the checks.** `S file` refuses a batch with a
   broken rule. Fix the candidate. Do not use `--force` to get past a rule.
4. **Nothing happens on a verdict until they say so.** Do not poll for
   verdicts and act on them unasked.
5. **Their words are quoted, never paraphrased**, in briefs, decisions and specs.
6. **After filing, say one line in chat** and stop: `"<title> is in the Studio
   (<n> to judge)."` No description of the candidates, no recommendation in
   chat. Anything they should know goes on the batch.

## Filing a batch

```
S new <slug> --kind <image|texture|model|audio|video|ingame|question|text> \
      --slot <slot id> --title "<what it is>" \
      --ask "<one sentence: what they are choosing>" \
      --look "<where to put the eye>" [--look "..."] \
      [--mode pick|rate|question] [--max-winners 2] \
      [--target height_m=1.8] [--target max_triangles=1500] \
      [--dest <path in the repo>] [--brief-file <what the makers were told>]
S add <batch> <file> [<more files>] --title "<short name>" --summary "<one line>" \
      --tool <tool> --seed <seed> --prompt-file <file> --source <script that made it>
S context <batch> <reference picture> --label "<what it is>"
S file <batch>
```

`new` prints the batch id (`2026-10-08-hero-model-r1`). Choosing the mode:

- **pick**: candidates compete for one slot. The user names a winner.
- **rate**: each candidate stands on its own (a set of materials, each with
  its own `--slot` and `--dest` on `add`). They approve, redo or reject each.
- **question**: options are candidates with `--body` or `--body-file`
  (markdown: what it costs, what it risks, what it feels like). Mark yours
  with `--recommended`. Put the words that raised the question in `--brief`.

What makes a batch worth their time:

- **The ask** is one plain sentence about the choice, not about the work.
- **Look-at points** say where to put the eye, not what to conclude:
  "Height against the 1.8 m figure", never "B has the best silhouette".
- **Every candidate differs in a way they can name.** Give each a short title
  that says how ("Dry crack", "Hall report"), not "Option 3".
- **Provenance on every generated file**: tool, seed, prompt, the script.
- **Hard targets** go in `--target`, so the checks hold the makers to them.
- For something that must be judged **in the running app** (`--kind ingame`),
  add no file: give each candidate `--label` with the exact words shown over
  it in the app, and the batch `--launch` with the line that starts the app.

## Motions they can watch in the Studio

If the project has animated characters, the Studio can loop each motion in
place in its 3D viewer, beside the label, from the project's own samples of
what it draws: one JSON file of each bone's posed matrix per tick, which the
Studio bakes into clips. The file's format is in the docstring of
`tool/studiolib/bake.py` in the kit; the project needs a small exporter that
writes it. A model that already carries animation clips needs no samples:
`S motion set <id> <file.glb>`.

```
S motion bake <set id> <samples.json> [--model <file.glb>]
S motion list                                     every baked clip, as <set>:<clip>
S add <batch> --label "<words over it>" --title "<name>" --motion <set>:<clip>
S motion link <batch> <candidate>=<set>:<clip> [...]     for a batch already filed
S slot set <motion slot> --motion <set>:<clip>           the Library loops it on that asset
```

Bake before you file a motion batch, never after.

## When the user says to process their verdicts

```
S todo
```

It prints every submitted verdict, oldest first, with their words quoted and
the steps for each, and what they answered about the things only they can do.
For each verdict, in order:

- **Ship** (`ship`, `ship_and_iterate`): `S import <batch>` copies the winner
  to the library and to `--dest` in the repo. Then wire it in as the project
  needs (the steps `todo` printed), build, test, commit.
- **Another round** (`another_round`, `ship_and_iterate`): read
  `batches/<batch>/next-round-brief.md`. It lays out what they kept, what to
  redo and what never to try again, in their words. Make the next candidates
  from it and file them as `S new <slug> --parent <batch>`. Bring anything
  marked Keep along with `S carry <new batch> <old batch> <candidate>`. A redo
  note is an order about that one candidate; a Keep is a direction; a Reject
  is a fence.
- **Answer** (a question): the answer is a ruling. Apply it where it belongs.
- **Park**: make nothing more for that slot until they say so.

Close each one when its work is done, not before:

```
S done <batch> --ruling "<what this settles, one sentence>" [--commit <sha>] [--next <new batch>] [--in-game]
```

`done` writes the decision (their notes, exact) and moves the slot's status.
Pass `--in-game` only when the project now runs on the winner. If a verdict
cannot be carried out, do not guess: file a question batch that says so.

## Rulings made outside a batch

```
S decide --title "<what it settles>" --words "<their words, exact>" \
         --ruling "<what follows from them>" --type chat|playtest --ref "<date or build>" \
         [--tag <topic>] [--supersedes D-0041]
```

A reading of their words that they did not state goes in `--ruling` and is
marked as a reading there. Where only a paraphrase exists, leave `--words`
empty and say so in `--ruling`.

## Slots

A slot is one thing the project holds or needs, named by a dotted id
(`weapon.pistol.sfx.shot`, `ui.menu.main`). Add one before the first batch for
a new need, and whenever the project gains an asset:

```
S slot set <id> --title "<name>" --kind <kind> --group <a small fixed set of groups> \
      --status needed|placeholder [--game-path <file, folder or glob in the repo>] [--needed-by <milestone>]
```

`--game-path` is what the user opens from the Library: every picture, model
and sound it matches is shown or played there (`assets/audio/*/step_*.wav`).
`in_game` means they accepted it as it is; what a session made and they have
not judged is `placeholder`. A master approved before the Studio existed comes
in with `S adopt <slot> <file> --note "<their words>" --date <day> --source "<where from>"`.

## Keeping the Overview true

The Overview is the first page the user opens, and they look at it instead of
asking you where things stand. It shows one percentage for the whole project,
what is running now, the milestones with their steps, a chart by day, a log,
and a rail of everything that needs them. All of it is counted from what you
record, so a stale Overview is worse than none. Your standing rules, in every
session:

- **Report each real event when it happens**, not at the end of the session:
  work starts, work lands, a merge, a publish, a setback, an ETA that slips.
- **Every question for the user goes in Needs you**, with the default you will
  use if they do not answer. Do not ask in chat what the Overview already
  shows, and do not stop to wait unless nothing can go on without the answer.
- **Keep ETAs honest**: a clock time or a date, revised when it slips, with a
  setback in the log that says why.
- **Never invent.** Steps, statuses and dates come from the project's real
  plan and history.

### The plan: milestones and steps

```
S milestone set <id> --name "<name>" --status done|current|next|later|parked \
      --goal "<what it is>" --question "<what their verdict answers>" --note "<where it stands>" \
      [--eta "<when it should be done>"] [--weight 2]
S step set <milestone> <step id> --name "<the step, as the user would say it>" --status <status>
S step list [<milestone>]
```

A step is something that is either done or not, small enough to land in a day
or two. Its status is where it truly stands: `planned`, `building`, `built`
(made, not yet proven), `tested` (proven by a test or a run), `done` (accepted
and in the project), `parked`, or `dropped` (no longer in the plan; a step is
never deleted). The percentage is counted from these: done 1, tested 0.85,
built 0.6, building 0.3. A milestone is the average of its steps; the project
is the average of its milestones, by `--weight` (1 unless one is plainly more
work). Break the current milestone into steps before work on it starts; later
ones can hold a few coarse steps until they are near. Milestones show in the
order they were first added. Only the user's recorded verdict makes a
milestone that ends on their verdict `done`.

`S plan` prints the whole plan as one JSON document; `S plan <file>` writes
one in (it adds and changes, and removes nothing).

If the Overview says "Getting organised", or the user says "plan this project
in its Studio", the plan has holes. Read what the project has, draft the goal,
the road and the steps of the milestone in hand, show the user the outline to
correct, ask only what they alone can answer, and write it in with
`S plan <file>`. The goal goes in `S now --goal`, in their words.

### Running now: lanes

A lane is one piece of work in progress. Start one when you begin something
that takes more than a few minutes, and whenever you hand work to a subagent,
a workflow or a background task:

```
S lane set <id> --name "<the work, in a few words>" --milestone <id> --step <step id> \
      --eta "<16:30, or a date>" [--note "<where it stands, one line>"] [--state building|testing|waiting|stuck]
S lane done <id> [--step-status built|tested|done] [--note "<how it ended>"]
```

Starting a lane on a planned step marks the step `building`. `lane done
--step-status` moves the step and takes the lane off the board. Update the
note, the ETA and the state as it goes: `stuck` with the reason in the note,
`waiting` when it waits on the user (with an ask in Needs you). Never leave a
lane on the board that nobody is working.

Claude Code's hooks also report, by themselves, what each session is doing
(working, waiting, which agents are running); that needs nothing from you.
`S hooks status` says whether they are installed on this machine.

### The log

A step that reaches `done` and a lane that starts or ends log themselves. Add
what the tool cannot know, when it happens:

```
S log merge "<what merged>"
S log publish "<what was published or delivered>"
S log setback "<what went wrong, and what it costs>"
S log note "<worth remembering>"            [--milestone <id>] [--step <id>]
```

A setback is logged the moment you know of it, not when it is fixed.

### Needs you: asks

Anything that waits on the user and is not a batch: something only they can
do, or a question only they can answer. Never leave one only in chat or in a
document.

```
S ask set <id> --kind action|decision|play|info \
      --title "<the thing, as an instruction or a question>" --detail "<why, and what to look for>" \
      --gates "<what it blocks>" --default "<what you will do if they say nothing>" \
      --time "<how long it takes them>" [--run "<a line to copy>"] [--urgent] \
      --group <a short group name> --status open|later
```

- `decision` is a question with a plain answer; if there are options to
  weigh, file a question batch instead. `play` is a build to try. `action` is
  a chore (a check on another machine, a purchase, a paper). `info` is
  something they should know and need not answer.
- Give every decision a `--default`. If work reaches that point unanswered,
  act on the default and say so in the log.
- `--urgent` only when work is stopped on it. `later` is theirs, but nothing
  waits on it yet.

They answer on the page. `S todo` prints what they said; act on it, then
`S ask seen <id>`. If they answer in chat instead, close it with their words:
`S ask answered <id> --answer "<their words, exact>"`.

### The build in hand

When a build is delivered, a fix lands that they will see, or the plan
changes, in the same session:

```
S now --headline "<one sentence: where the project stands>" --build <build id> --spec <plan of record> \
      --gate "<the last test run, in a few words>" \
      --built "<something they can see in the build>" [--built ...] \
      --next "<what comes next> :: <when>" [--next ...] \
      [--known "<known and left as it is>"] [--start "<a line that starts the build>"] \
      [--goal "<what the project is and what done looks like>"] \
      [--finish "<your honest estimate for the whole project>"] [--counter "<Name>=<have>/<of>"]
```

A list you pass replaces the old one; what you leave out stays. `S now` with
no flag prints what stands. Counters are what the user counts the project by
(`Levels=2/9`). The page shows how many commits the repo has made since this
was written, so staleness is visible.

## Playtest notes

Only when `studio.toml` names a playtest folder (`[playtests] dirs`, each
session a folder holding `f8-<n>/note.txt` and a screenshot). When a fix
lands, say what became of each note; the user confirms after playing:

```
S triage "<session folder>/f8-<n>" --status planned|fixed|wontfix|question \
         [--build <build>] --ref "<commit or decision>" --note "<what was done>"
```

## Samples

`samples/` holds made-up batches the user tries the page on (Inbox: Samples),
and `sample.figure` is their made-up motion. They are never in `S todo` or
`S status`. Never import, close, record or act on one, and never put
`sample.figure` on a real batch or slot. `S samples` makes any that are
missing (`--model <rigged .glb>` moves that model in place of the kit's own
figure); `S samples --fresh` makes them all again.

## Saving the Studio

The studio home is a git repository of its own; its history is the record of
what the user judged, what they ruled and what was filed for them. Keeping it
current is yours, not theirs:

```
S save [-m "<what changed, one line>"]
```

It rewrites the plain-text index, commits everything in the home (the user's
verdicts and answers made on the page included) and pushes. Run it when the last
verdict of an `S todo` pass is closed, after you file a batch, record a ruling
or change the overview, and always before the session ends: `S status` and
`S todo` say when the Studio has unsaved changes. If it prints "NOT pushed",
say so to the user in one line; do not leave it silent.

## Checking your own work

- `S check <batch>` runs the checks without filing.
- `S status` shows how far along the project is, what is running, what waits
  on the user and what waits on you, and says when the board is not true.
  `S step list`, `S lane list`, `S ask list` and `S log` print the rest.
- Before you say a batch is filed, confirm `S file` printed "Filed."
