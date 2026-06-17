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
from pathlib import Path
from typing import Iterator

import requests

from .env import load_env

load_env()

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
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
    """Yield up to n closed *issues* (PRs filtered out)."""
    owner, name = repo.split("/")
    page, got = 1, 0
    while got < n:
        r = _get(
            f"{API}/repos/{owner}/{name}/issues",
            params={"state": "closed", "per_page": 100, "page": page,
                    "sort": "created", "direction": "desc"},
        )
        batch = r.json()
        if not batch:
            break
        for issue in batch:
            if "pull_request" in issue:  # the issues endpoint also returns PRs
                continue
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch closed issues -> data/{repo}.jsonl")
    ap.add_argument("--repo", required=True, help="owner/name, e.g. grafana/grafana")
    ap.add_argument("--n", type=int, default=500)
    args = ap.parse_args()

    if not os.environ.get("GITHUB_TOKEN"):
        print("warning: no GITHUB_TOKEN set, you'll hit the 60 req/hr limit fast",
              file=sys.stderr)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / f"{args.repo.replace('/', '__')}.jsonl"
    n_written, n_dups = 0, 0
    with out.open("w") as f:
        for issue in fetch_issues(args.repo, args.n):
            rec = to_record(issue, args.repo)
            if rec["duplicate_of"] is not None:
                n_dups += 1
            f.write(json.dumps(rec) + "\n")
            n_written += 1
            if n_written % 50 == 0:
                print(f"  {n_written} issues...", file=sys.stderr)
    print(f"wrote {n_written} issues ({n_dups} duplicates) -> {out}")


if __name__ == "__main__":
    main()
