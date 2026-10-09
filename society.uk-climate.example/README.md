# UK climate investigations (an OSINT society)

The brief, the five starting questions and the operator settings for an OSINT society on UK climate and environment
questions (9 Oct). Search is GOV.UK plus Tavily plus Wikipedia; reads on the vetted hosts in
`operator/config.toml` run without asking; PDFs are read page by page; every page lists its links. How the pack
works and its rules: `docs/OSINT.md`.

```sh
uv run commons calibrate --pack osint --backend lmstudio --model qwen/qwen3.5-35b-a3b
uv run commons found uk-climate --pack osint --brief society.uk-climate.example/brief.md \
  --questions society.uk-climate.example/questions.md --backend lmstudio --model qwen/qwen3.5-35b-a3b
uv run commons found uk-climate --approve
cp -r society.uk-climate.example/operator societies/uk-climate/
uv run commons run --society uk-climate --backend lmstudio --model qwen/qwen3.5-35b-a3b --cycles 3 --serve
```

Tavily needs `TAVILY_API_KEY` in `.env` (1,000 free searches a month); without it, search falls back to GOV.UK and
Wikipedia.
