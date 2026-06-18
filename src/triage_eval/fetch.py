"""Pull closed issues from a repo via the GitHub REST API -> data/{repo}.jsonl.

The maintainers' applied labels ARE the ground truth. We also detect duplicates:
GitHub doesn't expose a structured "duplicate-of" field, so we use the conventional
signal — an issue closed with a comment/body referencing "duplicate of #N" or the
`duplicate` label. That gives us labeled positives for the dup-precision metric.

Read-only. A free personal-access token lifts the rate limit to 5000 req/hr.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterator

import requests

from .env import load_env

load_env()

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
API = "https://api.github.com"
DUP_RE = re.compile(r"duplicate\s+of\s+#(\d+)", re.I)


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _get(url: str, params: dict | None = None) -> requests.Response:
    for attempt in range(5):
        r = requests.get(url, headers=_headers(), params=params, timeout=30)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - time.time(), 1)
            print(f"  rate-limited, sleeping {wait:.0f}s", file=sys.stderr)
            time.sleep(min(wait, 120))
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def fetch_issues(repo: str, n: int) -> Iterator[dict]:
    """Yield up to n closed *issues* (PRs excluded via search API)."""
    page, got = 1, 0
    while got < n:
        print(f"  page {page} ({got}/{n})...", file=sys.stderr)
        r = _get(
            f"{API}/search/issues",
            params={"q": f"repo:{repo} type:issue state:closed",
                    "per_page": 100, "page": page,
                    "sort": "created", "order": "desc"},
        )
        items = r.json().get("items", [])
        if not items:
            break
        for issue in items:
            yield issue
            got += 1
            if got >= n:
                break
        page += 1


def detect_duplicate(issue: dict, repo: str) -> int | None:
    """Return the referenced issue number if this looks like a duplicate, else None."""
    labels = [l["name"].lower() for l in issue.get("labels", [])]
    body = issue.get("body") or ""
    m = DUP_RE.search(body)
    if m:
        return int(m.group(1))
    if "duplicate" in labels and issue.get("comments", 0) > 0:
        owner, name = repo.split("/")
        c = _get(issue["comments_url"]).json()
        for comment in c:
            mm = DUP_RE.search(comment.get("body") or "")
            if mm:
                return int(mm.group(1))
        return -1  # labeled duplicate but no parseable target
    return None


def to_record(issue: dict, repo: str) -> dict:
    raw_labels = [l["name"] for l in issue.get("labels", [])]
    return {
        "repo": repo,
        "number": issue["number"],
        "title": issue["title"],
        "body": (issue.get("body") or "")[:6000],
        "raw_labels": raw_labels,
        "duplicate_of": detect_duplicate(issue, repo),
        "created_at": issue["created_at"],
        "url": issue["html_url"],
    }


def _fetch_total_closed_issues(owner: str, name: str) -> int | None:
    """Return total closed issue count via the Search API (excludes PRs)."""
    try:
        r = _get(
            f"{API}/search/issues",
            params={"q": f"repo:{owner}/{name} type:issue state:closed", "per_page": 1},
        )
        return r.json().get("total_count")
    except Exception:
        return None


def _fetch_repo_created_at(owner: str, name: str) -> float | None:
    """Return repo creation timestamp in seconds since epoch."""
    try:
        r = _get(f"{API}/repos/{owner}/{name}")
        created = r.json().get("created_at", "")
        if created:
            return time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        pass
    return None


def compute_repo_stats(repo: str, records: list[dict]) -> dict:
    owner, name = repo.split("/")
    n_fetched = len(records)

    total_closed = _fetch_total_closed_issues(owner, name)
    repo_created_ts = _fetch_repo_created_at(owner, name)
    now_ts = time.time()

    if total_closed is not None and repo_created_ts is not None:
        repo_age_months = max((now_ts - repo_created_ts) / (86400 * 30.44), 1)
        avg_per_month = round(total_closed / repo_age_months, 1)
        repo_created = time.strftime("%Y-%m-%d", time.gmtime(repo_created_ts))
        today = time.strftime("%Y-%m-%d", time.gmtime(now_ts))
        return {
            "repo": repo,
            "n_fetched": n_fetched,
            "total_closed_issues": total_closed,
            "earliest": repo_created,
            "latest": today,
            "span_days": round((now_ts - repo_created_ts) / 86400),
            "avg_issues_per_month": avg_per_month,
        }

    dates = []
    for r in records:
        try:
            d = time.strptime(r["created_at"], "%Y-%m-%dT%H:%M:%SZ")
            dates.append(time.mktime(d))
        except (KeyError, ValueError):
            continue
    if not dates:
        return {}
    earliest = min(dates)
    latest = max(dates)
    span_days = max((now_ts - earliest) / 86400, 1)
    span_months = span_days / 30.44
    avg_per_month = round(n_fetched / span_months, 1)
    return {
        "repo": repo,
        "n_fetched": n_fetched,
        "earliest": time.strftime("%Y-%m-%d", time.gmtime(earliest)),
        "latest": time.strftime("%Y-%m-%d", time.gmtime(latest)),
        "span_days": round(span_days),
        "avg_issues_per_month": avg_per_month,
    }


def save_repo_stats(stats: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    p = RESULTS_DIR / "repo_stats.json"
    existing = json.loads(p.read_text()) if p.exists() else {}
    existing[stats["repo"]] = stats
    p.write_text(json.dumps(existing, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch closed issues -> data/{repo}.jsonl")
    ap.add_argument("--repo", required=True, help="owner/name, e.g. grafana/grafana")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--workers", type=int, default=8, help="parallel workers for to_record (default 8)")
    args = ap.parse_args()

    if not os.environ.get("GITHUB_TOKEN"):
        print("warning: no GITHUB_TOKEN set, you'll hit the 60 req/hr limit fast",
              file=sys.stderr)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / f"{args.repo.replace('/', '__')}.jsonl"
    print(f"  fetching issue list...", file=sys.stderr)
    raw_issues = list(fetch_issues(args.repo, args.n))
    print(f"  {len(raw_issues)} issues fetched, processing with {args.workers} workers...", file=sys.stderr)
    records = []
    n_dups = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool, out.open("w") as f:
        for rec in pool.map(lambda i: to_record(i, args.repo), raw_issues):
            records.append(rec)
            if rec["duplicate_of"] is not None:
                n_dups += 1
            f.write(json.dumps(rec) + "\n")
            if len(records) % 50 == 0:
                print(f"  {len(records)} processed...", file=sys.stderr)
    print(f"wrote {len(records)} issues ({n_dups} duplicates) -> {out}")

    stats = compute_repo_stats(args.repo, records)
    if stats:
        save_repo_stats(stats)
        total_note = (f"  total closed: {stats['total_closed_issues']:,}"
                      if stats.get("total_closed_issues") else "")
        print(
            f"repo stats: {stats['n_fetched']} fetched over {stats['span_days']} days "
            f"({stats['earliest']} to {stats['latest']}) "
            f"= {stats['avg_issues_per_month']} issues/month avg (lifetime)"
            + (f"\n{total_note}" if total_note else "")
        )


if __name__ == "__main__":
    main()
