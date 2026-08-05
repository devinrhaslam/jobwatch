from jobwatch.models import FetchMode
from jobwatch.scrapers.linkedin import PAGE_SIZE, LinkedInScraper

# Trimmed from a real response; the class names and the urn/time attributes are
# the parts the parser depends on.
_CARD = """
<li>
  <div class="base-card job-search-card"
       data-entity-urn="urn:li:jobPosting:{job_id}">
    <a class="base-card__full-link"
       href="https://www.linkedin.com/jobs/view/some-slug-at-linkedin-{job_id}?position=1&amp;refId=abc%3D%3D&amp;trackingId=xyz%3D%3D">
      <span class="sr-only">{title}</span>
    </a>
    <h3 class="base-search-card__title">{title}</h3>
    <h4 class="base-search-card__subtitle">LinkedIn</h4>
    <span class="job-search-card__location">{location}</span>
    <time class="job-search-card__listdate" datetime="{posted}">1 day ago</time>
  </div>
</li>
"""


def _page(cards):
    return "<!DOCTYPE html>" + "".join(cards)


def _card(job_id="4398724241", title="Senior Software Engineer",
          location="Sunnyvale, CA", posted="2026-08-04"):
    return _CARD.format(job_id=job_id, title=title, location=location, posted=posted)


def test_parses_card_into_job():
    jobs = LinkedInScraper().parse(_page([_card()]))

    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == "LinkedIn"
    assert job.job_id == "4398724241"
    assert job.title == "Senior Software Engineer"
    assert job.location == "Sunnyvale, CA"
    assert job.posted_date == "2026-08-04"


def test_url_is_rebuilt_from_the_id_not_taken_from_the_href():
    # The card's href carries per-request tracking parameters, so reusing it
    # would give the same posting a different URL on every run — and
    # Job.stable_id hashes the URL.
    job = LinkedInScraper().parse(_page([_card()]))[0]

    assert job.url == "https://www.linkedin.com/jobs/view/4398724241"
    assert "trackingId" not in job.url
    assert "refId" not in job.url


def test_skips_cards_without_a_posting_urn_or_title():
    junk = '<li><div class="base-card">no urn here</div></li>'
    titleless = _CARD.format(
        job_id="99", title="", location="Remote", posted="2026-08-04"
    ).replace("<h3 class=\"base-search-card__title\"></h3>", "")

    jobs = LinkedInScraper().parse(_page([_card(), junk, titleless]))

    assert [job.job_id for job in jobs] == ["4398724241"]


def test_missing_time_element_leaves_posted_date_unset():
    card = _card().replace(
        '<time class="job-search-card__listdate" datetime="2026-08-04">1 day ago</time>',
        "",
    )

    assert LinkedInScraper().parse(_page([card]))[0].posted_date is None


def test_next_page_advances_start_by_the_page_size():
    full = _page([_card(job_id=str(i)) for i in range(PAGE_SIZE)])

    nxt = LinkedInScraper().next_page_url(full, "https://x/search?f_C=1337&start=0")

    assert "start=10" in nxt


def test_next_page_is_none_on_a_short_page():
    assert LinkedInScraper().next_page_url(_page([_card()]), "https://x?start=0") is None


def test_reads_the_window_fully_because_it_is_not_date_ordered():
    # sortBy=DD is accepted and ignored, so a page of known jobs says nothing
    # about the pages behind it and the engine's early stop must be disabled.
    config = LinkedInScraper().config
    assert config.paginate_fully is True
    assert config.fetch_mode is FetchMode.STATIC


def test_requests_only_a_recent_window_and_paces_itself():
    config = LinkedInScraper().config
    # Asking for the whole board would mean an unordered full read against an
    # endpoint that answers 429 after ~4 pages.
    assert "f_TPR=r604800" in config.career_url
    assert config.inter_page_delay_seconds >= 4.0
