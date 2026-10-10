## The Studio (where the user sees the project's state and judges everything)

The Studio for {{PROJECT}} lives at `{{HOME}}`, outside this repo and the same from every worktree.
Use the `studio` skill; `S` is `{{S}}`.

- Anything the user must judge (art, models, sounds, textures, feel options, a question with
  options) is filed as a batch: `S new`, `add`, `file`. Never ask them to open a folder or for a
  pick in chat. After filing, say one line: "<title> is in the Studio (<n> to judge)."
- When they say "process my studio verdicts" (or anything like it), run `S todo` and do what it
  lists; close each with `S done`.
- A ruling they make in chat goes on the log in their words: `S decide`.
- Something only they can do is `S hand set`, not a line in a document.
- Keep the Overview true: `S now` when a build is delivered or the plan changes, `S milestone set`
  when a milestone moves. `S status` answers "what is waiting on me?".
