from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from jobwatch.models import Job

MODEL = "claude-opus-5"
BATCH_SIZE = 50
MAX_TOKENS = 16000
# A large batch occasionally comes back missing a listing. Re-ask for just the
# gaps rather than failing a whole run over one omission.
MAX_RETRIES = 2

DEFAULT_CACHE_PATH = Path("state") / "filter_cache.json"

# Hand-maintained summary of the resume under Senior_Software_Engineer_07_26/.
# Kept as a constant rather than parsed from the LaTeX source: the resume is a
# document that gets restructured, and a broken parse would silently change
# what the filter keeps. Edit this when the target role changes.
CANDIDATE_PROFILE = """\
Senior software engineer, ~8 years experience, currently Senior SWE at a
returns/logistics company.

Core strengths: backend service work in Go, TypeScript, and Python —
microservices, event-driven architecture (SQS/Lambda), REST and gRPC APIs,
AWS, PostgreSQL/DynamoDB/Redshift, rate limiting, data pipelines, and a
large production datastore migration.

Also comfortable full-stack (React, Cypress) and has earlier computer-vision
and ML research experience, plus production LLM integration work.

Targeting: general backend and full-stack software engineering roles at the
senior or staff level.

NOT looking for: dedicated infrastructure/platform/SRE roles, data engineering
or data science roles, ML/research engineer roles, security engineering,
engineering management, or anything that is not primarily an
individual-contributor software engineering job.
"""

INSTRUCTIONS = """\
You are screening newly posted job listings for the candidate described below.

<candidate>
{profile}
</candidate>

For each listing, decide whether the candidate should see it in their daily
alert digest. Return relevant=true only when the role is a general backend or
full-stack software engineering IC role at roughly the senior or staff level.

Judge the actual job, not the wording. Companies name the same job differently
("Software Engineer", "Member of Technical Staff", "Staff Engineer", "Backend
Engineer"), and a team name after a comma usually describes which product the
role sits on rather than changing the discipline. Use what you know about the
company and the product area named in the title.

Mark relevant=false for specialised tracks the candidate is not targeting
(dedicated infrastructure/platform/SRE, data engineering, data science,
ML/research engineering, security), for management or non-engineering roles,
and for levels well outside the band (internships, new grad, principal and
above). An unleveled title such as plain "Software Engineer" is fine — many
companies do not put a level in the title.

There is no manual review step: anything you mark relevant=false disappears
without the candidate ever seeing it. When a listing is genuinely borderline,
prefer relevant=true.

Give a reason of at most 10 words for every listing. Return one verdict per
listing, using the index shown.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["index", "relevant", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


class FilterError(Exception):
    """Raised when role-fit classification could not be completed."""


@dataclass(frozen=True)
class Verdict:
    relevant: bool
    reason: str


def cache_key(job: Job) -> str:
    return f"{job.company}|{job.title}"


def prompt_fingerprint() -> str:
    """Identifies the prompt that produced a cached verdict. Editing the profile
    or instructions changes this, which discards verdicts judged under the old
    criteria instead of leaving them to contradict the new ones."""
    material = f"{MODEL}\n{CANDIDATE_PROFILE}\n{INSTRUCTIONS}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def load_cache(path: Path = DEFAULT_CACHE_PATH) -> dict[str, Verdict]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}  # a corrupt cache costs one re-classification, not a failed run
    if not isinstance(raw, dict) or raw.get("prompt") != prompt_fingerprint():
        return {}
    verdicts = raw.get("verdicts")
    if not isinstance(verdicts, dict):
        return {}
    return {
        key: Verdict(bool(value["relevant"]), str(value.get("reason", "")))
        for key, value in verdicts.items()
        if isinstance(value, dict) and "relevant" in value
    }


def save_cache(cache: dict[str, Verdict], path: Path = DEFAULT_CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "prompt": prompt_fingerprint(),
        "verdicts": {
            key: {"relevant": verdict.relevant, "reason": verdict.reason}
            for key, verdict in cache.items()
        },
    }
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp_name, path)
    except BaseException:
        os.unlink(tmp_name)
        raise


def _batches(items: list[Job], size: int) -> Iterable[list[Job]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def classify_with_claude(jobs: list[Job], _attempt: int = 0) -> list[Verdict]:
    """Classify one batch of jobs. Raises FilterError on any failure."""
    import anthropic

    client = anthropic.Anthropic()
    listings = "\n".join(
        f"{index}. {job.title} — {job.company}"
        + (f" ({job.location})" if job.location else "")
        for index, job in enumerate(jobs)
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            system=INSTRUCTIONS.format(profile=CANDIDATE_PROFILE),
            messages=[{"role": "user", "content": listings}],
        )
    except anthropic.AnthropicError as exc:
        raise FilterError(f"classification request failed: {exc}") from exc

    if response.stop_reason == "refusal":
        raise FilterError("classification refused by the model")
    if response.stop_reason == "max_tokens":
        raise FilterError("classification truncated; lower BATCH_SIZE")

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise FilterError("classification returned no text block")

    try:
        verdicts = json.loads(text)["verdicts"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise FilterError(f"could not parse classification response: {exc}") from exc

    by_index = {
        int(item["index"]): Verdict(bool(item["relevant"]), str(item["reason"]))
        for item in verdicts
    }
    missing = [index for index in range(len(jobs)) if index not in by_index]
    if missing:
        if _attempt >= MAX_RETRIES:
            raise FilterError(
                f"classification omitted {len(missing)} of {len(jobs)} listings "
                f"after {_attempt + 1} attempts"
            )
        retried = classify_with_claude([jobs[index] for index in missing], _attempt + 1)
        for index, verdict in zip(missing, retried):
            by_index[index] = verdict
    return [by_index[index] for index in range(len(jobs))]


def classify(
    jobs: list[Job],
    *,
    cache_path: Path | None = DEFAULT_CACHE_PATH,
    classifier: Callable[[list[Job]], list[Verdict]] | None = None,
) -> dict[str, Verdict]:
    """Return a verdict per job, keyed by cache_key. Cached titles are not re-sent."""
    # Resolved here rather than as a default argument so tests can patch the
    # module attribute and never reach the network.
    classifier = classifier or classify_with_claude
    cache = load_cache(cache_path) if cache_path else {}

    pending: list[Job] = []
    seen: set[str] = set()
    for job in jobs:
        key = cache_key(job)
        if key in cache or key in seen:
            continue
        seen.add(key)
        pending.append(job)

    if pending:
        for batch in _batches(pending, BATCH_SIZE):
            for job, verdict in zip(batch, classifier(batch)):
                cache[cache_key(job)] = verdict
        if cache_path:
            save_cache(cache, cache_path)

    return {cache_key(job): cache[cache_key(job)] for job in jobs}


def apply_filters(
    jobs: list[Job],
    *,
    cache_path: Path | None = DEFAULT_CACHE_PATH,
    classifier: Callable[[list[Job]], list[Verdict]] | None = None,
    on_drop: Callable[[Job, Verdict], None] | None = None,
) -> list[Job]:
    """Report-time role-fit filter. Snapshots always store every job a company
    posts, so widening this filter later does not lose history.

    Raises FilterError if classification fails — the caller decides what to do
    rather than silently dropping or silently keeping everything.
    """
    if not jobs:
        return []

    verdicts = classify(jobs, cache_path=cache_path, classifier=classifier)

    kept = []
    for job in jobs:
        verdict = verdicts[cache_key(job)]
        if verdict.relevant:
            kept.append(job)
        elif on_drop is not None:
            on_drop(job, verdict)
    return kept
