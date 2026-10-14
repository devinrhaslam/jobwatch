"""Recover a report for a run.py invocation that was killed before it finished.

run.py only calls write_report() once, at the very end, after every company
has been scraped AND the role filter has run. If the process dies before
that -- the machine sleeps, the terminal is killed, anything short of a clean
exit -- nothing is written under output/ for that run, even though most of
the work already happened.

Nothing scraped is actually lost, though: JsonSnapshotStore.save() writes each
company's state/<company>.json the moment that company finishes (one at a
time, run.py's INTER_COMPANY_DELAY_SECONDS apart), and jobwatch/state.py's
merge_snapshot() stamps a job's first_seen the instant it is first recorded
and never touches that field again. So any record whose first_seen falls
inside the dead run's time window *is* the new-job diff that run found,
still sitting in state/ -- this rebuilds CompanyResult objects from exactly
that, runs them through the same role filter a normal run would (reusing
state/filter_cache.json, so nothing already classified is re-sent, and
failing open exactly like run.py does if the classifier itself is down), and
writes the result under output/ with an explicit "-recovered" tag so it can
never be mistaken for a completed run's own dated file.

A company untouched by the dead run needs no recovery: its state simply
predates the crash, and it will be scraped cleanly next time, same as any
other day it wasn't reached.

Usage:
    python tools/recover_interrupted_run.py
        Auto-detects the most recent run's time window from state/*.json
        mtimes (the trailing cluster of saves with no gap between
        consecutive companies wider than GAP_THRESHOLD_SECONDS) and labels
        the output with today's date.

    python tools/recover_interrupted_run.py --since "2026-08-25T20:10:00-04:00" --until "2026-08-25T20:25:00-04:00" --label 2026-08-25
        Recovers an explicit window instead (local time, any ISO offset) and
        tags the output file with a specific label rather than today's date
        -- e.g. because the run was started the night before.

    python tools/recover_interrupted_run.py --verbose
        Also prints each job the role filter drops and why.

Writes output/<label>-recovered.json and output/<label>-recovered.txt. If
the role filter itself fails (a bad key, no credits, an outage) they hold
every new job unfiltered instead -- rerun tools/refilter_report.py on the
.json once the classifier works again, exactly as it does for a report that
run.py itself wrote unfiltered.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from jobwatch.engine import CompanyResult  # noqa: E402
from jobwatch.filters import apply_filters_by_group  # noqa: E402
from jobwatch.models import Job  # noqa: E402
from jobwatch.report import format_report  # noqa: E402

STATE_DIR = REPO_ROOT / "state"
OUTPUT_DIR = REPO_ROOT / "output"
FILTER_CACHE = STATE_DIR / "filter_cache.json"
# A company takes low single digits of seconds on a quiet run and up to
# run.py's COMPANY_TIMEOUT_SECONDS (600s by default) on a wedged one; treat
# anything under 15 minutes between two consecutive company saves as still
# the same run rather than two different ones.
GAP_THRESHOLD_SECONDS = 900
# Saves within a company can straddle a second boundary; a little slack on
# both ends of the detected window is cheap and avoids dropping an edge job.
WINDOW_SLACK_SECONDS = 1


def _state_files() -> list[Path]:
    return [p for p in sorted(STATE_DIR.glob("*.json")) if p != FILTER_CACHE]


def detect_run_window() -> tuple[float, float]:
    """Return the [start, end] POSIX-timestamp window of the most recent run."""
    mtimes = sorted((p.stat().st_mtime for p in _state_files()), reverse=True)
    if not mtimes:
        raise SystemExit(f"no state files found under {STATE_DIR}")
    end = start = mtimes[0]
    for t in mtimes[1:]:
        if start - t > GAP_THRESHOLD_SECONDS:
            break
        start = t
    return start, end


def recover(since: float, until: float) -> tuple[list[CompanyResult], list[str], list[str]]:
    results: list[CompanyResult] = []
    not_reached: list[str] = []
    seeded_like: list[str] = []
    lo, hi = since - WINDOW_SLACK_SECONDS, until + WINDOW_SLACK_SECONDS

    def in_window(record: dict) -> bool:
        try:
            ts = datetime.fromisoformat(record["first_seen"]).timestamp()
        except (KeyError, ValueError):
            return False
        return lo <= ts <= hi

    for path in _state_files():
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if not snapshot:
            continue
        company_name = next(iter(snapshot.values())).get("company", path.stem)
        touched = [record for record in snapshot.values() if in_window(record)]
        if not touched:
            not_reached.append(company_name)
            continue
        # engine.py: `reported_new = [] if is_seed_run else new_jobs` -- a seed
        # run deliberately reports nothing. is_seed_run itself isn't visible
        # here, but a company where *every* stored record landed in this one
        # run's window has no other explanation for an established tracker.
        all_new = len(touched) == len(snapshot)
        if all_new:
            seeded_like.append(company_name)
        new_jobs = (
            []
            if all_new
            else [
                Job(
                    company=record.get("company", company_name),
                    job_id=job_id,
                    title=record["title"],
                    url=record["url"],
                    location=record.get("location"),
                    posted_date=record.get("posted_date"),
                )
                for job_id, record in snapshot.items()
                if in_window(record)
            ]
        )
        results.append(
            CompanyResult(
                company=company_name,
                status="seeded" if all_new else "ok",
                new_jobs=new_jobs,
                total_jobs=len(snapshot),
                detail=None,
            )
        )
    return results, not_reached, seeded_like


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--since", help="ISO timestamp: window start. Default: auto-detected.")
    parser.add_argument("--until", help="ISO timestamp: window end. Default: auto-detected.")
    parser.add_argument(
        "--label", help="Output filename tag, e.g. 2026-08-25. Default: today's date."
    )
    parser.add_argument("--verbose", action="store_true", help="Print each dropped job and why.")
    args = parser.parse_args(argv)

    if bool(args.since) != bool(args.until):
        parser.error("--since and --until must be given together")
    if args.since and args.until:
        since, until = datetime.fromisoformat(args.since).timestamp(), datetime.fromisoformat(
            args.until
        ).timestamp()
    else:
        since, until = detect_run_window()

    fmt = "%Y-%m-%d %H:%M:%S %Z"
    print(
        f"Run window: {datetime.fromtimestamp(since).astimezone().strftime(fmt)} "
        f"-- {datetime.fromtimestamp(until).astimezone().strftime(fmt)}",
        file=sys.stderr,
    )
    label = args.label or datetime.fromtimestamp(until).astimezone().date().isoformat()

    results, not_reached, seeded_like = recover(since, until)
    pending = sum(len(r.new_jobs) for r in results)
    print(
        f"Recovered {len(results)} companies from that window ({pending} new jobs "
        f"before filtering); {len(not_reached)} companies were never reached.",
        file=sys.stderr,
    )
    if seeded_like:
        print(
            "Treating as seed runs (100% first-seen in this window, so nothing "
            f"reported, matching engine.py): {', '.join(seeded_like)}",
            file=sys.stderr,
        )
    if not_reached:
        print("Not reached: " + ", ".join(sorted(not_reached)), file=sys.stderr)

    def report_drop(job, verdict):
        print(f"  dropped: {job.company} — {job.title} — {verdict.reason}", file=sys.stderr)

    # Mirror run.py's own fail-open handling: the snapshots are already
    # merged -- they were merged live during the dead run, before this script
    # ever ran -- so a classifier failure here must not lose the jobs.
    try:
        filtered = apply_filters_by_group(
            [r.new_jobs for r in results],
            cache_path=FILTER_CACHE,
            on_drop=report_drop if args.verbose else None,
        )
        kept = sum(len(group) for group in filtered)
        results = [replace(r, new_jobs=group) for r, group in zip(results, filtered)]
        print(f"Kept {kept} of {pending} after the role filter.", file=sys.stderr)
    except Exception as exc:
        print(f"Role filter failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        print(
            "Reporting every new job unfiltered -- rerun tools/refilter_report.py "
            "on the .json this writes once the classifier works again.",
            file=sys.stderr,
        )

    rendered = format_report(results)
    print(rendered)

    json_out = OUTPUT_DIR / f"{label}-recovered.json"
    text_out = OUTPUT_DIR / f"{label}-recovered.txt"
    json_out.write_text(
        json.dumps(
            [
                {
                    "company": r.company,
                    "status": r.status,
                    "total_jobs": r.total_jobs,
                    "detail": r.detail,
                    "new_jobs": [vars(job) for job in r.new_jobs],
                }
                for r in results
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    text_out.write_text(rendered, encoding="utf-8")
    print(f"\nWrote {json_out} and {text_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
