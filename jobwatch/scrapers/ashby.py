from __future__ import annotations

import json
from datetime import datetime

from jobwatch.fetch import build_post_url
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

# The endpoint the hosted board itself calls for logged-out visitors. Needed
# because the posting API above is opt-in: a board with it switched off answers
# 404 there while serving the same postings here. No account, no session, and
# nothing about bot detection worked around — same basis as the LinkedIn guest
# endpoint.
GRAPHQL_URL = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams"
GRAPHQL_POSTING_URL = "https://jobs.ashbyhq.com/{slug}/{job_id}"

# This endpoint has introspection disabled, so the selection set below is the
# result of probing field by field. Notably there is no published timestamp on
# this type: boards read this way have no posted_date and their recency comes
# purely from snapshot diffing, as Meta's does.
GRAPHQL_QUERY = """
query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {
  jobBoard: jobBoardWithTeams(
    organizationHostedJobsPageName: $organizationHostedJobsPageName
  ) {
    jobPostings {
      id
      title
      locationName
      secondaryLocations { locationName }
    }
  }
}
"""

# Companies whose public job board is hosted by Ashby, keyed by company name ->
# board slug. Verified live by tools/probe_ats.py.
#
# Note the endpoint rejects a default urllib User-Agent with 403; fetch_static
# already sends a realistic one, so this only bites ad-hoc scripts.
BOARDS = {
    "1X Technologies": "1x",
    "Abridge": "abridge",
    "Airwallex": "airwallex",
    "Alchemy": "alchemy",
    # Applied Intuition's board is the bare word "applied"; confirmed from the
    # postings themselves ("ABOUT APPLIED INTUITION"), not from the slug.
    "Applied Intuition": "applied",
    "Baseten": "baseten",
    # Bumble is also on Lever under the identical slug, with the Ashby board a
    # week fresher (2026-08-05 vs 2026-07-30) — a migration in progress rather
    # than two boards, so the fresher one wins.
    "Bumble": "bumbleinc",
    "Cerebras": "cerebras",
    # chainalysis.com/careers is a marketing page; the board is behind its "View
    # open positions" link. A second board,
    # `chainalysis-government-solutions`, carries seven postings for the
    # wholly-owned subsidiary and is deliberately not tracked separately.
    "Chainalysis": "chainalysis-careers",
    # The board is the bare word "character", which is also the name of an
    # unrelated San Francisco brand-design studio — the same trap as Runway and
    # Warp. Confirmed from the postings themselves: they name Character.AI in
    # the description and sit in Redwood City, its headquarters.
    "Character.AI": "character",
    "Checkout.com": "checkout.com",
    "Cognition": "cognition",
    "Cohere": "cohere",
    "Confluent": "confluent",
    "Crusoe": "crusoe",
    "Cursor": "cursor",
    "Decagon": "decagon",
    "Docker": "docker",
    "ElevenLabs": "elevenlabs",
    "Fireworks AI": "fireworks",
    # Grammarly renamed itself Superhuman in 2025 and grammarly.com/careers now
    # redirects there. Its board name is the legal entity, spaces and all —
    # "Superhuman Platform Inc" — which is why every slug guess (grammarly,
    # superhuman, superhumanhq) 404s. Kept under the name in companies.txt.
    "Grammarly": "Superhuman%20Platform%20Inc",
    "Harvey": "harvey",
    # "hims-and-hers", not the "hims-hers" a slug guess builds by dropping the
    # ampersand. The link is on hims.com/careers-professionals — /careers itself
    # 404s, which is what made this look like a company with no board at all.
    # Its sitemap does not carry the careers pages either, so only the page's
    # own outbound links name the board.
    #
    # The same page family also links jobs.ashbyhq.com/you-health, which is the
    # affiliated clinician network rather than the company: five telehealth
    # 1099 physician and nurse-practitioner roles, no engineering. Not tracked.
    "Hims & Hers": "hims-and-hers",
    "Hinge Health": "hinge-health",
    # Kraken's board name is the domain, dot included. The bare "kraken" slug
    # is a live but empty board, so a probe that only counts a 200 would report
    # the wrong one; only "kraken.com" carries the postings.
    "Kraken": "kraken.com",
    "Lambda": "lambda",
    "LangChain": "langchain",
    "Linear": "linear",
    "Luma AI": "lumaai",
    "Mercor": "mercor",
    "Miro": "miro",
    # Two more boards whose slug is not the lowercased company name: Mistral's
    # is its domain (like Kraken's) and Thinking Machines' is CamelCase, and the
    # posting API is case-sensitive, so both are invisible to a lowercase guess.
    "Mistral AI": "mistral.ai",
    "Modal": "modal",
    "Modern Treasury": "moderntreasury",
    "monday.com": "monday.com",
    # Niantic sold its games division to Scopely, and nianticlabs.com/careers
    # now redirects to Scopely's board. The company still called Niantic is
    # Niantic Spatial, whose own board this is.
    "Niantic": "niantic-spatial",
    "Notion": "notion",
    "Nubank": "nubank",
    "OpenAI": "openai",
    "OpenEvidence": "openevidence",
    "Perplexity": "perplexity",
    "Physical Intelligence": "physicalintelligence",
    "Pinecone": "pinecone",
    "Plaid": "plaid",
    "Poolside": "poolside",
    "Ramp": "ramp",
    "Redis": "redis",
    "Reflection AI": "reflectionai",
    "Replit": "replit",
    # The bare "runway" board belongs to a different company — Runway the
    # business planning platform. The AI video company is "runway-ml", which is
    # what runwayml.com/careers links to. Both boards are live, so a slug guess
    # finds the wrong one first and never notices.
    "Runway": "runway-ml",
    "Saronic": "saronic",
    "Sentry": "sentry",
    "Sierra": "sierra",
    "Skydio": "skydio",
    "Snowflake": "snowflake",
    "Strava": "strava",
    "Substack": "substack",
    "Suno": "suno",
    "Supercell": "supercell",
    "Synthesia": "synthesia",
    "Temporal": "temporal",
    "Thinking Machines Lab": "ThinkingMachines",
    "Vanta": "vanta",
    "Weaviate": "weaviate",
    "Whoop": "whoop",
    "WorkOS": "workos",
    "Writer": "writer",
}


def _location(record: dict) -> str | None:
    """Primary location plus any secondary ones, matching how Greenhouse boards
    present multi-site roles."""
    names = []
    primary = record.get("location")
    if primary:
        names.append(str(primary))
    for entry in record.get("secondaryLocations") or []:
        name = entry.get("location") if isinstance(entry, dict) else None
        if name and str(name) not in names:
            names.append(str(name))
    return ", ".join(names) or None


def _posted_date(record: dict) -> str | None:
    raw = record.get("publishedAt")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        return None


class AshbyScraper(Scraper):
    """One parameterised scraper for every company on a public Ashby board.

    Same reasoning as the Greenhouse scraper: Ashby is the ATS recruiters post
    into, so its posting API is the upstream source rather than a mirror, and it
    carries a real `publishedAt` timestamp.
    """

    def __init__(self, company: str, slug: str):
        self.slug = slug
        self.config = CompanyConfig(
            name=company,
            career_url=API_URL.format(slug=slug),
            fetch_mode=FetchMode.STATIC,
        )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("jobs") or []
        jobs: list[Job] = []
        for record in records:
            # isListed is the board's own published flag. Every job on the
            # boards sampled so far is listed, but an unlisted posting is not
            # public and should not be reported as something to apply to.
            if record.get("isListed") is False:
                continue
            job_id = record.get("id")
            title = record.get("title")
            url = record.get("jobUrl") or record.get("applyUrl")
            if not (job_id and title and url):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=title.strip(),
                    url=url,
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs


# Companies on Ashby whose public posting API is switched off, so they must be
# read through the board's own GraphQL endpoint instead.
GRAPHQL_BOARDS = {
    "Whatnot": "whatnot",
}


def _graphql_location(record: dict) -> str | None:
    """Same shape as _location, but this endpoint names the field
    `locationName` rather than `location`."""
    names = []
    primary = record.get("locationName")
    if primary:
        names.append(str(primary))
    for entry in record.get("secondaryLocations") or []:
        name = entry.get("locationName") if isinstance(entry, dict) else None
        if name and str(name) not in names:
            names.append(str(name))
    return ", ".join(names) or None


class AshbyGraphQLScraper(Scraper):
    """Reads an Ashby board through the endpoint its hosted page uses.

    Identical postings to AshbyScraper, minus the published timestamp, which
    this endpoint does not expose.
    """

    def __init__(self, company: str, slug: str):
        self.slug = slug
        self.config = CompanyConfig(
            name=company,
            career_url=build_post_url(
                GRAPHQL_URL,
                {
                    "operationName": "ApiJobBoardWithTeams",
                    "variables": {"organizationHostedJobsPageName": slug},
                    "query": GRAPHQL_QUERY,
                },
            ),
            fetch_mode=FetchMode.JSON_POST,
        )

    def parse(self, payload: str) -> list[Job]:
        data = json.loads(payload).get("data") or {}
        board = data.get("jobBoard") or {}
        records = board.get("jobPostings") or []
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
                    title=str(title).strip(),
                    url=GRAPHQL_POSTING_URL.format(slug=self.slug, job_id=job_id),
                    location=_graphql_location(record),
                    posted_date=None,
                )
            )
        return jobs


def scrapers() -> list[AshbyScraper | AshbyGraphQLScraper]:
    return [AshbyScraper(company, slug) for company, slug in BOARDS.items()] + [
        AshbyGraphQLScraper(company, slug) for company, slug in GRAPHQL_BOARDS.items()
    ]
