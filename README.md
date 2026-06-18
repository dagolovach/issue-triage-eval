# LLM Issue Triage — Does It Save Engineering Time?

> **86% label accuracy on grafana/grafana. 1,500 issues across 3 repos. ~$13,500/yr saved at 275 issues/month.**
> The interesting finding isn't the accuracy — it's that confidence calibration breaks on one repo, and that's what decides whether you can safely automate at all.

Can an LLM triage GitHub issues as reliably as the humans who run the project —
and is the accuracy high enough to actually move a budget number?

1,500 closed issues from `grafana/grafana`, `prometheus/prometheus`, and `cli/cli`.
LLM assigns labels, priority, and duplicate flags. Scored against what maintainers actually did.
No self-grading — the maintainers' own labels are the ground truth.

| Repo | Sample | Monthly inflow | Accuracy | Gross savings/yr |
|---|---|---|---|---|
| grafana/grafana | 205 issues | 275/mo | 86% | ~$13,500 |
| prometheus/prometheus | 128 issues | 37/mo | 77% | ~$1,600 |
| cli/cli | 449 issues | 64/mo | 64% | ~$2,300 |

*Monthly inflow = lifetime avg from GitHub API. Sample = issues with scoreable maintainer labels.*

## The honest ceiling

Maintainers disagree with each other. Two humans labeling the same issue probably agree ~85% of the time.
At 86% on grafana, we may be near the human-human ceiling — the remaining "errors" might not be errors.

We can only score issues maintainers actually labeled: 41% of grafana, 26% of prometheus, 90% of cli/cli.
If maintainers preferentially label clear-cut issues, accuracy here is measured on the easy subset.

## The calibration finding

The model returns a confidence score with every label. On grafana and prometheus, confidence cleanly separates good predictions from bad. On cli/cli, it carries zero signal — high-confidence predictions are 64% accurate, identical to the overall average.

This matters: the automation case rests on routing high-confidence labels automatically and sending uncertain ones to a human. That only works if confidence predicts accuracy. **Measure calibration per repo before trusting a two-lane policy.**

## Quickstart

```bash
# 1. install
pip install -e ".[claude,openai,plot]"

# 2. add your keys
cp .env.example .env    # then edit .env

# 3. pull issues
make fetch              # grafana + prometheus + cli/cli, 500 issues each

# 4. triage (start with mock — free, offline, no key)
make run-mock

#    then real models (keys from .env):
make run-claude         # claude-sonnet-4-6, 10 parallel workers
make run-openai         # gpt-4o, 10 parallel workers

# 5. score
make score

# 6. dashboard
make serve              # http://localhost:8000/web/
```

`results/scores.json` and `results/repo_stats.json` are committed — the dashboard renders immediately on clone without running the LLM.

### API keys via `.env`

```
GITHUB_TOKEN=ghp_...        # free, read-only; lifts rate limit to 5000 req/hr
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

Keys load automatically — no `export` needed. Git-ignored.

## Dashboard

```bash
make serve    # http://localhost:8000/web/
# or open web/index.html directly — ships with sample data
```

Shows: label accuracy · ROI by repo (with verdict) · confidence calibration · confusion matrix · model comparison · cost per issue · latency per issue.

## What's measured

- **Label classification** — predicted vs. maintainer labels, normalized to a fixed taxonomy (bug / feature / question / docs / ci/build / security / other). Reports accuracy, macro F1, confusion matrix.
- **Confidence calibration** — per-tier accuracy (high ≥0.8 / medium / low) and calibration gap. Tells you whether the model knows when it's wrong.
- **Priority** — where repos use priority labels (meaningful on prometheus: 77% accuracy, n=53).
- **Cost per issue** — actual API tokens billed, not an estimate.
- **Latency per issue** — wall-clock time per prediction.
- **ROI** — gross savings/yr, net savings/yr, break-even months, ROI multiplier vs human baseline.

## Layout

```
src/triage_eval/
  fetch.py        # GitHub API -> data/{repo}.jsonl  (ground truth, free)
  taxonomy.py     # messy repo labels -> normalized categories
  providers.py    # claude / openai / mock  (one interface, cost tracking)
  triage.py       # prompt + LLM call per issue
  run.py          # parallel predictions -> results/{repo}_{provider}.jsonl
  score.py        # accuracy / F1 / calibration / ROI / --compare
  roi.py          # accuracy + volume -> minutes & dollars saved
scripts/
  serve.py        # local dashboard server
web/
  index.html      # dashboard (no build step, no dependencies)
```

## Why these repos

- **grafana/grafana** — high volume (275/mo), 12 years of issues, disciplined labeling. The clearest ROI case.
- **prometheus/prometheus** — low volume (37/mo). Tests whether it's worth it at smaller scale.
- **cli/cli** — mid volume (64/mo), largest scored sample (449 issues). Where confidence calibration broke.

Add any repo: `python -m triage_eval.fetch --repo owner/name --n 500`

## License

MIT. Data pulled at runtime from the public GitHub API; nothing copyrighted is vendored.
