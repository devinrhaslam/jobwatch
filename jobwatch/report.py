from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from jobwatch.engine import CompanyResult

DEFAULT_OUTPUT_DIR = Path("output")


# Statuses worth counting in the header. Ordered worst-first so the summary
# leads with the status that most needs acting on.
PROBLEM_STATUSES = ("failed", "blocked", "suspicious")


def _headline(results: list[CompanyResult]) -> str:
    """Summarise the run in one line, naming any statuses that need attention.

    Counting these up front is the difference between noticing a bad run and
    not: the per-company lines are the only other place a failure appears, and
    three FAILED among a hundred companies scrolls past unread. A clean run says
    nothing extra, so the counts only ever appear when they mean something.
    """
    total_new = sum(len(r.new_jobs) for r in results)
    header = f"Job Posting Watcher — {len(results)} companies, {total_new} new jobs"
    counts = [
        (status, sum(1 for r in results if r.status == status))
        for status in PROBLEM_STATUSES
    ]
    flagged = [f"{count} {status}" for status, count in counts if count]
    if flagged:
        header += f" ({', '.join(flagged)})"
    return header


def format_report(results: list[CompanyResult]) -> str:
    lines = [_headline(results), ""]
    for result in results:
        detail_part = f": {result.detail}" if result.detail else ""
        # A successful run can still carry a detail — most often that pagination
        # was truncated. Dropping it here would hide an incomplete result behind
        # a line that reads like a clean one.
        if result.status == "ok" and result.new_jobs:
            lines.append(f"## {result.company} — {len(result.new_jobs)} new{detail_part}")
            for job in result.new_jobs:
                loc = f" ({job.location})" if job.location else ""
                lines.append(f"  - {job.title}{loc}\n    {job.url}")
        elif result.status == "ok":
            lines.append(f"## {result.company} — no new jobs{detail_part}")
        elif result.status == "seeded":
            lines.append(
                f"## {result.company} — seeded {result.total_jobs} jobs, no alerts{detail_part}"
            )
        elif result.status == "blocked":
            lines.append(f"## {result.company} — BLOCKED{detail_part}")
        elif result.status == "failed":
            lines.append(f"## {result.company} — FAILED{detail_part}")
        elif result.status == "suspicious":
            lines.append(f"## {result.company} — SUSPICIOUS{detail_part}")
        else:
            lines.append(
                f"## {result.company} — UNRECOGNIZED STATUS '{result.status}'{detail_part}"
            )
    return "\n".join(lines)


def write_report(
    results: list[CompanyResult], output_dir: Path = DEFAULT_OUTPUT_DIR
) -> Path:
    """Write the day's report, merging into one already written today.

    The file is named for the date, so a later `--company X` run used to replace
    the whole day's record with a single company. That is how a full run's 807
    jobs were lost: the morning run wrote them, an afternoon one-company run
    overwrote the file, and the only surviving copy of what the other 240
    companies reported was a filtered export made by hand.

    Merging keeps every company the day has seen. A company that appears in this
    run replaces its earlier entry — the newer read is the truer one — and the
    order of first appearance is preserved so the file still reads like the run
    that produced it.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{date.today().isoformat()}.json"
    payload = [
        {
            "company": r.company,
            "status": r.status,
            "total_jobs": r.total_jobs,
            "detail": r.detail,
            "new_jobs": [asdict(job) for job in r.new_jobs],
        }
        for r in results
    ]
    path.write_text(
        json.dumps(_merged_with_existing(path, payload), indent=2), encoding="utf-8"
    )
    return path


def _merged_with_existing(path: Path, payload: list[dict]) -> list[dict]:
    """`payload` laid over whatever the file already holds for today.

    An unreadable or unexpected existing file is left out of the merge rather
    than allowed to fail the write: losing the earlier half of a day's report is
    bad, but losing the run that just finished is worse.
    """
    if not path.exists():
        return payload
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return payload
    if not isinstance(existing, list):
        return payload

    merged: dict[str, dict] = {}
    for entry in existing:
        if isinstance(entry, dict) and isinstance(entry.get("company"), str):
            merged[entry["company"]] = entry
    for entry in payload:
        merged[entry["company"]] = entry
    return list(merged.values())
