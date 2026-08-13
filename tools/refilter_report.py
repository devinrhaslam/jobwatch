"""Re-run the role filter over a report that was written unfiltered.

When the filter fails mid-run — no credits, an unset key, an API outage —
run.py deliberately prints every new job rather than losing them, because the
snapshots have already been written and those jobs will never be reported
again. That is the right call, but it can mean hundreds of unfiltered jobs
scrolling past.

The dated report under output/ holds every one of them, so the filter can be
applied afterwards and the report re-rendered as it should have looked.

Usage:
    python tools/refilter_report.py                     # newest report
    python tools/refilter_report.py output/2026-08-07.json
    python tools/refilter_report.py --verbose           # show dropped jobs too

Writes the filtered version alongside the original as
`<name>-filtered.json` and `<name>-filtered.txt`, leaving the unfiltered
record untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from jobwatch.engine import CompanyResult  # noqa: E402
from jobwatch.filters import apply_filters_by_group  # noqa: E402
from jobwatch.models import Job  # noqa: E402
from jobwatch.report import format_report  # noqa: E402

STATE_DIR = REPO_ROOT / "state"
OUTPUT_DIR = REPO_ROOT / "output"


def newest_report(output_dir: Path) -> Path:
    reports = sorted(output_dir.glob("*.json"))
    reports = [p for p in reports if not p.stem.endswith("-filtered")]
    if not reports:
        raise SystemExit(f"no reports found in {output_dir}")
    return max(reports, key=lambda p: p.stat().st_mtime)


def load_results(path: Path) -> list[CompanyResult]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    results = []
    for entry in raw:
        jobs = [
            Job(
                company=job.get("company", entry["company"]),
                job_id=str(job["job_id"]),
                title=job["title"],
                url=job["url"],
                location=job.get("location"),
                posted_date=job.get("posted_date"),
            )
            for job in entry.get("new_jobs") or []
        ]
        results.append(
            CompanyResult(
                company=entry["company"],
                status=entry["status"],
                new_jobs=jobs,
                total_jobs=entry.get("total_jobs", 0),
                detail=entry.get("detail"),
            )
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", nargs="?", help="Report to re-filter. Defaults to the newest.")
    parser.add_argument("--verbose", action="store_true", help="Print each dropped job and why.")
    args = parser.parse_args(argv)

    path = Path(args.report) if args.report else newest_report(OUTPUT_DIR)
    results = load_results(path)
    pending = sum(len(r.new_jobs) for r in results)
    print(f"Re-filtering {pending} jobs from {path.name}...", file=sys.stderr)
    if not pending:
        print("Nothing to filter.", file=sys.stderr)
        return 0

    def report_drop(job, verdict):
        print(f"  dropped: {job.company} — {job.title} — {verdict.reason}", file=sys.stderr)

    # Same cache the run uses, so anything classified before the failure is free
    # and this pass is itself cached for next time.
    filtered = apply_filters_by_group(
        [r.new_jobs for r in results],
        cache_path=STATE_DIR / "filter_cache.json",
        on_drop=report_drop if args.verbose else None,
    )
    kept = sum(len(group) for group in filtered)
    results = [replace(r, new_jobs=group) for r, group in zip(results, filtered)]
    print(f"Kept {kept} of {pending}.", file=sys.stderr)

    rendered = format_report(results)
    print(rendered)

    stem = path.with_suffix("").name
    json_out = path.with_name(f"{stem}-filtered.json")
    text_out = path.with_name(f"{stem}-filtered.txt")
    json_out.write_text(
        json.dumps(
            [
                {
                    "company": r.company,
                    "status": r.status,
                    "total_jobs": r.total_jobs,
                    "detail": r.detail,
                    "new_jobs": [vars(j) for j in r.new_jobs],
                }
                for r in results
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    text_out.write_text(rendered, encoding="utf-8")
    print(f"\nWrote {json_out.name} and {text_out.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
