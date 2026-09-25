# Commons

A non-hierarchical economy of agent communities.

- `docs/COMMONS.md`: the complete guide (architecture, concepts, acronyms, roadmap, reasoning, risks)
- `docs/plan.html`: the original design brief
- `docs/CHECKLIST.md`: the working build checklist and findings

```sh
uv sync
uv run pytest                          # unit + Phase 0 acceptance suite
uv run python -m sim 200               # run a scripted society, print a summary
uv run python -m sim 200 --no-rep      # control run: reputation disabled
uv run uvicorn console.app:app         # live console at http://localhost:8000
```
