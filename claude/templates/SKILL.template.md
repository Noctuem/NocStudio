---
name: studio
description: The Studio is where the user sees where {{PROJECT}} stands, judges everything its makers produce, and where their rulings are kept. Use this skill whenever work produces something the user must judge (concept art, textures, models, animations, sounds, tuning or feel options, design questions with options), whenever they say anything like "process my verdicts", "process my studio verdicts", "act on my reviews", "what did I pick" or "what is waiting on me", whenever they rule on something in chat or in a playtest note, before asking them to look at any file, folder or in-app option or to do something only they can do, and whenever a build is delivered, a milestone moves or the plan changes (the overview must stay true).
---

# The Studio for {{PROJECT}}

One folder outside this repo: `{{HOME}}`. The user reads and judges in a local
web page (Overview, Inbox, Library, Decisions, and Playtests when a playtest
folder is set); you work through one command. Below, `S` is

    {{S}}

`S --help` and `S <command> --help` list every flag. Never hand-edit the JSON
under the studio home; the commands keep slots, the log and the batches in step.

## The rules

1. **Anything the user must judge is a batch.** Never ask them to open a
   folder, and never ask for a pick in chat. That includes "which of these two
   do you prefer" and every design question with options to weigh. A quick
   question that has no options to weigh is asked in chat.
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

## Keeping the overview true

The Overview is the first page the user opens. Three things on it are yours to
keep current; a stale overview is worse than none.

- **The build in hand.** When a build is delivered, a fix lands that they
  will see, or the plan changes, in the same session:
  ```
  S now --headline "<one sentence: where the project stands>" --build <build id> --spec <plan of record> \
        --gate "<the last test run, in a few words>" \
        --built "<something they can see in the build>" [--built ...] --next "<what comes next>" [--next ...] \
        [--known "<known and left as it is>"] [--start "<a line that starts the build>"]
  ```
  A list you pass replaces the old one; what you leave out stays. `S now`
  with no flag prints what stands. The page shows how many commits the repo
  has made since this was written, so staleness is visible.
- **The road.** `S milestone set <id> --name "<name>" --status done|current|next|later|parked
  --goal "<what it is>" --question "<what their verdict answers>" --note "<where it stands>"`.
  Milestones show in the order they were first added.
- **What only they can do** (try a build, a check on another machine, a
  purchase, a paper). Never leave such an ask only in chat or in a document:
  ```
  S hand set <id> --title "<the thing, as an instruction>" --detail "<why, and what to look for>" \
        --gates "<what waits on it>" --time "<how long it takes>" [--run "<a line to copy>"] \
        --group <a short group name> --status open|later
  ```
  `open` is on their list now; `later` is theirs but nothing waits on it yet.
  They mark each Done or Not now on the page, with a note. `S todo` prints
  what they answered; act on it, then `S hand seen <id>`.

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
- `S status` shows what waits on the user and what waits on you; `S hand list`
  and `S milestone list` print the rest of the overview.
- Before you say a batch is filed, confirm `S file` printed "Filed."
