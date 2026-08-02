from jobwatch.filters import apply_filters
from jobwatch.models import Job


def test_apply_filters_is_currently_a_pass_through():
    jobs = [
        Job(company="Acme", job_id="1", title="Senior Software Engineer", url="https://x/1")
    ]
    assert apply_filters(jobs) == jobs
