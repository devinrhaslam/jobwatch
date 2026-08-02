from __future__ import annotations

from jobwatch.models import Job


def find_new_jobs(jobs: list[Job], snapshot: dict[str, dict]) -> list[Job]:
    return [job for job in jobs if job.job_id not in snapshot]
