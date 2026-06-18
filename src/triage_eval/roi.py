"""Convert triage accuracy into the numbers a manager budgets against.

Assumptions are explicit and overridable — the post should state them out loud.
The logic: an automatable decision is one the LLM gets right AND is confident enough
to act on without review. We model a review policy where the LLM auto-applies on
agreement and a human only checks a sampled fraction, then compare against the
all-human baseline.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ROIAssumptions:
    minutes_per_triage: float = 4.0     # human time to read + label one issue
    issues_per_month: int = 400         # incoming volume for the team
    loaded_hourly_rate: float = 75.0    # fully-loaded eng cost, USD/hr
    review_fraction: float = 0.20       # share of auto-labeled issues a human spot-checks
    review_minutes: float = 1.0         # time for a quick spot-check


def roi(accuracy: float, api_cost_usd: float = 0.0,
        a: ROIAssumptions = ROIAssumptions(),
        cost_per_issue_usd: float = 0.0) -> dict:
    """Return monthly minutes and dollars saved at a given label accuracy."""
    baseline_min = a.issues_per_month * a.minutes_per_triage

    wrong = a.issues_per_month * (1 - accuracy)
    right = a.issues_per_month * accuracy
    llm_human_min = (wrong * a.minutes_per_triage
                     + right * a.review_fraction * a.review_minutes)

    saved_min = baseline_min - llm_human_min
    saved_pct = saved_min / baseline_min if baseline_min else 0.0
    saved_usd = saved_min / 60 * a.loaded_hourly_rate
    saved_usd_year = saved_usd * 12
    net_usd_year = saved_usd_year - api_cost_usd * 12

    human_cost_per_issue = a.minutes_per_triage / 60 * a.loaded_hourly_rate
    llm_cost_per_issue = cost_per_issue_usd
    saved_per_correct = human_cost_per_issue - llm_cost_per_issue
    roi_multiplier = round(human_cost_per_issue / llm_cost_per_issue) if llm_cost_per_issue else None

    return {
        "accuracy": round(accuracy, 4),
        "baseline_minutes_per_month": round(baseline_min),
        "with_llm_minutes_per_month": round(llm_human_min),
        "minutes_saved_per_month": round(saved_min),
        "hours_saved_per_month": round(saved_min / 60, 1),
        "pct_time_saved": round(saved_pct, 3),
        "usd_saved_per_month": round(saved_usd),
        "usd_saved_per_year": round(saved_usd_year),
        "api_cost_usd_per_run": round(api_cost_usd, 4),
        "net_usd_saved_per_year": round(net_usd_year),
        "human_cost_per_issue_usd": round(human_cost_per_issue, 4),
        "llm_cost_per_issue_usd": round(llm_cost_per_issue, 5),
        "saved_per_correct_issue_usd": round(saved_per_correct, 4),
        "roi_multiplier": roi_multiplier,
        "assumptions": a.__dict__,
    }


if __name__ == "__main__":
    import sys
    acc = float(sys.argv[1]) if len(sys.argv) > 1 else 0.82
    import json
    print(json.dumps(roi(acc), indent=2))
