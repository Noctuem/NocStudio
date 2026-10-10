## The Studio (where the user sees the project's state and judges everything)

The Studio for {{PROJECT}} lives at `{{HOME}}`, outside this repo and the same from every worktree.
Use the `studio` skill; `S` is `{{S}}`.

- Anything the user must judge (art, models, sounds, textures, feel options, a question with
  options) is filed as a batch: `S new`, `add`, `file`. Never ask them to open a folder or for a
  pick in chat. After filing, say one line: "<title> is in the Studio (<n> to judge)."
- When they say "process my studio verdicts" (or anything like it), run `S todo` and do what it
  lists; close each with `S done`.
- A ruling they make in chat goes on the log in their words: `S decide`.
- Anything else that waits on them (a chore only they can do, a question with a plain answer) is
  `S ask set`, with the default you will use; never a line in chat or in a document.
- Keep the Overview true as you work, not afterwards: `S step set` when a step moves, `S lane set`
  and `S lane done` for work in progress, `S log` for a merge, a publish or a setback, `S now` when a
  build is delivered. `S status` answers "where are we?" and "what is waiting on me?".
