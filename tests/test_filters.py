import json

import pytest

from jobwatch.filters import (
    FilterError,
    Verdict,
    apply_filters,
    cache_key,
    classify,
    load_cache,
    save_cache,
)
from jobwatch.models import Job


def _job(job_id, title, company="Acme", location=None):
    return Job(
        company=company,
        job_id=job_id,
        title=title,
        url=f"https://{company.lower()}.example/{job_id}",
        location=location,
    )


class RecordingClassifier:
    """Stands in for the Claude call. Records every batch it was asked to judge."""

    def __init__(self, relevant_titles):
        self.relevant_titles = set(relevant_titles)
        self.batches = []

    def __call__(self, jobs):
        self.batches.append([j.title for j in jobs])
        return [
            Verdict(j.title in self.relevant_titles, "matched" if j.title in self.relevant_titles else "specialised track")
            for j in jobs
        ]


def test_keeps_only_jobs_the_classifier_marks_relevant(tmp_path):
    keep = _job("1", "Senior Software Engineer, Payments")
    drop = _job("2", "Data Engineer, Safeguards")
    classifier = RecordingClassifier(["Senior Software Engineer, Payments"])

    result = apply_filters(
        [keep, drop], cache_path=tmp_path / "cache.json", classifier=classifier
    )

    assert result == [keep]


def test_empty_job_list_never_calls_the_classifier(tmp_path):
    classifier = RecordingClassifier([])
    assert apply_filters([], cache_path=tmp_path / "cache.json", classifier=classifier) == []
    assert classifier.batches == []


def test_repeated_titles_are_classified_once_within_a_run(tmp_path):
    jobs = [_job("1", "Software Engineer"), _job("2", "Software Engineer")]
    classifier = RecordingClassifier(["Software Engineer"])

    result = apply_filters(
        jobs, cache_path=tmp_path / "cache.json", classifier=classifier
    )

    assert classifier.batches == [["Software Engineer"]]
    assert result == jobs


def test_cached_verdicts_are_not_reclassified_on_the_next_run(tmp_path):
    cache_path = tmp_path / "cache.json"
    job = _job("1", "Backend Engineer, Payments")

    first = RecordingClassifier(["Backend Engineer, Payments"])
    apply_filters([job], cache_path=cache_path, classifier=first)

    second = RecordingClassifier([])  # would drop it if consulted
    result = apply_filters([job], cache_path=cache_path, classifier=second)

    assert second.batches == []
    assert result == [job]


def test_same_title_at_different_companies_is_classified_separately(tmp_path):
    stripe = _job("1", "Staff Engineer", company="Stripe")
    other = _job("2", "Staff Engineer", company="Acme")
    classifier = RecordingClassifier(["Staff Engineer"])

    apply_filters(
        [stripe, other], cache_path=tmp_path / "cache.json", classifier=classifier
    )

    assert classifier.batches == [["Staff Engineer", "Staff Engineer"]]
    assert cache_key(stripe) != cache_key(other)


def test_classification_failure_propagates_rather_than_dropping_jobs(tmp_path):
    def failing(jobs):
        raise FilterError("boom")

    with pytest.raises(FilterError):
        apply_filters(
            [_job("1", "Software Engineer")],
            cache_path=tmp_path / "cache.json",
            classifier=failing,
        )


def test_failed_classification_does_not_write_a_partial_cache(tmp_path):
    cache_path = tmp_path / "cache.json"

    def failing(jobs):
        raise FilterError("boom")

    with pytest.raises(FilterError):
        apply_filters(
            [_job("1", "Software Engineer")], cache_path=cache_path, classifier=failing
        )

    assert not cache_path.exists()


def test_on_drop_receives_the_dropped_job_and_its_reason(tmp_path):
    drop = _job("1", "Engineering Manager, Search")
    classifier = RecordingClassifier([])
    dropped = []

    apply_filters(
        [drop],
        cache_path=tmp_path / "cache.json",
        classifier=classifier,
        on_drop=lambda job, verdict: dropped.append((job.title, verdict.reason)),
    )

    assert dropped == [("Engineering Manager, Search", "specialised track")]


def test_batches_are_capped_so_a_large_run_is_split(tmp_path, monkeypatch):
    monkeypatch.setattr("jobwatch.filters.BATCH_SIZE", 2)
    jobs = [_job(str(i), f"Software Engineer {i}") for i in range(5)]
    classifier = RecordingClassifier([j.title for j in jobs])

    apply_filters(jobs, cache_path=tmp_path / "cache.json", classifier=classifier)

    assert [len(batch) for batch in classifier.batches] == [2, 2, 1]


def test_classify_returns_a_verdict_for_every_job(tmp_path):
    jobs = [_job("1", "Software Engineer"), _job("2", "Data Engineer")]
    classifier = RecordingClassifier(["Software Engineer"])

    verdicts = classify(jobs, cache_path=tmp_path / "cache.json", classifier=classifier)

    assert verdicts[cache_key(jobs[0])].relevant is True
    assert verdicts[cache_key(jobs[1])].relevant is False


def test_cache_round_trips_through_disk(tmp_path):
    path = tmp_path / "cache.json"
    save_cache({"Acme|Software Engineer": Verdict(True, "backend IC role")}, path)
    assert load_cache(path) == {"Acme|Software Engineer": Verdict(True, "backend IC role")}


def test_corrupt_cache_is_ignored_rather_than_crashing_the_run(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_cache(path) == {}


def test_cache_entries_missing_a_verdict_are_skipped(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"Acme|X": {"reason": "no verdict field"}}), encoding="utf-8")
    assert load_cache(path) == {}


def test_missing_cache_file_is_treated_as_empty(tmp_path):
    assert load_cache(tmp_path / "absent.json") == {}


def test_cache_path_none_skips_disk_entirely(tmp_path):
    job = _job("1", "Software Engineer")
    classifier = RecordingClassifier(["Software Engineer"])

    apply_filters([job], cache_path=None, classifier=classifier)

    assert list(tmp_path.iterdir()) == []
