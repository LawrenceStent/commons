# Example: a tech-for-good society

    uv run commons found town-help --pack tech_for_good --brief society.tech-for-good.example/brief.md \
        --questions society.tech-for-good.example/questions.md --context society.tech-for-good.example/archive \
        --backend lmstudio --model <id>
    cp -r society.tech-for-good.example/playbooks societies/town-help/
    uv run commons found town-help --approve
    uv run commons run --society town-help --backend lmstudio --model <id> --panel --serve
    uv run commons rate town-help      # rate the work it set aside for you

The archive notes here are placeholders written for the example, not research: replace them with your own sources.
