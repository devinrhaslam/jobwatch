from __future__ import annotations

import json

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Atlassian's careers page renders client-side and its all-jobs HTML carries no
# listings at all, so there is nothing to parse from the page itself. The page
# calls this endpoint, which answers the whole board — 241 postings — as plain
# JSON over an ordinary GET, with no key, token or browser required.
#
# The underlying ATS is iCIMS (`globalcareers-atlassian.icims.com`, named in
# each record's portalUrl), but this endpoint is the better source: it is one
# request for the entire board, and it is what the careers page itself trusts.
API_URL = "https://www.atlassian.com/endpoint/careers/listings"

# The site's own posting page. Preferred over the record's `applyUrl`, which
# jumps straight into the iCIMS apply form (`?mode=apply`) rather than showing
# the description first.
POSTING_URL = "https://www.atlassian.com/company/careers/details/{job_id}"


def _location(record: dict) -> str | None:
    """Roles list every site they are open in; 198 of 241 postings name more
    than one. 29 name none at all, which reads as no location rather than an
    empty string."""
    names = []
    for entry in record.get("locations") or []:
        if entry and str(entry) not in names:
            names.append(str(entry))
    return ", ".join(names) or None


class AtlassianScraper(Scraper):
    """Reads Atlassian's board from the endpoint its careers page calls.

    No posted_date: the only timestamp on a record is `portalJobPost.updatedDate`,
    which is an edit time rather than a publication time. It is well distributed
    (207 distinct values across 241 postings) so it is not a bulk re-index
    artefact, but a job posted in January and edited yesterday would still
    report as posted yesterday. Reporting nothing is better than reporting a
    date that means something else; recency comes from snapshot diffing, as it
    does for Meta.
    """

    config = CompanyConfig(
        name="Atlassian",
        career_url=API_URL,
        fetch_mode=FetchMode.STATIC,
    )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload)
        if not isinstance(records, list):
            return []
        jobs: list[Job] = []
        # The endpoint repeats some postings verbatim — 241 records for 226
        # distinct ids on the board sampled here. The duplicates are identical,
        # so the first occurrence wins; without this the same job would be
        # listed twice in a report.
        seen: set[str] = set()
        for record in records:
            job_id = record.get("id")
            title = record.get("title")
            if not (job_id and title):
                continue
            job_id = str(job_id)
            if job_id in seen:
                continue
            seen.add(job_id)
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=job_id,
                    title=str(title).strip(),
                    url=POSTING_URL.format(job_id=job_id),
                    location=_location(record),
                    posted_date=None,
                )
            )
        return jobs
