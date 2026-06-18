"""Normalize messy per-repo labels into a small, comparable taxonomy.

This is the step that decides whether your accuracy number means anything. Repos
use dozens of labels; many are process noise ("stale", "needs triage") rather than
a *category*. We map raw labels to a fixed set of categories and a priority, and
explicitly drop process labels so they don't pollute the comparison.

Edit CATEGORY_RULES to fit the repos you pull. Keep it transparent: the post should
be able to show this mapping.
"""
from __future__ import annotations
import re
from typing import Iterable, Optional

# Fixed target taxonomy for the classification metric.
CATEGORIES = ["bug", "feature", "question", "docs", "ci/build", "security", "other"]

# raw-label substring -> normalized category. First match wins, order matters.
CATEGORY_RULES: list[tuple[str, str]] = [
    (r"\bsecurity\b|vulnerab|cve", "security"),
    (r"(?:type|kind)/(?:bug|regression)|(?:^|/)regression$|\bbug\b|crash|broken|defect", "bug"),
    (r"(?:type|kind)/(?:feature|enhancement|ux)|feature|enhancement|proposal|feat\b", "feature"),
    (r"question|support|discussion|how[- ]?to", "question"),
    (r"(?:type|kind)/doc|docs?\b|documentation", "docs"),
    (r"ci\b|build|test|flake|pipeline|release", "ci/build"),
]

# Labels that describe process, not the issue itself. Excluded from scoring.
PROCESS_LABELS = re.compile(
    r"stale|wontfix|duplicate|needs[- ]?(triage|investigation|info|more)|"
    r"good[- ]?first[- ]?issue|help[- ]?wanted|on[- ]?hold|waiting|"
    r"keep[- ]?open|pinned|backport|triage/|"
    r"^internal$|^area/|^team/|^datasource/|^automated|^component/",
    re.I,
)

PRIORITY_RULES: list[tuple[str, str]] = [
    (r"crit|/p0|/p1\b|p0\b|p1\b|urgent|sev-?1|priority/critical|priority/high", "high"),
    (r"/p2\b|\bp2\b|medium|priority/medium|important|priority-2", "medium"),
    (r"/p[34]\b|\bp[34]\b|low|minor|priority/low|trivial|priority-3|priority-4", "low"),
]


def normalize_category(raw_labels: Iterable[str]) -> Optional[str]:
    """Collapse a raw label set to one category, or None if only process labels."""
    labels = [str(l).lower() for l in raw_labels]
    meaningful = [l for l in labels if not PROCESS_LABELS.search(l)]
    if not meaningful:
        return None
    for pattern, cat in CATEGORY_RULES:
        for lab in meaningful:
            if re.search(pattern, lab):
                return cat
    return "other"


def normalize_priority(raw_labels: Iterable[str]) -> Optional[str]:
    labels = [str(l).lower() for l in raw_labels]
    for pattern, pri in PRIORITY_RULES:
        for lab in labels:
            if re.search(pattern, lab):
                return pri
    return None  # most issues have no priority label; that's expected


def is_process_only(raw_labels: Iterable[str]) -> bool:
    labels = [str(l).lower() for l in raw_labels]
    return bool(labels) and all(PROCESS_LABELS.search(l) for l in labels)
