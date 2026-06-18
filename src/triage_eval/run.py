"""Run triage over fetched issues -> results/{repo}__{provider}.jsonl.

Skips issues with no usable ground-truth category (process-only labels), caches
per-issue so a re-run after a crash doesn't re-pay for completed predictions.
"""
from __future__ import annotations
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
             limit: int | None, workers: int = 5) -> Path:
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
    pending = [r for r in scored if r["number"] not in done]

    mode = "a" if done else "w"
    lock = threading.Lock()
    n_new = 0
    total_input = total_output = 0
    latencies: list[float] = []
    batch_start = time.perf_counter()

    def _process(rec: dict) -> dict | None:
        t0 = time.perf_counter()
        try:
            pred = triage_issue(provider, rec)
        except Exception as e:
            print(f"  issue #{rec['number']} failed: {e}", file=sys.stderr)
            return None
        pred["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
        return pred

    with out.open(mode) as f, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_process, rec): rec for rec in pending}
        for future in as_completed(futures):
            pred = future.result()
            if pred is None:
                continue
            with lock:
                latencies.append(pred["elapsed_ms"])
                total_input += pred.get("input_tokens", 0)
                total_output += pred.get("output_tokens", 0)
                f.write(json.dumps(pred) + "\n")
                f.flush()
                n_new += 1
                if n_new % 25 == 0:
                    print(f"  {n_new} new predictions...", file=sys.stderr)

    batch_elapsed = time.perf_counter() - batch_start
    model_name = getattr(provider, "model", "mock")
    run_cost = cost_usd(model_name, total_input, total_output)

    avg_s = (sum(latencies) / len(latencies) / 1000) if latencies else 0
    min_s = min(latencies) / 1000 if latencies else 0
    max_s = max(latencies) / 1000 if latencies else 0
    print(
        f"{repo_slug}: {n_new} new ({len(done)} cached) -> {out}\n"
        f"  time : {batch_elapsed:.1f}s total  |  {avg_s:.2f}s avg/issue  "
        f"(min {min_s:.2f}s  max {max_s:.2f}s)  workers={workers}\n"
        f"  cost : tokens in={total_input:,} out={total_output:,}  ${run_cost:.4f}"
    )
    return out, {
        "input_tokens": total_input, "output_tokens": total_output,
        "cost_usd": round(run_cost, 6), "model": model_name,
        "batch_seconds": round(batch_elapsed, 1),
        "avg_seconds_per_issue": round(avg_s, 3),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Run LLM triage over fetched issues")
    ap.add_argument("--provider", choices=["claude", "openai", "mock"], default="mock")
    ap.add_argument("--model", default=None)
    ap.add_argument("--repo", default=None, help="limit to one data file (owner__name)")
    ap.add_argument("--limit", type=int, default=None, help="cap issues per repo")
    ap.add_argument("--workers", type=int, default=5, help="parallel API workers (default 5)")
    args = ap.parse_args()

    files = sorted(DATA_DIR.glob("*.jsonl"))
    if args.repo:
        files = [f for f in files if f.stem == args.repo.replace("/", "__")]
    if not files:
        sys.exit("no data files in data/ — run triage_eval.fetch first")

    all_costs = []
    for rf in files:
        _, cost_info = run_repo(rf, args.provider, args.model, args.limit, args.workers)
        cost_info["repo"] = rf.stem.replace("__", "/")
        all_costs.append(cost_info)

    costs_path = RESULTS_DIR / "costs.json"
    existing = json.loads(costs_path.read_text()) if costs_path.exists() else []
    existing.extend(all_costs)
    costs_path.write_text(json.dumps(existing, indent=2))
    total = sum(c["cost_usd"] for c in all_costs)
    total_time = sum(c.get("batch_seconds", 0) for c in all_costs)
    print(f"\ntotal cost this run: ${total:.4f}  |  total time: {total_time:.1f}s")


if __name__ == "__main__":
    main()
