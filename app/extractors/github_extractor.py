"""
Unstructured source extractor: GitHub profile URL.

Uses the public GitHub REST API (no auth required for public profiles;
60 req/hour unauthenticated, 5000/hour with GITHUB_TOKEN).

Extracts: name, bio (→ headline), location, email, repos (→ skills),
          languages (→ skills), blog (→ portfolio link).
"""

from __future__ import annotations
import os
import re
import time
from typing import Any

import httpx

from app.schema import FieldValue, RawExtraction
from app.normalizers.location import parse_location
from app.normalizers.skills import canonicalise_skill

SOURCE = "github_api"
_API_BASE = "https://api.github.com"
_TIMEOUT = 10.0
_LANG_CONFIDENCE = 0.80   # inferred from repos; solid but not self-declared
_PROFILE_CONFIDENCE = 0.90 # name/email on profile; very reliable


def _headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "")
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _fv(value: Any, method: str = "api", confidence: float = _PROFILE_CONFIDENCE) -> FieldValue:
    return FieldValue(value=value, source=SOURCE, method=method, confidence=confidence)


def _username_from_url(url: str) -> str | None:
    """Extract GitHub username from a profile URL or plain username."""
    if not url:
        return None
    url = url.strip().rstrip("/")
    # https://github.com/username  or  github.com/username  or  just username
    m = re.search(r"github\.com/([A-Za-z0-9_.-]+)", url, re.IGNORECASE)
    if m:
        return m.group(1)
    # Treat as bare username if no slashes
    if "/" not in url and "." not in url:
        return url
    return None


def extract_from_github(url: str) -> RawExtraction:
    """
    Fetch a GitHub profile and return a RawExtraction.
    On any network/API error, returns an empty RawExtraction so the
    pipeline continues with other sources.
    """
    ext = RawExtraction(source_name=SOURCE)
    username = _username_from_url(url)
    if not username:
        print(f"[github_extractor] Cannot parse username from: {url!r}")
        return ext

    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_headers()) as client:
            user_resp = client.get(f"{_API_BASE}/users/{username}")
            if user_resp.status_code == 404:
                print(f"[github_extractor] User not found: {username}")
                return ext
            if user_resp.status_code == 403:
                print("[github_extractor] Rate limited. Set GITHUB_TOKEN env var to increase limit.")
                return ext
            user_resp.raise_for_status()
            user = user_resp.json()

            # Fetch top 100 repos for language aggregation
            repos_resp = client.get(
                f"{_API_BASE}/users/{username}/repos",
                params={"per_page": 100, "sort": "pushed"},
            )
            repos = repos_resp.json() if repos_resp.status_code == 200 else []

    except httpx.RequestError as exc:
        print(f"[github_extractor] Network error: {exc}")
        return ext

    _populate(ext, user, repos, username)
    return ext


def _populate(ext: RawExtraction, user: dict, repos: list[dict], username: str) -> None:
    # Name
    name = user.get("name") or ""
    if name.strip():
        ext.full_name = _fv(name.strip())

    # Email (only if public)
    email = user.get("email") or ""
    if email.strip() and "@" in email:
        ext.emails.append(_fv(email.strip().lower()))

    # Location
    loc_raw = user.get("location") or ""
    if loc_raw.strip():
        ext.location = _fv(parse_location(loc_raw), method="api_parsed")

    # Bio → headline
    bio = user.get("bio") or ""
    if bio.strip():
        ext.headline = _fv(bio.strip(), confidence=0.80)

    # Blog / website → portfolio link
    blog = user.get("blog") or ""
    links: dict[str, Any] = {
        "linkedin": None,
        "github": f"https://github.com/{username}",
        "portfolio": blog.strip() if blog.strip() else None,
        "other": [],
    }
    ext.links = _fv(links, confidence=0.95)

    # Languages from repos → skills
    lang_counts: dict[str, int] = {}
    for repo in repos:
        if isinstance(repo, dict):
            lang = repo.get("language")
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1

    total_repos = sum(lang_counts.values()) or 1
    for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
        freq = count / total_repos
        # Only include languages that appear in >5% of repos to avoid noise
        if freq >= 0.05:
            skill_conf = min(0.95, _LANG_CONFIDENCE + freq * 0.15)
            ext.skills.append(_fv(
                {"name": canonicalise_skill(lang), "confidence": round(skill_conf, 2)},
                method="inferred_from_repos",
                confidence=skill_conf,
            ))

    # Topics across repos → additional skills
    topic_counts: dict[str, int] = {}
    for repo in repos:
        if isinstance(repo, dict):
            for topic in repo.get("topics", []):
                topic_counts[topic] = topic_counts.get(topic, 0) + 1

    # Skip generic/meta topics that aren't real skills
    _SKIP_TOPICS = {"config", "github-config", "dotfiles", "template", "awesome",
                    "hacktoberfest", "portfolio", "website", "blog"}
    seen_skills = {s.value["name"] for s in ext.skills}
    for topic, count in sorted(topic_counts.items(), key=lambda x: -x[1])[:15]:
        if topic.lower() in _SKIP_TOPICS:
            continue
        canonical = canonicalise_skill(topic)
        if canonical not in seen_skills:
            ext.skills.append(_fv(
                {"name": canonical, "confidence": 0.65},
                method="inferred_from_topics",
                confidence=0.65,
            ))
            seen_skills.add(canonical)
