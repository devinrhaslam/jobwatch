from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from jobwatch.engine import CompanyResult

DEFAULT_OUTPUT_DIR = Path("output")


def format_report(results: list[CompanyResult]) -> str:
    total_new = sum(len(r.new_jobs) for r in results)
    lines = [f"Job Posting Watcher — {len(results)} companies, {total_new} new jobs", ""]
    for result in results:
        detail_part = f": {result.detail}" if result.detail else ""
        if result.status == "ok" and result.new_jobs:
            lines.append(f"## {result.company} — {len(result.new_jobs)} new")
            for job in result.new_jobs:
                loc = f" ({job.location})" if job.location else ""
                lines.append(f"  - {job.title}{loc}\n    {job.url}")
        elif result.status == "ok":
            lines.append(f"## {result.company} — no new jobs")
        elif result.status == "seeded":
            lines.append(f"## {result.company} — seeded {result.total_jobs} jobs, no alerts")
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
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
