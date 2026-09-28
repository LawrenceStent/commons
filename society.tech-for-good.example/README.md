# Example: a tech-for-good society

    uv run python -m sim.found town-help --pack tech_for_good --brief society.tech-for-good.example/brief.md \
        --questions society.tech-for-good.example/questions.md --context society.tech-for-good.example/archive \
        --backend lmstudio --model <id>
    cp -r society.tech-for-good.example/playbooks societies/town-help/
    uv run python -m sim.found town-help --approve
    uv run python -m sim.live --society town-help --backend lmstudio --model <id> --panel --serve
    uv run python -m sim.rate town-help      # rate the work it set aside for you

The archive notes here are placeholders written for the example, not research: replace them with your own sources.
