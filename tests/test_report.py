import json

from jobwatch.engine import CompanyResult
from jobwatch.models import Job
from jobwatch.report import format_report, write_report


def _job(job_id):
    return Job(
        company="Acme", job_id=job_id, title="Engineer", url=f"https://acme.example/{job_id}"
    )


def test_format_report_lists_new_jobs_with_links():
    results = [CompanyResult("Acme", "ok", [_job("1")], 5)]
    text = format_report(results)
    assert "Acme" in text
    assert "https://acme.example/1" in text


def test_format_report_shows_seeded_companies_without_alerts():
    results = [CompanyResult("Acme", "seeded", [], 40)]
    text = format_report(results)
    assert "seeded 40 jobs" in text


def test_format_report_surfaces_failures_prominently():
    results = [CompanyResult("Acme", "failed", [], 0, "parser returned zero jobs")]
    text = format_report(results)
    assert "FAILED" in text
    assert "parser returned zero jobs" in text


def test_format_report_shows_blocked_companies_with_detail():
    results = [CompanyResult("Acme", "blocked", [], 0, "403 Forbidden")]
    text = format_report(results)
    assert "Acme" in text
    assert "BLOCKED" in text
    assert "403 Forbidden" in text


def test_format_report_shows_suspicious_companies_with_detail():
    results = [CompanyResult("Acme", "suspicious", [], 12, "job count dropped 90%")]
    text = format_report(results)
    assert "Acme" in text
    assert "SUSPICIOUS" in text
    assert "job count dropped 90%" in text


def test_format_report_blocked_without_detail_omits_the_word_none():
    results = [CompanyResult("Acme", "blocked", [], 0, None)]
    text = format_report(results)
    assert "BLOCKED" in text
    assert "None" not in text


def test_format_report_failed_without_detail_omits_the_word_none():
    results = [CompanyResult("Acme", "failed", [], 0, None)]
    text = format_report(results)
    assert "FAILED" in text
    assert "None" not in text


def test_format_report_suspicious_without_detail_omits_the_word_none():
    results = [CompanyResult("Acme", "suspicious", [], 12, None)]
    text = format_report(results)
    assert "SUSPICIOUS" in text
    assert "None" not in text


def test_format_report_shows_ok_companies_with_no_new_jobs():
    results = [CompanyResult("Acme", "ok", [], 5)]
    text = format_report(results)
    assert "Acme" in text
    assert "no new jobs" in text


def test_format_report_shows_unrecognized_status():
    results = [CompanyResult("Acme", "weird", [], 0, "something odd")]
    text = format_report(results)
    assert "Acme" in text
    assert "weird" in text
    assert "something odd" in text


def test_write_report_creates_dated_json_file(tmp_path):
    results = [CompanyResult("Acme", "ok", [_job("1")], 5)]
    path = write_report(results, output_dir=tmp_path)
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload[0]["company"] == "Acme"
    assert payload[0]["new_jobs"][0]["job_id"] == "1"


def test_seeded_result_surfaces_a_truncation_detail():
    # A truncated seed reads like a clean one unless the detail is shown.
    results = [
        CompanyResult("Acme", "seeded", [], 1200, "reached the 60-page pagination ceiling")
    ]
    text = format_report(results)
    assert "seeded 1200 jobs" in text
    assert "60-page pagination ceiling" in text


def test_ok_result_with_no_new_jobs_surfaces_a_detail():
    results = [CompanyResult("Acme", "ok", [], 40, "pagination stopped early")]
    assert "pagination stopped early" in format_report(results)


def test_ok_result_with_new_jobs_surfaces_a_detail():
    results = [
        CompanyResult("Acme", "ok", [_job("1")], 40, "pagination stopped early")
    ]
    text = format_report(results)
    assert "1 new" in text
    assert "pagination stopped early" in text


def test_clean_results_have_no_trailing_detail_separator():
    results = [CompanyResult("Acme", "seeded", [], 40)]
    assert format_report(results).rstrip().endswith("no alerts")
