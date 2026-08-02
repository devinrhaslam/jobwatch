from jobwatch.models import CompanyConfig, FetchMode, Job


def test_job_stable_id_is_deterministic():
    id1 = Job.stable_id("Software Engineer", "Remote", "https://acme.example/1")
    id2 = Job.stable_id("Software Engineer", "Remote", "https://acme.example/1")
    assert id1 == id2


def test_job_stable_id_differs_for_different_titles():
    id1 = Job.stable_id("Software Engineer", "Remote", "https://acme.example/1")
    id2 = Job.stable_id("Staff Software Engineer", "Remote", "https://acme.example/1")
    assert id1 != id2


def test_company_config_defaults_wait_for_selector_to_none():
    config = CompanyConfig(
        name="Acme", career_url="https://acme.example", fetch_mode=FetchMode.STATIC
    )
    assert config.wait_for_selector is None


def test_company_config_rendered_requires_wait_for_selector():
    import pytest

    with pytest.raises(ValueError, match="wait_for_selector is required"):
        CompanyConfig(
            name="Acme",
            career_url="https://acme.example",
            fetch_mode=FetchMode.RENDERED,
        )


def test_company_config_rendered_rejects_empty_string_wait_for_selector():
    import pytest

    with pytest.raises(ValueError, match="wait_for_selector is required"):
        CompanyConfig(
            name="Acme",
            career_url="https://acme.example",
            fetch_mode=FetchMode.RENDERED,
            wait_for_selector="",
        )


def test_company_config_rendered_accepts_wait_for_selector():
    config = CompanyConfig(
        name="Acme",
        career_url="https://acme.example",
        fetch_mode=FetchMode.RENDERED,
        wait_for_selector=".job-listing",
    )
    assert config.wait_for_selector == ".job-listing"
