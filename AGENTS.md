# Agent notes — Grand Endeavors

Design: DESIGN.md · definitions: framework.yaml · status rubric: gather/RUBRIC.md ·
views: views/EXPLORER.md · backlog: TODO.md. The data repo is `./data` (its own git repo or
worktree; commit data changes there).

## Previewing view changes (dashboard, period pages)

The published site https://pasky.or.cz/grand-endeavors/ is `~/WWW/grand-endeavors`, a
symlink to the MAIN checkout's `build/` (`/home/pasky/projects/hai/grand-endeavors/build/`).
Any change to the dashboard or other views must be reviewable there before merging. In a
side-agent worktree:

```sh
uv run views/explore.py site     # -> this worktree's build/ (index.html, period pages, ledger.sqlite)
name="$(basename "$PWD" | sed 's/^grand-endeavors-agent-//')"     # e.g. worktree-0002
ln -sfn "$PWD/build" "/home/pasky/projects/hai/grand-endeavors/build/$name"
curl -s -o /dev/null -w '%{http_code}\n' "https://pasky.or.cz/grand-endeavors/$name/"   # expect 200
```

Give the owner the URL `https://pasky.or.cz/grand-endeavors/<name>/`. Re-run `site` after
every further change. After the branch is merged (or abandoned), remove the symlink
(`rm /home/pasky/projects/hai/grand-endeavors/build/<name>`; it is only a link) and run
`uv run views/explore.py site` in the main checkout to publish the merged result.
