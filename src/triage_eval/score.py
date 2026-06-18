"""Score predictions against maintainer ground truth.

Metrics:
  - label accuracy + macro precision/recall/F1 + confusion matrix
  - priority accuracy (where ground-truth priority exists)
  - duplicate precision/recall/F1
  - ROI (minutes & dollars), via roi.py

--compare lines up every results file per repo so you get the model-vs-model table
the second post is built around.
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from pathlib import Path

from sklearn.metrics import (confusion_matrix, precision_recall_fscore_support,
                             accuracy_score)

from .taxonomy import (CATEGORIES, normalize_category, normalize_priority)
from .providers import cost_usd
from .roi import roi, ROIAssumptions

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _load_repo_stats() -> dict:
    p = RESULTS_DIR / "repo_stats.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _truth_index(repo_slug: str) -> dict[int, dict]:
    recs = load_jsonl(DATA_DIR / f"{repo_slug}.jsonl")
    return {r["number"]: r for r in recs}


def _confidence_tiers(y_true: list, y_pred: list,
                      y_conf: list) -> dict | None:
    has_conf = [c for c in y_conf if c is not None]
    if not has_conf:
        return None

    tiers = {"high": (0.8, 1.01), "medium": (0.5, 0.8), "low": (0.0, 0.5)}
    result = {}
    conf_vals, correct_flags = [], []
    for t, p, c in zip(y_true, y_pred, y_conf):
        if c is None:
            continue
        conf_vals.append(c)
        correct_flags.append(1 if t == p else 0)

    for tier, (lo, hi) in tiers.items():
        idx = [i for i, c in enumerate(conf_vals) if lo <= c < hi]
        if not idx:
            result[tier] = {"n": 0, "accuracy": None, "avg_confidence": None}
            continue
        tier_correct = [correct_flags[i] for i in idx]
        tier_conf = [conf_vals[i] for i in idx]
        acc = sum(tier_correct) / len(tier_correct)
        avg_conf = sum(tier_conf) / len(tier_conf)
        result[tier] = {
            "n": len(idx),
            "accuracy": round(acc, 4),
            "avg_confidence": round(avg_conf, 4),
            "calibration_gap": round(avg_conf - acc, 4),
        }

    overall_acc = sum(correct_flags) / len(correct_flags) if correct_flags else 0
    overall_conf = sum(conf_vals) / len(conf_vals) if conf_vals else 0
    result["overall"] = {
        "avg_confidence": round(overall_conf, 4),
        "calibration_gap": round(overall_conf - overall_acc, 4),
    }
    return result


def score_file(results_path: Path) -> dict:
    # results filename: {owner__name}__{provider-model}.jsonl
    stem = results_path.stem
    repo_slug, tag = stem.split("__", 2)[0] + "__" + stem.split("__")[1], stem.split("__", 2)[2]
    truth = _truth_index(repo_slug)
    preds = load_jsonl(results_path)

    y_true, y_pred, y_conf = [], [], []
    pri_true, pri_pred = [], []
    dup_tp = dup_fp = dup_fn = 0
    total_input = total_output = 0

    for p in preds:
        total_input += p.get("input_tokens", 0)
        total_output += p.get("output_tokens", 0)
        gt = truth.get(p["number"])
        if not gt:
            continue
        gt_cat = normalize_category(gt["raw_labels"])
        if gt_cat is None:
            continue
        y_true.append(gt_cat)
        y_pred.append(p["category"] if p["category"] in CATEGORIES else "other")
        y_conf.append(p.get("confidence"))

        gt_pri = normalize_priority(gt["raw_labels"])
        if gt_pri and p.get("priority"):
            pri_true.append(gt_pri)
            pri_pred.append(p["priority"])

        gt_dup = gt.get("duplicate_of") is not None
        pred_dup = bool(p.get("is_duplicate"))
        if pred_dup and gt_dup:
            dup_tp += 1
        elif pred_dup and not gt_dup:
            dup_fp += 1
        elif (not pred_dup) and gt_dup:
            dup_fn += 1

    acc = accuracy_score(y_true, y_pred) if y_true else 0.0
    pr, rc, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=CATEGORIES, average="macro", zero_division=0
    ) if y_true else (0, 0, 0, 0)
    cm = (confusion_matrix(y_true, y_pred, labels=CATEGORIES).tolist()
          if y_true else [])

    pri_acc = (accuracy_score(pri_true, pri_pred) if pri_true else None)

    dup_p = dup_tp / (dup_tp + dup_fp) if (dup_tp + dup_fp) else None
    dup_r = dup_tp / (dup_tp + dup_fn) if (dup_tp + dup_fn) else None
    dup_f1 = (2 * dup_p * dup_r / (dup_p + dup_r)
              if dup_p and dup_r else None)

    confidence_tiers = _confidence_tiers(y_true, y_pred, y_conf)

    model_name = tag.split("-", 1)[1] if "-" in tag else tag
    run_cost = cost_usd(model_name, total_input, total_output)

    repo_name = repo_slug.replace("__", "/")
    repo_stats = _load_repo_stats().get(repo_name, {})
    measured_volume = repo_stats.get("avg_issues_per_month")
    roi_assumptions = ROIAssumptions(
        issues_per_month=int(measured_volume) if measured_volume else ROIAssumptions().issues_per_month
    )

    return {
        "repo": repo_name,
        "model": tag,
        "n_scored": len(y_true),
        "label_accuracy": round(acc, 4),
        "macro_precision": round(pr, 4),
        "macro_recall": round(rc, 4),
        "macro_f1": round(f1, 4),
        "priority_accuracy": (round(pri_acc, 4) if pri_acc is not None else None),
        "priority_n": len(pri_true),
        "dup_precision": (round(dup_p, 4) if dup_p is not None else None),
        "dup_recall": (round(dup_r, 4) if dup_r is not None else None),
        "dup_f1": (round(dup_f1, 4) if dup_f1 is not None else None),
        "dup_support": dup_tp + dup_fn,
        "confusion_labels": CATEGORIES,
        "confusion_matrix": cm,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cost_usd": round(run_cost, 4),
        "confidence_tiers": confidence_tiers,
        "repo_stats": repo_stats or None,
        "roi": roi(acc, run_cost, roi_assumptions),
    }


def print_report(s: dict) -> None:
    rs = s.get("repo_stats") or {}
    vol_note = (f"  [measured: {rs['avg_issues_per_month']} issues/mo avg, "
                f"{rs['earliest']} to {rs['latest']}]"
                if rs.get("avg_issues_per_month") else "  [volume: assumed 400/mo]")
    print(f"\n=== {s['repo']}  |  {s['model']}  |  n={s['n_scored']}{vol_note} ===")
    print(f"  label accuracy : {s['label_accuracy']:.1%}")
    print(f"  macro F1       : {s['macro_f1']:.3f}  "
          f"(P {s['macro_precision']:.3f} / R {s['macro_recall']:.3f})")
    if s["priority_accuracy"] is not None:
        print(f"  priority acc   : {s['priority_accuracy']:.1%}  (n={s['priority_n']})")
    if s["dup_precision"] is not None:
        print(f"  dup precision  : {s['dup_precision']:.1%}  "
              f"recall {s['dup_recall']:.1%}  (support={s['dup_support']})")
    r = s["roi"]
    print(f"  ROI            : {r['hours_saved_per_month']} h/mo saved "
          f"(~${r['usd_saved_per_year']:,}/yr) at {r['pct_time_saved']:.0%} time cut")
    if s.get("cost_usd") is not None:
        net = r.get("net_usd_saved_per_year")
        net_str = f"  net ~${net:,}/yr" if net is not None else ""
        print(f"  API cost       : ${s['cost_usd']:.4f} this run  "
              f"({s.get('input_tokens',0):,} in / {s.get('output_tokens',0):,} out tokens){net_str}")
    ct = s.get("confidence_tiers")
    if ct:
        print("  confidence     :"
              f"  high(≥0.8) {ct['high']['n']} issues → {ct['high']['accuracy']:.1%}"
              if ct.get("high") and ct["high"]["accuracy"] is not None else
              "  confidence     : (no high-confidence predictions)")
        for tier in ("medium", "low"):
            t = ct.get(tier, {})
            if t.get("n"):
                gap = t.get("calibration_gap", 0)
                sign = "+" if gap >= 0 else ""
                print(f"    {tier}({' <0.8' if tier=='medium' else '<0.5 '}): "
                      f"{t['n']} issues → {t['accuracy']:.1%}  "
                      f"(gap {sign}{gap:.2f})")


def compare_table(scores: list[dict]) -> str:
    by_repo = defaultdict(list)
    for s in scores:
        by_repo[s["repo"]].append(s)
    lines = ["\n## Model comparison\n"]
    for repo, rows in by_repo.items():
        lines.append(f"### {repo}\n")
        lines.append("| Model | n | Label acc | Macro F1 | Dup precision | Hrs saved/mo | API cost |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in sorted(rows, key=lambda x: -x["label_accuracy"]):
            dp = f"{s['dup_precision']:.0%}" if s["dup_precision"] is not None else "—"
            cost = f"${s['cost_usd']:.4f}" if s.get("cost_usd") is not None else "—"
            lines.append(
                f"| {s['model']} | {s['n_scored']} | {s['label_accuracy']:.1%} | "
                f"{s['macro_f1']:.3f} | {dp} | {s['roi']['hours_saved_per_month']} | {cost} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Score triage predictions")
    ap.add_argument("--compare", action="store_true",
                    help="emit a model-vs-model markdown table")
    ap.add_argument("--json", action="store_true", help="dump raw scores as JSON")
    args = ap.parse_args()

    files = sorted(RESULTS_DIR.glob("*.jsonl"))
    if not files:
        raise SystemExit("no results in results/ — run triage_eval.run first")

    scores = [score_file(f) for f in files]
    for s in scores:
        print_report(s)

    (RESULTS_DIR / "scores.json").write_text(json.dumps(scores, indent=2))
    if args.compare:
        table = compare_table(scores)
        print(table)
        (RESULTS_DIR / "comparison.md").write_text(table)
    if args.json:
        print(json.dumps(scores, indent=2))


if __name__ == "__main__":
    main()
