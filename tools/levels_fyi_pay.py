"""Rank companies by Levels.fyi median software-engineer total compensation.

`companies.txt` is curated for two things at once: pay and brand recognition.
Pay is the part that can actually be measured, and Levels.fyi publishes it
per company at a stable, public URL.

This reads the LLM-readable markdown that Levels.fyi's own robots.txt
advertises -- append `.md` to any `/companies/<slug>/salaries/...` route -- and
pulls the national median, the sample size behind it, and the per-level ladder.
The markdown is a summary surface built for exactly this: it is ~6KB instead of
a ~190KB client-rendered page, and it will not silently change shape the way
scraped DOM does.

Two things are deliberately *not* done here:

  * The site's own leaderboard (`/leaderboard/...`) and the "sort companies by
    compensation" control are behind a free account, and the signup copy says
    in as many words that the account exists to check you are "not a bot or AI
    scraper". So the full ranking is not fetched -- it is *recomputed*, one
    public company page at a time, which is the same data without using an
    account to do the thing the account is there to prevent.
  * Rate is kept to one request every few seconds. An earlier pass at four
    concurrent workers tripped the AWS WAF human-verification challenge after
    roughly 400 requests, and that challenge is not something to solve or work
    around -- it is the site saying "slower". DEFAULT_DELAY is that lesson.

Responses are cached under state/levels_fyi/, so a run that is interrupted (or
throttled) resumes for free rather than re-fetching what it already has.

Usage:
    python tools/levels_fyi_pay.py                      # rank companies.txt
    python tools/levels_fyi_pay.py --extra cands.txt    # ...plus candidates
    python tools/levels_fyi_pay.py --json out.json
    python tools/levels_fyi_pay.py --delay 5 --limit 50

Data source: Levels.fyi (https://www.levels.fyi). Levels.fyi asks that derived
work cite them; anything built on this output should.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "state" / "levels_fyi"

# Always pin the country. The bare /salaries/software-engineer route picks a
# default location per company, and for a company whose submissions skew
# offshore it picks that country: Atlassian and Arista Networks both answer in
# INR for India. Reading the bare route and matching on "$" drops them silently
# -- it looks like "no data" when it is really "different continent". The
# /locations/united-states sub-route is explicit, so use it first and keep the
# bare route only as a fallback for companies with no US page at all.
US = "https://www.levels.fyi/companies/{slug}/salaries/software-engineer/locations/united-states.md"
BARE = "https://www.levels.fyi/companies/{slug}/salaries/software-engineer.md"

# Levels.fyi's robots.txt names Claude-User as a user-initiated reader and
# allows it. Identify honestly rather than posing as a desktop browser: this
# runs because a person asked for it, which is the case that file permits.
USER_AGENT = "Claude-User/1.0 (+https://claude.ai; user-initiated fetch on behalf of a person)"
TIMEOUT = 30
DEFAULT_DELAY = 2.5

# Slugs that name-derivation gets wrong: Levels.fyi files some companies under
# a parent, a former name, or a legal name nobody types.
SLUG_OVERRIDES = {
    "Walmart Global Tech": "walmart",
    "Meta": "facebook",
    "Block": "square",
    "X": "twitter",
    "Google DeepMind": "deepmind",
    "TikTok": "bytedance",
    "Hims & Hers": "hims-and-hers",
    "JPMorgan Chase": "jpmorgan-chase",
    "RTX": "raytheon",
    "Raytheon": "raytheon",
}

# Suffixes Levels.fyi tends to carry that a bare company name does not. Tried in
# order when the derived slug has no page; the first one with a median wins.
SLUG_SUFFIXES = (
    "", "-ai", "-industries", "-group", "-technologies", "-technology", "-labs",
    "-games", "-networks", "-software", "-systems", "-space", "-inc",
    "-corporation", "-motor-company", "-interactive",
)

CHALLENGE = re.compile(r"Human Verification|awsWafCookieDomainList", re.I)

# Currency-agnostic on purpose: a non-USD page must be *detected and labelled*,
# never silently skipped for failing to match a dollar sign.
RE_MEDIAN = re.compile(r"Median Total Compensation:\s*(\D{0,3})([\d,]+)")
RE_SAMPLE = re.compile(r"tracks\s+([\d,]+)\s+Software Engineer salary submissions")
RE_LEVEL_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*\D{0,3}([\d,]+)\s*\|", re.M)
RE_AVERAGE = re.compile(r"average yearly total compensation[^\d]*([\d,]+)")
RE_LOCATION = re.compile(r"\*\*Location:\*\*\s*(.+)")
RE_CURRENCY = re.compile(r"\*\*Currency:\*\*\s*([A-Z]{3})")
# levels.fyi tags each level with the experience its submitters report. That is
# the only company-agnostic way to compare ladders -- "Senior" means 5 years at
# one company and 14 at another.
RE_YOE_LVL = re.compile(
    r"### How many years of experience does an? (.+?) have\?\s*\n(.*?)"
    r"typically have (\d+)[–-](\d+) years", re.S)


class Throttled(RuntimeError):
    """The site served a bot-protection challenge instead of the page."""


@dataclass
class Pay:
    name: str
    slug: str
    median: int | None = None
    average: int | None = None
    samples: int | None = None
    top_level: int | None = None
    location: str = ""
    currency: str = ""
    note: str = ""
    ladder: list[tuple[str, int]] | None = None
    bands: dict[str, tuple[int, int]] | None = None

    def at_yoe(self, years: int) -> tuple[str, int, tuple[int, int]] | None:
        """The level this many years of experience actually qualifies for.

        The highest level whose band *starts* at or below `years` -- not the
        band nearest to it. Nearest-band promotes an 8-year engineer into
        Cisco's Distinguished Engineer (21-23 yrs) and reads Roku's Senior
        (12-14 yrs) as reachable. Both are wrong, and both look like great
        finds right up until the bands are printed.
        """
        if not self.ladder or not self.bands:
            return None
        ok = [i for i, (n, _) in enumerate(self.ladder)
              if n in self.bands and self.bands[n][0] <= years]
        if not ok:
            return None
        name, amount = self.ladder[max(ok)]
        return name, amount, self.bands[name]


def slugify(name: str) -> str:
    if name in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[name]
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.replace("&", " and ").replace("+", " plus ")
    # Drop apostrophes rather than letting them become separators: Levels.fyi
    # spells these "lowes" and "mcdonalds", not "lowe-s" and "mcdonald-s".
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s


def slug_variants(name: str) -> list[str]:
    """Candidate slugs, best guess first."""
    if name in SLUG_OVERRIDES:
        return [SLUG_OVERRIDES[name]]
    base = slugify(name)
    out = [base]
    # A name that already ends in a suffix should also be tried without it
    # ("Marvell Technology" is filed as "marvell", "Anduril" as
    # "anduril-industries") -- so strip as well as append.
    for suf in SLUG_SUFFIXES[1:]:
        if base.endswith(suf):
            out.append(base[: -len(suf)])
    for suf in SLUG_SUFFIXES[1:]:
        cand = base + suf
        if cand not in out:
            out.append(cand)
    return out


def _cache_path(url: str) -> Path:
    return CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".md")


OFFLINE = False


def fetch(session: requests.Session, url: str, delay: float, tries: int = 3) -> str:
    cached = _cache_path(url)
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    if OFFLINE:
        return ""
    time.sleep(delay)
    # A read timeout partway through a 600-company sweep must not lose the
    # sweep. Retry transient network errors; only a bot-protection challenge
    # is a reason to stop, because that one means "back off", not "try again".
    for attempt in range(tries):
        try:
            resp = session.get(url, timeout=TIMEOUT)
            break
        except requests.RequestException as exc:
            if attempt == tries - 1:
                print(f"   ! giving up on {url}: {exc}", file=sys.stderr)
                return ""
            time.sleep(delay * (attempt + 2))
    body = resp.text
    if CHALLENGE.search(body):
        raise Throttled(url)
    # A wrong slug renders the SPA shell (HTML), not markdown.
    if resp.status_code == 404 or not body.lstrip().startswith("#"):
        body = ""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_text(body, encoding="utf-8")
    return body


def parse(name: str, slug: str, md: str) -> Pay:
    out = Pay(name=name, slug=slug)
    if not md:
        out.note = "no page / wrong slug"
        return out
    if m := RE_LOCATION.search(md):
        out.location = m.group(1).strip()
    if m := RE_CURRENCY.search(md):
        out.currency = m.group(1)
    if m := RE_MEDIAN.search(md):
        out.median = int(m.group(2).replace(",", ""))
    if m := RE_SAMPLE.search(md):
        out.samples = int(m.group(1).replace(",", ""))
    if m := RE_AVERAGE.search(md):
        out.average = int(m.group(1).replace(",", ""))
    ladder = [(n, int(v.replace(",", ""))) for n, v in RE_LEVEL_ROW.findall(md)
              if n.lower() != "level"]
    if ladder:
        out.ladder = ladder
        out.top_level = max(v for _, v in ladder)
        bands: dict[str, tuple[int, int]] = {}
        for m in RE_YOE_LVL.finditer(md):
            head = m.group(1).strip()
            lvl = head[len(name):].strip() if head.startswith(name) else head.split()[-1]
            bands[lvl] = (int(m.group(3)), int(m.group(4)))
        out.bands = bands or None
    if out.median is None:
        out.note = "page exists, no median reported"
    elif out.currency != "USD":
        out.note = f"non-USD page ({out.currency or '?'}, {out.location or '?'})"
    return out


def measure(session: requests.Session, name: str, delay: float) -> Pay:
    """First slug variant that yields a US median wins; a non-US page is only
    accepted when no US page exists anywhere, and is labelled when it is."""
    fallback: Pay | None = None
    for slug in slug_variants(name):
        got = parse(name, slug, fetch(session, US.format(slug=slug), delay))
        if got.median and got.currency == "USD":
            # The US sub-route reports no submission count, and a median over
            # three submissions should not outrank one over three thousand. The
            # bare route carries the count, so borrow it when that page is also
            # US -- otherwise the count would describe some other country.
            if got.samples is None:
                bare = parse(name, slug, fetch(session, BARE.format(slug=slug), delay))
                if bare.currency == "USD":
                    got.samples = bare.samples
            return got
        if got.median or got.note == "page exists, no median reported":
            # Slug is real but the US page is thin -- try the company's default
            # page before giving up on it.
            bare = parse(name, slug, fetch(session, BARE.format(slug=slug), delay))
            if bare.median and bare.currency == "USD":
                return bare
            fallback = fallback or (bare if bare.median else got)
    return fallback or Pay(name=name, slug=slugify(name), note="no page / wrong slug")


def load_names(paths: list[Path]) -> list[str]:
    seen: dict[str, None] = {}
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                seen.setdefault(line, None)
    return list(seen)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extra", type=Path, action="append", default=[],
                    help="additional newline-separated candidate list(s)")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                    help=f"seconds between live requests (default {DEFAULT_DELAY})")
    ap.add_argument("--limit", type=int, default=0, help="stop after N companies")
    ap.add_argument("--json", type=Path, help="write full results as JSON")
    ap.add_argument("--min-samples", type=int, default=1,
                    help="hide companies with fewer than N submissions")
    ap.add_argument("--offline", action="store_true",
                    help="report from the cache only, making no network requests")
    ap.add_argument("--at-yoe", type=int, metavar="YEARS",
                    help="rank by pay at the level this many years of experience "
                         "qualifies for, instead of the company-wide median")
    ap.add_argument("--bar", type=int, default=0, metavar="USD",
                    help="with --at-yoe, show only companies clearing this figure")
    args = ap.parse_args(argv)

    global OFFLINE
    OFFLINE = args.offline

    names = load_names([ROOT / "companies.txt", *args.extra])
    if args.limit:
        names = names[: args.limit]

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/markdown,text/plain,*/*"})

    results: list[Pay] = []
    for i, name in enumerate(names, 1):
        try:
            results.append(measure(session, name, args.delay))
        except Throttled:
            print(f"\n!! bot-protection challenge at {name} ({i}/{len(names)}).",
                  file=sys.stderr)
            print("   Stopping. Cached results are kept; rerun later with a larger",
                  "--delay to resume.", file=sys.stderr)
            break
        if i % 25 == 0:
            print(f"  ...{i}/{len(names)}", file=sys.stderr, flush=True)

    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in results], indent=1), encoding="utf-8")

    # Only USD pages are comparable; a non-USD median is real data but ranking
    # it against dollars would put a ₹9.2M package above every US company.
    ranked = [r for r in results
              if r.median and r.currency == "USD" and (r.samples or 0) >= args.min_samples]
    ranked.sort(key=lambda r: -r.median)
    missing = [r for r in results if not (r.median and r.currency == "USD")]

    if args.at_yoe:
        placed = []
        for r in ranked:
            hit = r.at_yoe(args.at_yoe)
            if hit and hit[1] >= args.bar:
                placed.append((hit, r))
        placed.sort(key=lambda p: -p[0][1])
        unplaceable = sum(1 for r in ranked if not r.at_yoe(args.at_yoe))
        print(f"{'rank':>4}  {'@'+str(args.at_yoe)+'yr':>10}  {'level (yrs)':>24}  "
              f"{'ceiling':>10}  {'n':>6}  company")
        for i, ((lvl, amount, band), r) in enumerate(placed, 1):
            lb = f"{lvl[:15]} ({band[0]}-{band[1]})"
            top = f"${r.top_level:,}" if r.top_level else "-"
            print(f"{i:>4}  {'$'+format(amount, ','):>10}  {lb:>24}  {top:>10}  "
                  f"{r.samples or 0:>6}  {r.name}")
        print(f"\n{len(placed)} placed at {args.at_yoe} yrs"
              f"{f' clearing ${args.bar:,}' if args.bar else ''}; "
              f"{unplaceable} had no experience-banded level to place them at.",
              file=sys.stderr)
    else:
        print(f"{'rank':>4}  {'median':>10}  {'top level':>10}  {'n':>6}  company")
        for i, r in enumerate(ranked, 1):
            top = f"${r.top_level:,}" if r.top_level else "-"
            print(f"{i:>4}  {'$'+format(r.median, ','):>10}  {top:>10}  {r.samples or 0:>6}  {r.name}")
    if missing:
        print(f"\n=== no median on Levels.fyi ({len(missing)}) ===", file=sys.stderr)
        for r in missing:
            print(f"  {r.name:32} {r.slug:32} {r.note}", file=sys.stderr)
    print(f"\nData source: Levels.fyi (https://www.levels.fyi)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
