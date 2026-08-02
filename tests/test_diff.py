from jobwatch.diff import find_new_jobs
from jobwatch.models import Job


def _job(job_id, title="Software Engineer"):
    return Job(
        company="Acme", job_id=job_id, title=title, url=f"https://acme.example/{job_id}"
    )


def test_find_new_jobs_returns_only_unseen_ids():
    jobs = [_job("1"), _job("2"), _job("3")]
    snapshot = {"1": {}, "3": {}}
    new_jobs = find_new_jobs(jobs, snapshot)
    assert [j.job_id for j in new_jobs] == ["2"]


def test_find_new_jobs_empty_snapshot_returns_all():
    jobs = [_job("1"), _job("2")]
    assert find_new_jobs(jobs, {}) == jobs


def test_find_new_jobs_no_jobs_returns_empty():
    assert find_new_jobs([], {"1": {}}) == []
