# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (with all optional deps)
pip install -e ".[claude,openai,plot]"

# Or use make targets:
make install
make fetch          # pull 500 issues from grafana/grafana and prometheus/prometheus
make run-mock       # free offline triage (no API key needed)
make run-claude     # triage with claude-sonnet-4-6
make run-openai     # triage with gpt-4o
make score          # score + model-vs-model comparison table
make post           # generate LinkedIn post + chart
make serve          # open dashboard at http://localhost:8000/web/
make clean          # remove all data, results, and generated files
```

Individual module invocations:
```bash
python -m triage_eval.fetch --repo owner/name --n 500
python -m triage_eval.run --provider mock|claude|openai [--model MODEL] [--repo owner__name] [--limit N]
python -m triage_eval.score [--compare] [--json]
python scripts/make_post.py [--chart]
python scripts/serve.py
```

No test suite is present; validate end-to-end with `make run-mock && make score`.

## Architecture

The pipeline is linear: **fetch → run → score**.

```
data/{owner}__{name}.jsonl          # ground truth from GitHub API (fetch.py)
results/{repo}__{provider}-{model}.jsonl  # per-issue predictions (run.py)
results/scores.json                 # aggregated metrics (score.py)
```

**Key modules in `src/triage_eval/`:**

- `fetch.py` — GitHub API → `data/*.jsonl`. Each record has `number`, `title`, `body`, `raw_labels`, `duplicate_of`.
- `taxonomy.py` — Normalizes messy repo labels to a fixed taxonomy: `["bug", "feature", "question", "docs", "ci/build", "security", "other"]`. Also handles priority normalization and process-label filtering. **Edit `CATEGORY_RULES` here when adding new repos.**
- `providers.py` — Defines a `Provider` protocol with `complete(system, user) -> str`. Three implementations: `ClaudeProvider`, `OpenAIProvider`, `MockProvider` (keyword heuristic, no API needed). `parse_response()` extracts JSON from model output.
- `triage.py` — Builds the prompt per issue and calls `provider.complete()`.
- `run.py` — Orchestrates issue → prediction loop with per-issue caching (safe to resume after crash). Output filename format: `{repo_slug}__{provider.name}-{model}.jsonl`.
- `score.py` — Computes accuracy, macro F1, confusion matrix, priority accuracy, duplicate precision/recall, and ROI. Writes `results/scores.json` (consumed by the web dashboard).
- `roi.py` — Converts accuracy to hours/dollars saved.
- `env.py` — Loads `.env` file into `os.environ` automatically (called at import time in `providers.py`).

**Web dashboard** (`web/index.html`) is a standalone HTML file with no build step. It reads `results/scores.json` when available, otherwise renders bundled sample data.

## Environment

Copy `.env.example` to `.env` and fill in:
```
GITHUB_TOKEN=ghp_...         # lifts rate limit to 5000 req/hr
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=...          # optional, for compatible APIs
```
