import json

from jobwatch.engine import CompanyResult
from jobwatch.models import Job
from jobwatch.report import format_report, write_report


def _job(job_id):
    return Job(
        company="Acme", job_id=job_id, title="Engineer", url=f"https://acme.example/{job_id}"
    )


def test_headline_counts_statuses_that_need_attention():
    results = [
        CompanyResult("Acme", "ok", [_job("1")], 5),
        CompanyResult("Beta", "failed", [], 0, "boom"),
        CompanyResult("Gamma", "blocked", [], 0, "HTTP 406"),
        CompanyResult("Delta", "blocked", [], 0, "HTTP 429"),
        CompanyResult("Epsilon", "suspicious", [], 30, "scheme change"),
    ]
    headline = format_report(results).splitlines()[0]
    assert "5 companies, 1 new jobs" in headline
    assert "1 failed" in headline
    assert "2 blocked" in headline
    assert "1 suspicious" in headline


def test_headline_stays_quiet_when_every_company_succeeded():
    results = [
        CompanyResult("Acme", "ok", [_job("1")], 5),
        CompanyResult("Beta", "seeded", [], 40),
    ]
    headline = format_report(results).splitlines()[0]
    assert headline == "Job Posting Watcher — 2 companies, 1 new jobs"


def test_headline_omits_statuses_with_no_companies():
    # A run with only blocks must not read "0 failed, 1 blocked, 0 suspicious".
    results = [CompanyResult("Acme", "blocked", [], 0, "HTTP 406")]
    headline = format_report(results).splitlines()[0]
    assert "1 blocked" in headline
    assert "failed" not in headline
    assert "suspicious" not in headline


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


def _entry(company, status="ok", total=1):
    return CompanyResult(company, status, [], total)


def test_a_later_single_company_run_does_not_erase_the_days_report(tmp_path):
    """The bug this exists for: a morning run writes every company, an
    afternoon `--company X` run replaces the file with just X, and the rest of
    the day's record is gone."""
    write_report([_entry("Stripe"), _entry("Figma"), _entry("Ramp")], output_dir=tmp_path)
    path = write_report([_entry("Stripe", total=99)], output_dir=tmp_path)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [e["company"] for e in saved] == ["Stripe", "Figma", "Ramp"]
    # The company that ran again is updated, not duplicated.
    assert sum(e["company"] == "Stripe" for e in saved) == 1
    assert next(e for e in saved if e["company"] == "Stripe")["total_jobs"] == 99


def test_a_company_seen_only_in_the_later_run_is_appended(tmp_path):
    write_report([_entry("Stripe")], output_dir=tmp_path)
    path = write_report([_entry("Anduril")], output_dir=tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [e["company"] for e in saved] == ["Stripe", "Anduril"]


def test_new_jobs_from_the_earlier_run_survive(tmp_path):
    job = Job(company="Figma", job_id="1", title="Engineer", url="https://example.com/1")
    write_report([CompanyResult("Figma", "ok", [job], 1)], output_dir=tmp_path)
    path = write_report([_entry("Stripe")], output_dir=tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    figma = next(e for e in saved if e["company"] == "Figma")
    assert [j["job_id"] for j in figma["new_jobs"]] == ["1"]


def test_an_unreadable_existing_report_does_not_lose_the_finished_run(tmp_path):
    from datetime import date

    (tmp_path / f"{date.today().isoformat()}.json").write_text("{not json", encoding="utf-8")
    path = write_report([_entry("Stripe")], output_dir=tmp_path)
    assert [e["company"] for e in json.loads(path.read_text(encoding="utf-8"))] == ["Stripe"]


def test_an_existing_file_that_is_not_a_list_is_replaced(tmp_path):
    from datetime import date

    (tmp_path / f"{date.today().isoformat()}.json").write_text('{"company": "x"}', encoding="utf-8")
    path = write_report([_entry("Stripe")], output_dir=tmp_path)
    assert [e["company"] for e in json.loads(path.read_text(encoding="utf-8"))] == ["Stripe"]
