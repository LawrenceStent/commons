# Commons

An economy of AI agent co-ops with no one in charge: co-ops find work, contract each other, build reputations and
earn their keep, under rules the world enforces.

- `docs/COMMONS.md`: the complete guide (concepts, architecture, mechanisms, money, roadmap, risks)
- `docs/COMMANDS.md`: every command and script, with every option
- `docs/CHECKLIST.md`: the working build checklist and findings
- `docs/FRAMEWORK.md`: one kernel, many societies (packs, founding, scorecards)
- `docs/REFACTOR-PLAN.md` and `docs/ARCHITECTURE-AUDIT.md`: the architecture refactor (Ports and Adapters)
- `docs/plan.html`: the original design brief

```sh
uv sync
uv run pytest                                          # the test suite, golden master included
uv run commons sim 200                                 # a scripted society (default pack: earn_online)
uv run commons sim 200 --no-rep                        # control run: reputation disabled
uv run commons run --backend fake                      # a live society with fake models (free)
uv run uvicorn commons.interfaces.console.app:app      # the dashboard at http://localhost:8000
```
