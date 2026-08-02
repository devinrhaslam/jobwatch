from jobwatch.filters import apply_filters
from jobwatch.models import Job


def test_apply_filters_is_currently_a_pass_through():
    jobs = [
        Job(company="Acme", job_id="1", title="Senior Software Engineer", url="https://x/1")
    ]
    assert apply_filters(jobs) == jobs


def test_apply_filters_returns_a_new_list_not_the_same_object():
    # The only contract this stub can meaningfully pin: callers must be able
    # to widen the filter later without accidentally mutating the caller's list.
    jobs = [
        Job(company="Acme", job_id="1", title="Senior Software Engineer", url="https://x/1")
    ]
    assert apply_filters(jobs) is not jobs
