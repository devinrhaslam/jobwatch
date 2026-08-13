from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
CANONICAL_POSTING_URL = "https://job-boards.greenhouse.io/{slug}/jobs/{job_id}"

# Companies whose careers page is a downstream renderer of a public Greenhouse
# board, keyed by company name -> board slug. Verified live by tools/probe_ats.py.
#
# LinkedIn is deliberately absent: it matches three different boards (Greenhouse
# 53 jobs, Lever 23) and none is plausibly LinkedIn's real volume, so it needs
# individual recon rather than an assumed slug.
BOARDS = {
    "Adyen": "adyen",
    "Affirm": "affirm",
    "Agility Robotics": "agilityrobotics",
    "Airbnb": "airbnb",
    "Airtable": "airtable",
    "Anduril": "andurilindustries",
    "Anthropic": "anthropic",
    # Names the retired boards.greenhouse.io host in `absolute_url`, with a
    # `?gh_jid=` repeating the id already in the path — the shape _posting_url
    # rebuilds, as it does for Anduril and Figma.
    "AppLovin": "applovin",
    "Apptronik": "apptronik",
    # The trailing digits are part of the board name, like Sourcegraph's. Only
    # archer.com/careers names it, and only once loaded — the page is a shell
    # that fetches this board client-side.
    "Archer Aviation": "archer56",
    "Asana": "asana",
    "Astranis": "astranis",
    "Beta Technologies": "betatechnologiesinc",
    # bill.com/jobs embeds this board; the slug is the domain without the dot.
    "BILL": "billcom",
    "Block": "block",
    "Brex": "brex",
    "Carvana": "carvana",
    "Chainguard": "chainguard",
    "Chime": "chime",
    # ClickHouse serves the same 167 postings on Ashby under the same slug, down
    # to identical publish timestamps, so either board is correct and this one is
    # picked only for consistency with the rest of the list.
    "ClickHouse": "clickhouse",
    "Cloudflare": "cloudflare",
    "Cockroach Labs": "cockroachlabs",
    "Coinbase": "coinbase",
    "CoreWeave": "coreweave",
    "Coupang": "coupang",
    "Cresta": "cresta",
    "Cribl": "cribl",
    "Databricks": "databricks",
    "Datadog": "datadog",
    "Discord": "discord",
    "DoorDash": "doordashusa",
    "Doximity": "doximity",
    "Dropbox": "dropbox",
    "Duolingo": "duolingo",
    "Elastic": "elastic",
    "Epic Games": "epicgames",
    "Faire": "faire",
    "Fastly": "fastly",
    "Figma": "figma",
    "Figure AI": "figureai",
    "Fireblocks": "fireblocks",
    # Also covers dbt Labs, which merged into Fivetran: getdbt.com/careers now
    # renders this same board, so watching dbt Labs separately would report
    # every Fivetran posting twice.
    "Fivetran": "fivetran",
    "Flexport": "flexport",
    "GitLab": "gitlab",
    "Glean": "gleanwork",
    # gong.io's board is "gongio". The bare "gong" slug is a live
    # SmartRecruiters board belonging to an unrelated company, whose postings
    # are journalism internships.
    "Gong": "gongio",
    "Grafana Labs": "grafanalabs",
    "Gusto": "gusto",
    "Honeycomb": "honeycomb",
    "HubSpot": "hubspotjobs",
    "Instacart": "instacart",
    "Jane Street": "janestreet",
    "JFrog": "jfrog",
    "Klaviyo": "klaviyo",
    "Kodiak Robotics": "kodiak",
    "LaunchDarkly": "launchdarkly",
    "Lyft": "lyft",
    "Marqeta": "marqeta",
    "Mercury": "mercury",
    "MongoDB": "mongodb",
    "Monzo": "monzo",
    "Motional": "motional",
    "Neo4j": "neo4j",
    "Netlify": "netlify",
    "Netskope": "netskope",
    # Navan's board is still under its former name, TripActions. Its
    # absolute_url puts the id in a query parameter, but unlike the boards in
    # EMBED_FALLBACK_BOARDS the canonical URL redirects to a real per-job path
    # whose og:title is the posting, so the ordinary link works.
    "Navan": "tripactions",
    "Neuralink": "neuralink",
    "Nuro": "nuro",
    "Okta": "okta",
    "Oura": "oura",
    "Pinterest": "pinterest",
    "Planet Labs": "planetlabs",
    "Postman": "postman",
    "Pure Storage": "purestorage",
    "Reddit": "reddit",
    "Relativity Space": "relativity",
    "Riot Games": "riotgames",
    "Ripple": "ripple",
    "Robinhood": "robinhood",
    "Roblox": "roblox",
    "Rocket Lab": "rocketlab",
    # Rockstar runs its own board rather than posting to its parent's, so
    # Take-Two's 33 postings and Rockstar's 74 do not overlap.
    "Rockstar Games": "rockstargames",
    "Rubrik": "rubrik",
    "Samsara": "samsara",
    "Scale AI": "scaleai",
    # Nothing name-derived reaches "skildai-careers": the compact base takes the
    # suffix without a hyphen and the hyphenated base splits the name instead
    # ("skildaicareers", "skild-aicareers"). It came from the careers page's own
    # JS chunk, which fetches this board id from the browser — the page itself
    # ships "Current Openings • 00" and "Loading...", so nothing in its HTML or
    # its sitemap (it publishes none) names the board. Note the path is
    # /career, singular; /careers 404s, which is what made it look boardless.
    "Skild AI": "skildai-careers",
    "Scopely": "scopely",
    "SHEIN": "shein",
    "SoFi": "sofi",
    "Sony Interactive Entertainment": "sonyinteractiveentertainmentglobal",
    # The trailing digits are part of the board name, not a version: no
    # name-derived guess reaches it, and sourcegraph.com/jobs is what names it.
    "Sourcegraph": "sourcegraph91",
    "SpaceX": "spacex",
    "Stripe": "stripe",
    "StubHub": "stubhubinc",
    "Tailscale": "tailscale",
    "Take-Two Interactive": "taketwo",
    "The Trade Desk": "thetradedesk",
    "Toast": "toast",
    "Together AI": "togetherai",
    "Twilio": "twilio",
    "Twitch": "twitch",
    "Vannevar Labs": "vannevarlabs",
    "Varda Space Industries": "vardaspace",
    # The space-station company, not VAST Data the storage company, whose board
    # this is emphatically not: "billions of people living and thriving in
    # space". Found while probing aliases for VAST Data, which is still unbuilt.
    "Vast Space": "vast",
    "Vercel": "vercel",
    "Verkada": "verkada",
    # The terminal company. An unrelated Warp — an HR and payroll platform —
    # holds the identically named Ashby board, so the slug alone picks the
    # wrong one half the time.
    "Warp": "warp",
    "Waymo": "waymo",
    # Wayve also has a live Ashby board carrying almost the same postings (104
    # vs 106) and published the same day. Greenhouse is kept for its
    # first_published timestamp, which the Ashby board does not beat.
    "Wayve": "wayve",
    # Wiz's board is registered under the legal entity, not the brand: the bare
    # "wiz" slug is not its board.
    "Wiz": "wizinc",
    "World Labs": "worldlabs",
    "xAI": "xai",
    "Zipline": "flyzipline",
    "Zscaler": "zscaler",
}


# Greenhouse's standalone embed view of a single posting. Unlike the canonical
# URL it is never redirected to the company's own site, so it renders the job
# itself on every board tried.
EMBED_POSTING_URL = "https://job-boards.greenhouse.io/embed/job_app?for={slug}&token={job_id}"

# Boards whose canonical Greenhouse URL 301s to a company page that does not
# open the posting, so the embed view above is reported instead.
#
# _posting_url already refuses an `absolute_url` that carries the id only in a
# query parameter, because such a page depends on the company's own JavaScript
# to deep-link. What these boards add is that their *canonical* URL redirects to
# that same page, so the fallback lands on the dead end it was avoiding. Both
# URLs then answer a healthy 200, which is why a status check never catches this
# and every one of these was found by asserting the job's title appears on the
# page it opens.
#
# Fastly, Nuro, Netskope and Zipline were confirmed in a real browser: each
# renders a generic careers or open-roles page with no route to the posting.
# The rest were classified by the same redirect shape plus a failed title
# assertion. Epic Games and Rubrik additionally answer 403 through their own
# sites; the embed view avoids that too.
#
# Deliberately absent: Duolingo and HubSpot. Their pages also failed a plain
# title check, but they put the job id in the path and Duolingo was confirmed in
# a browser to render the posting correctly — the check was defeated by
# client-side rendering, not by a dead link.
EMBED_FALLBACK_BOARDS = frozenset(
    {
        "Agility Robotics",
        "BILL",
        "Cockroach Labs",
        "CoreWeave",
        "Epic Games",
        "Fastly",
        "Fivetran",
        "Motional",
        "Netskope",
        "Nuro",
        "Rubrik",
        "SoFi",
        "Zipline",
    }
)


def _location(record: dict) -> str | None:
    """Prefer a metadata location over the top-level one.

    Some boards use `location.name` for the work arrangement rather than a place
    — Cloudflare's reads "Hybrid" / "In-Office" / "Distributed" — and put the
    actual city in a metadata field. Boards without such a field (Stripe,
    Airbnb) fall through to `location.name`, and a metadata entry with no value
    (Anthropic's "Location Type") is skipped rather than blanking the location.
    """
    for entry in record.get("metadata") or []:
        if "location" not in (entry.get("name") or "").lower():
            continue
        value = entry.get("value")
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if item)
        if value:
            return str(value)
    name = (record.get("location") or {}).get("name")
    return name or None


def _posting_url(record: dict, slug: str, job_id: str) -> str:
    """Prefer the company's own posting URL, but only when it actually
    identifies the job in its path.

    Some boards point `absolute_url` at a generic listing page with the job id
    only in a query parameter — Stripe's is `stripe.com/jobs/search?gh_jid=N`
    and Pinterest's `pinterestcareers.com/jobs/?gh_jid=N`. Those depend on the
    company's own JavaScript to deep-link, and when the posting has closed they
    silently render the full search listing instead, which reads as "the link
    took me to the jobs page, not the job". The canonical Greenhouse URL
    redirects to the same destination while the posting is open, and to an
    explicit error page once it is not.

    An `absolute_url` already on Greenhouse is rebuilt rather than passed
    through, because a board may name the retired `boards.greenhouse.io` host:
    Anduril and Figma both still do, and both append a `?gh_jid=` that repeats
    the id already in the path. That host only 301s to `job-boards`, so the
    link works but spends a redirect getting there and depends on a redirect
    Greenhouse has no reason to keep. Rebuilding costs nothing for the boards
    already naming the canonical host — theirs is byte-identical.
    """
    absolute = record.get("absolute_url") or ""
    parsed = urlsplit(absolute) if absolute else None
    if parsed and not parsed.netloc.endswith("greenhouse.io"):
        if re.search(rf"/{re.escape(job_id)}(?:/|$)", parsed.path):
            return absolute
    return CANONICAL_POSTING_URL.format(slug=slug, job_id=job_id)


def _posted_date(record: dict) -> str | None:
    """Only `first_published` is a real posting time. `updated_at` moves in bulk
    re-indexes — every Anthropic job shared one timestamp — so it would report a
    stale listing as posted today."""
    raw = record.get("first_published")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        return None


class GreenhouseScraper(Scraper):
    """One parameterised scraper for every company on a public Greenhouse board.

    Greenhouse is the ATS recruiters post into; a company's careers page renders
    from it. Reading the board API directly is therefore the upstream source,
    not a third-party mirror, and it carries a real publication timestamp that
    most careers pages omit.
    """

    def __init__(self, company: str, slug: str):
        self.slug = slug
        self.use_embed_url = company in EMBED_FALLBACK_BOARDS
        self.config = CompanyConfig(
            name=company,
            career_url=API_URL.format(slug=slug),
            fetch_mode=FetchMode.STATIC,
        )

    def _url(self, record: dict, job_id: str) -> str:
        if self.use_embed_url:
            return EMBED_POSTING_URL.format(slug=self.slug, job_id=job_id)
        return _posting_url(record, self.slug, job_id)

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("jobs") or []
        jobs: list[Job] = []
        for record in records:
            job_id = record.get("id")
            title = record.get("title")
            if not (job_id and title):
                continue
            job_id = str(job_id)
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=job_id,
                    title=title.strip(),
                    url=self._url(record, job_id),
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs


def scrapers() -> list[GreenhouseScraper]:
    return [GreenhouseScraper(company, slug) for company, slug in BOARDS.items()]
