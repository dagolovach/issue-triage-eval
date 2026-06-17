"""Run triage over fetched issues -> results/{repo}__{provider}.jsonl.

Skips issues with no usable ground-truth category (process-only labels), caches
per-issue so a re-run after a crash doesn't re-pay for completed predictions.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from .providers import get_provider, cost_usd
from .taxonomy import normalize_category
from .triage import triage_issue

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def run_repo(repo_file: Path, provider_name: str, model: str | None,
             limit: int | None) -> Path:
    repo_slug = repo_file.stem
    provider = get_provider(provider_name, model)
    tag = f"{provider.name}-{getattr(provider, 'model', 'na')}".replace("/", "_")
    out = RESULTS_DIR / f"{repo_slug}__{tag}.jsonl"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    done: set[int] = set()
    if out.exists():
        done = {r["number"] for r in load_jsonl(out)}

    records = load_jsonl(repo_file)
    scored = [r for r in records if normalize_category(r["raw_labels"]) is not None]
    if limit:
        scored = scored[:limit]

    mode = "a" if done else "w"
    n_new = 0
    total_input = total_output = 0
    with out.open(mode) as f:
        for rec in scored:
            if rec["number"] in done:
                continue
            try:
                pred = triage_issue(provider, rec)
            except Exception as e:
                print(f"  issue #{rec['number']} failed: {e}", file=sys.stderr)
                continue
            total_input += pred.get("input_tokens", 0)
            total_output += pred.get("output_tokens", 0)
            f.write(json.dumps(pred) + "\n")
            f.flush()
            n_new += 1
            if n_new % 25 == 0:
                print(f"  {n_new} new predictions...", file=sys.stderr)

    model_name = getattr(provider, "model", "mock")
    run_cost = cost_usd(model_name, total_input, total_output)
    print(
        f"{repo_slug}: {n_new} new ({len(done)} cached) -> {out}  |  "
        f"tokens in={total_input:,} out={total_output:,}  cost=${run_cost:.4f}"
    )
    return out, {"input_tokens": total_input, "output_tokens": total_output,
                 "cost_usd": round(run_cost, 6), "model": model_name}


def main() -> None:
    ap = argparse.ArgumentParser(description="Run LLM triage over fetched issues")
    ap.add_argument("--provider", choices=["claude", "openai", "mock"], default="mock")
    ap.add_argument("--model", default=None)
    ap.add_argument("--repo", default=None, help="limit to one data file (owner__name)")
    ap.add_argument("--limit", type=int, default=None, help="cap issues per repo")
    args = ap.parse_args()

    files = sorted(DATA_DIR.glob("*.jsonl"))
    if args.repo:
        files = [f for f in files if f.stem == args.repo.replace("/", "__")]
    if not files:
        sys.exit("no data files in data/ — run triage_eval.fetch first")

    all_costs = []
    for rf in files:
        _, cost_info = run_repo(rf, args.provider, args.model, args.limit)
        cost_info["repo"] = rf.stem.replace("__", "/")
        all_costs.append(cost_info)

    costs_path = RESULTS_DIR / "costs.json"
    existing = json.loads(costs_path.read_text()) if costs_path.exists() else []
    existing.extend(all_costs)
    costs_path.write_text(json.dumps(existing, indent=2))
    total = sum(c["cost_usd"] for c in all_costs)
    print(f"\ntotal cost this run: ${total:.4f}")


if __name__ == "__main__":
    main()
