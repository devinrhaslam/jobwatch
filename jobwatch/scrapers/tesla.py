from __future__ import annotations

import json
import re

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Tesla's careers page is a client-rendered app in front of one API call that
# returns the entire board — every listing, plus the lookup tables that decode
# it — in a single response. Reading that call gives the whole board in one
# request and does not depend on the page's markup.
STATE_API = "/cua-api/apps/careers/state"
CAREERS_URL = "https://www.tesla.com/careers/search/"
POSTING_URL = "https://www.tesla.com/careers/search/job/{slug}-{job_id}"

# www.tesla.com sits behind Akamai Bot Manager, which answers plain HTTP — and
# headless Chromium — with "Access Denied" before any request reaches the board.
# Headless Firefox is served the page normally, so this reads the site with an
# ordinary browser rather than by disguising one.
BROWSER_ENGINE = "firefox"

# Tesla staffs factories, service centres and showrooms from the same board, so
# ~82% of its ~7,660 postings are for work this tool is not watching for. The
# API answers the whole board however it is asked — its page filters
# client-side — so the narrowing happens here instead of in the entry URL the
# way Meta's and Amazon's does.
#
# Departments are kept, not job titles: the department is Tesla's own structural
# label, while titles vary too much to match on (the reason role-fit filtering
# is left to the LLM at report time). "Engineering & Information Technology"
# still carries mechanical, thermal and sales engineers; dropping those is the
# report-time filter's job, not this one's.
#
# Matched by name, resolved against each payload's own lookup table. The ids are
# positional rather than stable: on 2026-08-05 Tesla's department list shifted
# by one, so "Engineering & Information Technology" moved to the id "Vehicle
# Software" had held and "Manufacturing" took its old one. Selecting by id meant
# choosing between a run that fails on every renumbering and one that quietly
# reports factory jobs as software; a name survives renumbering outright.
SOFTWARE_DEPARTMENTS = frozenset(
    {
        "Tesla AI",
        "Vehicle Software",
        "Engineering & Information Technology",
    }
)


def _slug(title: str) -> str:
    """Reproduce the readable prefix Tesla puts in its own job links.

    The prefix is decorative: the router keys on the trailing id, and a link
    whose slug is wrong still resolves to the right posting. So this exists to
    make a reported link readable, and cannot produce a dead one.
    """
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _watched_department_ids(departments: dict) -> set[str]:
    """Resolve the watched department names to the ids this payload gives them.

    A name that is not on the board at all is a hard failure rather than a
    silent narrowing. Tesla renaming or retiring a department would otherwise
    drop that whole slice of the board, and a run watching two departments out
    of three looks exactly like a run where nobody was hiring.
    """
    missing = SOFTWARE_DEPARTMENTS - set(departments.values())
    if missing:
        raise ValueError(
            f"Tesla departments {sorted(missing)} are not on the board: found "
            f"{sorted(departments.values())} — re-check the names before "
            f"trusting the filter"
        )
    return {
        dept_id for dept_id, name in departments.items() if name in SOFTWARE_DEPARTMENTS
    }


class TeslaScraper(Scraper):
    """Tesla's careers board, read through the state API its own page consumes.

    Listings are stored in a compact form — `t` title, `l` location id, `id`
    requisition — with the human-readable names held once in a `lookup` table
    rather than repeated across ~7,500 rows.

    Postings carry no publication date (`pu`, where present, is an expiry), so
    recency comes from snapshot diffing.

    Only the software-adjacent departments are kept; see SOFTWARE_DEPARTMENTS.
    """

    config = CompanyConfig(
        name="Tesla",
        career_url=CAREERS_URL,
        fetch_mode=FetchMode.RENDERED_XHR,
        capture_response_url=STATE_API,
        browser_engine=BROWSER_ENGINE,
        max_pages=1,  # one response carries the entire board
    )

    def parse(self, payload: str) -> list[Job]:
        state = json.loads(payload)
        lookup = state.get("lookup") or {}
        locations = lookup.get("locations") or {}
        watched = _watched_department_ids(lookup.get("departments") or {})
        jobs: list[Job] = []
        for record in state.get("listings") or []:
            if not isinstance(record, dict):
                continue
            if str(record.get("dp")) not in watched:
                continue
            job_id = record.get("id")
            title = record.get("t")
            if not (job_id and title):
                continue
            title = str(title).strip()
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=title,
                    url=POSTING_URL.format(slug=_slug(title), job_id=job_id),
                    location=locations.get(str(record.get("l"))),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        return None  # the board arrives whole; there is nothing to paginate
