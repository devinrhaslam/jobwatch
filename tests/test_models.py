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


def test_company_config_rendered_xhr_requires_capture_response_url():
    import pytest

    with pytest.raises(ValueError, match="capture_response_url is required"):
        CompanyConfig(
            name="Acme",
            career_url="https://acme.example",
            fetch_mode=FetchMode.RENDERED_XHR,
        )


def test_company_config_rendered_xhr_does_not_require_wait_for_selector():
    # It waits on an API response rather than on markup, so demanding a
    # selector would be asking for something it never uses.
    config = CompanyConfig(
        name="Acme",
        career_url="https://acme.example",
        fetch_mode=FetchMode.RENDERED_XHR,
        capture_response_url="/api/jobs",
    )
    assert config.wait_for_selector is None


def test_company_config_defaults_to_chromium():
    config = CompanyConfig(
        name="Acme", career_url="https://acme.example", fetch_mode=FetchMode.STATIC
    )
    assert config.browser_engine == "chromium"


def test_company_config_rejects_unknown_browser_engine():
    import pytest

    # A typo here would otherwise surface as an AttributeError deep inside the
    # fetch layer, long after the config that caused it.
    with pytest.raises(ValueError, match="unknown browser_engine"):
        CompanyConfig(
            name="Acme",
            career_url="https://acme.example",
            fetch_mode=FetchMode.STATIC,
            browser_engine="chrome",
        )
