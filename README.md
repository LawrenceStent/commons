# Commons

A non-hierarchical economy of agent communities. See `docs/plan.html` for the design and
`docs/CHECKLIST.md` for progress.

```sh
uv sync
uv run pytest                          # unit + Phase 0 acceptance suite
uv run python -m sim 200               # run a scripted society, print a summary
uv run python -m sim 200 --no-rep      # control run: reputation disabled
uv run uvicorn console.app:app         # live console at http://localhost:8000
```
