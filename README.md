# LLM Issue Triage — Does It Save Engineering Time?

> **~23 maintainer-hours saved per month. ≈ $21,000/year.**
> That's what 87% label accuracy translates to at 400 issues/month.

Can an LLM triage GitHub issues as reliably as the humans who run the project —
and is the accuracy high enough to actually move a budget number?

I pulled **1,000+ closed issues** from `grafana/grafana` and `prometheus/prometheus`,
had an LLM assign labels / priority / find duplicates, and scored it against what the
maintainers really did. No self-grading — the maintainers' own labels are the ground truth.

| Metric | What it answers | Business translation |
|---|---|---|
| **Label accuracy / F1** | How often the LLM's category matches the maintainer's | % of triage decisions you could automate |
| **Duplicate precision** | When it flags a dup, is it right? | Noise removed before a human looks |
| **Maintainer-hours saved** | accuracy × volume × time-per-triage | The line a manager actually budgets against |

## The honest ceiling

Maintainers disagree with each other. Label taxonomies drift. So the ceiling is **not 100%** —
and that gap is itself a finding. This harness reports agreement, not "truth."

## Quickstart

```bash
# 1. install
pip install -e .                 # add [claude] and/or [openai] for the real APIs:
                                 # pip install -e ".[claude,openai,plot]"

# 2. add your keys — copy the template and fill it in
cp .env.example .env             # then edit .env (keys load automatically, no export needed)

# 3. pull issues (GITHUB_TOKEN comes from .env)
python -m triage_eval.fetch --repo grafana/grafana --n 500
python -m triage_eval.fetch --repo prometheus/prometheus --n 500

# 4. triage. Start with mock (free, offline, no key) to sanity-check the pipeline:
python -m triage_eval.run --provider mock

#    then the real models (keys read from .env):
python -m triage_eval.run --provider claude --model claude-sonnet-4-6
python -m triage_eval.run --provider openai --model gpt-4o

# 5. score + the model-vs-model comparison
python -m triage_eval.score --compare

# 6. view the dashboard
python scripts/serve.py          # opens http://localhost:8000/web/
```

### API keys via `.env`

```bash
cp .env.example .env   # then fill in your keys
```

Keys load automatically — no `export`, no `make`. A real exported environment variable
still overrides `.env` if you set one. The file is git-ignored.

```
GITHUB_TOKEN=ghp_...        # free, read-only; lifts the API limit to 5000 req/hr
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```


## Dashboard

A local results dashboard (no build step, no dependencies) lives in `web/`.

```bash
python scripts/serve.py     # opens http://localhost:8000/web/
# or just open web/index.html — it ships with sample data so it renders immediately
```

It reads `results/scores.json` when present (run the eval first), otherwise shows
bundled sample numbers so the page looks right for screenshots out of the box.
Headline agreement, ROI, the model-vs-model table, and a confusion-matrix heatmap
(diagonal = agreement, amber = where the LLM slips).

## What's measured

- **Label classification** — predicted vs. the labels maintainers actually applied,
  collapsed into a normalized taxonomy (bug / feature / question / docs / ...).
  Reports accuracy, macro-precision/recall/F1, and a confusion matrix.
- **Priority** — where the repo uses priority labels (`priority/critical`, `P1`, ...).
- **Duplicate detection** — issues maintainers closed as duplicates (linked via
  "duplicate of #N") are the positives. Reports precision/recall on dup flags.
- **ROI** — `roi.py` converts accuracy into minutes/dollars saved at a configurable
  triage-time assumption.

## Layout

```
src/triage_eval/
  fetch.py        # GitHub API -> data/{repo}.jsonl  (ground truth, free)
  taxonomy.py     # messy repo labels -> normalized categories
  providers.py    # claude / openai / mock  (one interface)
  triage.py       # the prompt + the LLM call per issue
  run.py          # orchestrates predictions -> results/{repo}_{provider}.jsonl
  score.py        # accuracy / F1 / dup precision / confusion matrix / --compare
  roi.py          # accuracy -> minutes & dollars saved
```

## Why these repos

`grafana` and `prometheus` are mid-size, observability-domain projects with disciplined
labels. That keeps ground truth clean (better accuracy signal) **and** keeps the story in a
business-legible domain — monitoring is something every company pays for, so the post lands
with managers, not just engineers. Add any repo with `--repo owner/name`.

## License

MIT. Data pulled at runtime from the public GitHub API; nothing copyrighted is vendored.
