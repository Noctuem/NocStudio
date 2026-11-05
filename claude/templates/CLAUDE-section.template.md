## The Studio (where the user sees the project's state and judges everything)

The Studio for {{PROJECT}} lives at `{{HOME}}`, outside this repo and the same from every worktree.
Use the `studio` skill; `S` is `{{S}}`.

- Anything the user must judge (art, models, sounds, textures, feel options, a question with
  options) is filed as a batch: `S new`, `add`, `file`. Never ask them to open a folder or for a
  pick in chat. After filing, say one line: "<title> is in the Studio (<n> to judge)."
- Their verdicts, and what they answer on the page, are handed to you by Claude Code's hooks when you
  finish a turn or they send you a message (or they say "process my studio verdicts"): run `S todo`
  and do what it lists; close each with `S done`.
- A ruling they make in chat goes on the log in their words: `S decide`.
- Anything else that waits on them (a chore only they can do, a question with a plain answer) is
  `S ask set`, with the default you will use; never a line in chat or in a document. A command for
  them to run on this PC, or a file for them to open, is a button: `S ask set <id> --button`.
- Notes they type in the Studio are handed to you by Claude Code's hooks; never poll for them. Sort
  each one (`S note sort`, or `S note reply` for a discussion), make no change for a directive or a
  rule until they confirm it on the page, and close what you did with `S note done`.
- Keep the Overview true as you work, not afterwards: `S step set` when a step moves, `S lane set`
  and `S lane done` for work in progress, `S log` for a merge, a publish or a setback, `S now` when a
  build is delivered. `S status` answers "where are we?" and "what is waiting on me?".
