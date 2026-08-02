from __future__ import annotations

from jobwatch.models import Job


def apply_filters(jobs: list[Job]) -> list[Job]:
    """Phase 2 hook: role-fit filtering (seniority allow/deny lists) will be
    added here. It must stay a report-time filter — snapshots always store
    every job a company posts, regardless of fit, so widening this filter
    later does not lose history."""
    return list(jobs)
