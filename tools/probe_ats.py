"""Recon helper: guess which hiring platform each tracked company uses.

Probes well-known ATS endpoints for each company slug and reports those that
return a genuinely non-empty job board. Companies sharing a platform can
usually share one parameterized scraper instead of getting a bespoke module.

A platform check must prove real postings exist: several of these APIs answer
200 with an empty result set for any slug at all, so merely finding the
expected field would report every company as a match.

Usage: python tools/probe_ats.py [name ...]
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 15


def _count_greenhouse_api(text: str) -> int:
    return len(json.loads(text).get("jobs", []))


def _count_lever_api(text: str) -> int:
    return len(json.loads(text))


def _count_smartrecruiters(text: str) -> int:
    return int(json.loads(text).get("totalFound", 0))


def _count_greenhouse_html(text: str, slug: str) -> int:
    return len(set(re.findall(rf"/{re.escape(slug)}/jobs/(\d+)", text)))


def _count_lever_html(text: str, slug: str) -> int:
    return len(set(re.findall(rf"jobs\.lever\.co/{re.escape(slug)}/([0-9a-f-]{{8,}})", text)))


def _count_ashby_html(text: str, slug: str) -> int:
    return len(set(re.findall(rf"/{re.escape(slug)}/([0-9a-f]{{8}}-[0-9a-f-]+)", text)))


def _count_ashby_api(text: str) -> int:
    return len(json.loads(text).get("jobs", []))


# platform -> (url template, counter). The counter returns how many real
# postings the response contains; zero means "this company is not here".
PLATFORMS = {
    "greenhouse": (
        "https://job-boards.greenhouse.io/{slug}",
        _count_greenhouse_html,
    ),
    "greenhouse-api": (
        "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        _count_greenhouse_api,
    ),
    "lever": (
        "https://jobs.lever.co/{slug}",
        _count_lever_html,
    ),
    "lever-api": (
        "https://api.lever.co/v0/postings/{slug}?mode=json",
        _count_lever_api,
    ),
    # The public jobs.ashbyhq.com page renders its listings client-side, so the
    # HTML probe silently reports zero for boards that are in fact live. Keep it
    # as a secondary signal, but the JSON posting API is the authoritative check.
    "ashby": (
        "https://jobs.ashbyhq.com/{slug}",
        _count_ashby_html,
    ),
    "ashby-api": (
        "https://api.ashbyhq.com/posting-api/job-board/{slug}",
        _count_ashby_api,
    ),
    "smartrecruiters": (
        "https://api.smartrecruiters.com/v1/companies/{slug}/postings",
        _count_smartrecruiters,
    ),
}

MIN_POSTINGS = 3


# Boards are not always registered under the bare company name. DoorDash's
# Greenhouse slug is "doordashusa", which a bare-name guess never finds.
SLUG_SUFFIXES = ("", "usa", "inc", "careers", "jobs", "global", "us")


def slugs_for(name: str) -> list[str]:
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    hyphen = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    candidates = []
    for base in (compact, hyphen):
        for suffix in SLUG_SUFFIXES:
            candidates.append(f"{base}{suffix}" if suffix else base)
    # Some boards are registered under the company's domain rather than its
    # name: Kraken's Ashby board is "kraken.com", and the bare "kraken" slug is
    # a live but empty board that a name-only guess finds first and misreads.
    candidates.append(f"{compact}.com")
    return list(dict.fromkeys(candidates))


def probe(name: str) -> tuple[str, list[tuple[str, str, int]]]:
    session = requests.Session()
    hits: list[tuple[str, str, int]] = []
    for platform, (template, counter) in PLATFORMS.items():
        for slug in slugs_for(name):
            try:
                response = session.get(
                    template.format(slug=slug),
                    timeout=TIMEOUT,
                    headers={"User-Agent": USER_AGENT},
                )
            except requests.RequestException:
                continue
            if response.status_code != 200:
                continue
            try:
                count = (
                    counter(response.text)
                    if counter.__code__.co_argcount == 1
                    else counter(response.text, slug)
                )
            except (ValueError, KeyError, TypeError):
                continue
            if count >= MIN_POSTINGS:
                hits.append((platform, slug, count))
                break
    return name, hits


def main(argv: list[str]) -> int:
    if argv:
        names = argv
    else:
        listed = Path("companies.txt").read_text(encoding="utf-8").split("\n")
        names = [n.strip() for n in listed if n.strip()]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(probe, names))

    matched = [(n, h) for n, h in results if h]
    unmatched = [n for n, h in results if not h]

    print(f"=== on a known platform ({len(matched)}) ===")
    for name, hits in sorted(matched):
        rendered = ", ".join(f"{p}:{s} ({c} jobs)" for p, s, c in hits)
        print(f"  {name:22} {rendered}")
    print(f"\n=== custom / unknown, needs individual recon ({len(unmatched)}) ===")
    for name in sorted(unmatched):
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
