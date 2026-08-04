from __future__ import annotations

import json

from bs4 import BeautifulSoup

from jobwatch.fetch import build_post_url
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

AJAX_URL = "https://www.hudsonrivertrading.com/wp-admin/admin-ajax.php"

# The board is a self-hosted WordPress plugin ("hrt-jobs") rather than an ATS.
# Its careers page ships no listings — they arrive from this admin-ajax action,
# whose name and payload come from the plugin's own frontend bundle. `setting`
# is the plugin's render config, copied verbatim from the page's
# `.hrt-card-wrapper[data-filters-settings]`; the handler 500s without it.
SETTING = json.dumps(
    {
        "meta_data": [
            {"icon": "", "term": "locations"},
            {"icon": "", "term": "job-category"},
            {"icon": "", "term": "job-type"},
        ],
        "settings": {"hide_job_id": True},
    }
)
BODY = {
    "action": "get_hrt_jobs_handler",
    "data[search]": "",
    "setting": SETTING,
}

# Not the Greenhouse board that hudsonrivertrading.com also embeds: that one
# ("hrttalentcommunity") holds three "Talent Community" pipeline entries, not
# the real listings.


def _location(card) -> str | None:
    """The first info list holds the location; the second holds the category
    and seniority."""
    first_list = card.select_one(".hrt-card-info-list")
    if first_list is None:
        return None
    names = []
    for item in first_list.select(".hrt-card-info-item"):
        text = item.get_text(" ", strip=True)
        if text and text != "•" and text not in names:
            names.append(text)
    return ", ".join(names) or None


class HudsonRiverTradingScraper(Scraper):
    """Hudson River Trading's self-hosted WordPress job board.

    The endpoint answers the whole board in one form-encoded POST, so there is
    no pagination. Postings carry no publication date, so recency comes from
    snapshot diffing.
    """

    config = CompanyConfig(
        name="Hudson River Trading",
        career_url=build_post_url(AJAX_URL, BODY),
        fetch_mode=FetchMode.FORM_POST,
    )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload)
        if not isinstance(records, list):
            return []
        jobs: list[Job] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            # The WordPress post id, not the card's data-jobid: one requisition
            # is listed once per location, so data-jobid repeats (53 distinct
            # values across 72 postings) and would collapse real listings.
            job_id = record.get("ID")
            title = record.get("title")
            if not (job_id and title):
                continue
            card = BeautifulSoup(record.get("content") or "", "html.parser")
            anchor = card.select_one("a.hrt-card-title")
            if anchor is None or not anchor.get("href"):
                continue
            jobs.append(
                Job(
                    company="Hudson River Trading",
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=anchor["href"],
                    location=_location(card),
                )
            )
        return jobs
