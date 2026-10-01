# Example society folder

Copy this to `societies/<name>/`, or found a new one from a brief:

    uv run commons found <name> --pack earn_online --brief society.example/brief.md \
        --context society.example/archive --backend lmstudio --model <id>
    uv run commons found <name> --approve
    uv run commons run --society <name> --backend lmstudio --model <id> --serve

A society folder holds: society.toml, brief.md, blueprints.toml (drafted, then approved by you),
archive/ (reference files), playbooks/ (<capability>--<title>.md, seeded into the library),
an optional operator/ folder, and runs/. The real societies/ folder is git-ignored.
