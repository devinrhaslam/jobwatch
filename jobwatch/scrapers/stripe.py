from __future__ import annotations

import json

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

CONFIG = CompanyConfig(
    name="Stripe",
    career_url="https://stripe.com/jobs/search",
    fetch_mode=FetchMode.STATIC,
)


def _extract_json_array(payload: str, key: str) -> list[dict] | None:
    marker = f'"{key}":['
    index = payload.find(marker)
    if index == -1:
        return None
    start = payload.index("[", index)
    value, _ = json.JSONDecoder().raw_decode(payload, start)
    return value


class StripeScraper(Scraper):
    config = CONFIG

    def parse(self, payload: str) -> list[Job]:
        listings = _extract_json_array(payload, "listings")
        locations = _extract_json_array(payload, "locations") or []
        if not listings:
            return []
        jobs: list[Job] = []
        for listing in listings:
            job_id = listing.get("greenhouseId")
            title = listing.get("title")
            slug = listing.get("slug")
            if not (job_id and title and slug):
                continue
            location_names = [
                locations[i]["name"]
                for i in listing.get("locationIndices", [])
                if i < len(locations)
            ]
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=title,
                    url=f"https://stripe.com/careers/listing/{slug}/{job_id}",
                    location=", ".join(location_names) or None,
                )
            )
        return jobs
