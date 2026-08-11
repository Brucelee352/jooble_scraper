"""Data layer for the jooble_scraper Dash app.

Pure, importable module — no top-level execution, no interactive prompts.
Refactored from the legacy CLI ``scraper_source.py`` (which is left untouched).

Public interface (see INTERFACE.md for the full contract):

    fetch_jobs(days=7, limit=100, ...) -> pandas.DataFrame
    JoobleApiError

The API key is read from the ``KEY`` environment variable (or passed
explicitly via ``api_key=``). A ``.env`` file is honored if present via
python-dotenv, but the environment variable always wins.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

try:  # optional convenience: pick up a local .env if one exists
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

JOOBLE_URL_TEMPLATE = "https://jooble.org/api/{key}"
HEADERS = {"Content-type": "application/json"}

DEFAULT_KEYWORDS = "data engineer, analytics engineer"
DEFAULT_LOCATION = "United States"
DEFAULT_RADIUS = 500

#: Column order of the DataFrame returned by :func:`fetch_jobs`.
COLUMNS = [
    "id", "title", "company", "location", "salary", "salary_value",
    "job_type", "seniority", "min_years", "skills",
    "snippet", "link", "updated", "source", "lat", "lon",
]


class JoobleApiError(Exception):
    """Raised when the Jooble API cannot be reached or returns an error.

    Attributes:
        status_code: HTTP status code of the failing response, or None if
            the failure happened before a response was received (network
            error, missing key, retries exhausted).
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Offline geocoding: US state centroids + a handful of common cities.
# Rows that can't be matched get NaN lat/lon. No network calls.
# ---------------------------------------------------------------------------

_STATE_CENTROIDS = {
    "AL": (32.7794, -86.8287), "AK": (64.0685, -152.2782),
    "AZ": (34.2744, -111.6602), "AR": (34.8938, -92.4426),
    "CA": (37.1841, -119.4696), "CO": (38.9972, -105.5478),
    "CT": (41.6219, -72.7273), "DE": (38.9896, -75.5050),
    "FL": (28.6305, -82.4497), "GA": (32.6415, -83.4426),
    "HI": (20.2927, -156.3737), "ID": (44.3509, -114.6130),
    "IL": (40.0417, -89.1965), "IN": (39.8942, -86.2816),
    "IA": (42.0751, -93.4960), "KS": (38.4937, -98.3804),
    "KY": (37.5347, -85.3021), "LA": (31.0689, -91.9968),
    "ME": (45.3695, -69.2428), "MD": (39.0550, -76.7909),
    "MA": (42.2596, -71.8083), "MI": (44.3467, -85.4102),
    "MN": (46.2807, -94.3053), "MS": (32.7364, -89.6678),
    "MO": (38.3566, -92.4580), "MT": (47.0527, -109.6333),
    "NE": (41.5378, -99.7951), "NV": (39.3289, -116.6312),
    "NH": (43.6805, -71.5811), "NJ": (40.1907, -74.6728),
    "NM": (34.4071, -106.1126), "NY": (42.9538, -75.5268),
    "NC": (35.5557, -79.3877), "ND": (47.4501, -100.4659),
    "OH": (40.2862, -82.7937), "OK": (35.5889, -97.4943),
    "OR": (43.9336, -120.5583), "PA": (40.8781, -77.7996),
    "RI": (41.6762, -71.5562), "SC": (33.9169, -80.8964),
    "SD": (44.4443, -100.2263), "TN": (35.8580, -86.3505),
    "TX": (31.4757, -99.3312), "UT": (39.3055, -111.6703),
    "VT": (44.0687, -72.6658), "VA": (37.5215, -78.8537),
    "WA": (47.3826, -120.4472), "WV": (38.6409, -80.6227),
    "WI": (44.6243, -89.9941), "WY": (42.9957, -107.5512),
    "DC": (38.9101, -77.0147),
}

_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "washington dc": "DC",
    "washington, d.c.": "DC",
}

#: "city, ST" (lowercase) -> (lat, lon). Preferred over state centroids.
_CITY_COORDS = {
    "new york, ny": (40.7128, -74.0060),
    "los angeles, ca": (34.0522, -118.2437),
    "chicago, il": (41.8781, -87.6298),
    "houston, tx": (29.7604, -95.3698),
    "phoenix, az": (33.4484, -112.0740),
    "philadelphia, pa": (39.9526, -75.1652),
    "san antonio, tx": (29.4241, -98.4936),
    "san diego, ca": (32.7157, -117.1611),
    "dallas, tx": (32.7767, -96.7970),
    "austin, tx": (30.2672, -97.7431),
    "san jose, ca": (37.3382, -121.8863),
    "san francisco, ca": (37.7749, -122.4194),
    "seattle, wa": (47.6062, -122.3321),
    "denver, co": (39.7392, -104.9903),
    "boston, ma": (42.3601, -71.0589),
    "atlanta, ga": (33.7490, -84.3880),
    "miami, fl": (25.7617, -80.1918),
    "washington, dc": (38.9072, -77.0369),
    "charlotte, nc": (35.2271, -80.8431),
    "nashville, tn": (36.1627, -86.7816),
    "portland, or": (45.5152, -122.6784),
    "minneapolis, mn": (44.9778, -93.2650),
    "detroit, mi": (42.3314, -83.0458),
    "salt lake city, ut": (40.7608, -111.8910),
    "raleigh, nc": (35.7796, -78.6382),
    "pittsburgh, pa": (40.4406, -79.9959),
    "columbus, oh": (39.9612, -82.9988),
    "indianapolis, in": (39.7684, -86.1581),
    "kansas city, mo": (39.0997, -94.5786),
    "st. louis, mo": (38.6270, -90.1994),
    "tampa, fl": (27.9506, -82.4572),
    "orlando, fl": (28.5384, -81.3789),
    "baltimore, md": (39.2904, -76.6122),
    "las vegas, nv": (36.1699, -115.1398),
    "sacramento, ca": (38.5816, -121.4944),
    "san bernardino, ca": (34.1083, -117.2898),
    "cincinnati, oh": (39.1031, -84.5120),
    "cleveland, oh": (41.4993, -81.6944),
    "milwaukee, wi": (43.0389, -87.9065),
    "oklahoma city, ok": (35.4676, -97.5164),
    "new orleans, la": (29.9511, -90.0715),
    "memphis, tn": (35.1495, -90.0490),
    "louisville, ky": (38.2527, -85.7585),
    "richmond, va": (37.5407, -77.4360),
    "jacksonville, fl": (30.3322, -81.6557),
    "fort worth, tx": (32.7555, -97.3308),
    "el paso, tx": (31.7619, -106.4850),
    "albuquerque, nm": (35.0844, -106.6504),
    "tucson, az": (32.2226, -110.9747),
    "omaha, ne": (41.2565, -95.9345),
    "boise, id": (43.6150, -116.2023),
    "anchorage, ak": (61.2181, -149.9003),
    "honolulu, hi": (21.3069, -157.8583),
    "hartford, ct": (41.7658, -72.6734),
    "providence, ri": (41.8240, -71.4128),
    "buffalo, ny": (42.8864, -78.8784),
    "des moines, ia": (41.5868, -93.6250),
    "birmingham, al": (33.5186, -86.8104),
    "charleston, sc": (32.7765, -79.9311),
}


def geocode_location(location: str | None) -> tuple[float, float]:
    """Best-effort offline geocode of a Jooble location string.

    Tries a small "City, ST" lookup first, then falls back to the centroid
    of the US state named or abbreviated in the string. Returns
    ``(nan, nan)`` when nothing matches (e.g. "Remote", non-US, empty).
    """
    nan = float("nan")
    if not location or not isinstance(location, str):
        return (nan, nan)

    text = location.strip().lower()
    if not text:
        return (nan, nan)

    # Exact city match ("Austin, TX")
    if text in _CITY_COORDS:
        return _CITY_COORDS[text]

    # Normalize full state name to abbreviation in a "City, State" string
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) >= 2:
        city, state = parts[0], parts[-1]
        abbrev = _STATE_NAMES.get(state, state.upper() if len(state) == 2 else None)
        if abbrev:
            hit = _CITY_COORDS.get(f"{city}, {abbrev.lower()}")
            if hit:
                return hit
            if abbrev in _STATE_CENTROIDS:
                return _STATE_CENTROIDS[abbrev]

    # Bare state name or abbreviation ("Texas", "TX")
    abbrev = _STATE_NAMES.get(text)
    if abbrev is None and len(text) == 2 and text.upper() in _STATE_CENTROIDS:
        abbrev = text.upper()
    if abbrev:
        return _STATE_CENTROIDS[abbrev]

    return (nan, nan)


# ---------------------------------------------------------------------------
# Tier-1 textual analysis: pull light "experience" signal out of the title
# and snippet we already have. No network calls, no full-JD scraping — the
# Jooble snippet is a truncated excerpt, so treat every result as best-effort
# (None / [] when nothing is found, surfaced as "Unknown" in the UI).
# ---------------------------------------------------------------------------

#: Seniority labels in priority order: the first pattern that hits the title
#: (then the snippet) wins, so more specific/senior levels are checked first.
_SENIORITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Intern", re.compile(r"\bintern(ship)?\b", re.I)),
    ("Principal", re.compile(r"\bprincipal\b", re.I)),
    ("Staff", re.compile(r"\bstaff\b", re.I)),
    ("Lead", re.compile(r"\b(?:team\s+)?lead\b", re.I)),
    ("Senior", re.compile(r"\b(?:senior|sr\.?)\b|\biii\b", re.I)),
    ("Mid", re.compile(r"\b(?:mid[-\s]?level|intermediate|ii)\b", re.I)),
    ("Junior", re.compile(
        r"\b(?:junior|jr\.?|entry[-\s]?level|entry|graduate|new\s+grad)\b",
        re.I)),
]

#: "5+ years", "3-5 yrs", "at least 2 years", etc. The first captured number
#: is the low end of the requirement.
_YEARS_RE = re.compile(
    r"(\d{1,2})\s*(?:\+|-|–|to)?\s*\d{0,2}\s*\+?\s*(?:years?|yrs?)\b",
    re.I,
)

#: Default skill vocabulary (canonical spelling). Matched case-insensitively
#: on word boundaries. Callers can pass their own vocab to ``extract_skills``.
DEFAULT_SKILLS = [
    "Python", "SQL", "R", "Java", "Scala", "Go", "JavaScript", "TypeScript",
    "dbt", "Airflow", "Spark", "Kafka", "Hadoop", "Snowflake", "Redshift",
    "BigQuery", "Databricks", "Postgres", "MySQL", "MongoDB", "Kubernetes",
    "Docker", "AWS", "Azure", "GCP", "Terraform", "Tableau", "Power BI",
    "Looker", "Pandas", "PyTorch", "TensorFlow", "Excel", "SAS",
]

_SKILL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(r"\b" + re.escape(name) + r"\b", re.I))
    for name in DEFAULT_SKILLS
]


def parse_seniority(title: str | None, snippet: str | None = None) -> str | None:
    """Best-effort seniority level from a job title (snippet as fallback).

    Returns one of the labels in ``_SENIORITY_PATTERNS`` (e.g. "Senior",
    "Junior") or None when nothing matches. The title is the primary signal;
    the snippet is only consulted if the title is inconclusive.
    """
    for text in (title or "", snippet or ""):
        for label, pattern in _SENIORITY_PATTERNS:
            if pattern.search(text):
                return label
    return None


def parse_min_years(title: str | None, snippet: str | None = None) -> int | None:
    """Minimum years of experience mentioned in the title/snippet, or None.

    Scans for phrases like "5+ years" / "3-5 yrs" and returns the smallest
    low-end value found (so "5+ yrs Python, 3+ yrs SQL" yields 3). Values
    outside 1-30 are ignored as noise (dates, unrelated numbers).
    """
    best: int | None = None
    for text in (f"{title or ''} {snippet or ''}",):
        for match in _YEARS_RE.finditer(text):
            n = int(match.group(1))
            if 1 <= n <= 30:
                best = n if best is None else min(best, n)
    return best


def extract_skills(text: str | None,
                   vocab: list[tuple[str, re.Pattern[str]]] | None = None
                   ) -> list[str]:
    """Canonical skill names found in ``text`` (case-insensitive), in vocab
    order. Defaults to :data:`DEFAULT_SKILLS`. Returns [] when none match.
    """
    if not text:
        return []
    patterns = vocab if vocab is not None else _SKILL_PATTERNS
    return [name for name, pattern in patterns if pattern.search(text)]


# ---------------------------------------------------------------------------
# Salary parsing: turn Jooble's messy free-text ``salary`` into an estimated
# annual USD figure, or None when it can't be read. Jooble salary strings are
# wildly inconsistent ("$90k-$120k", "$45/hr", "$8,000 per month", "" ...), so
# this is best-effort: it normalizes hourly/daily/weekly/monthly to a yearly
# amount and drops anything outside a sane band.
# ---------------------------------------------------------------------------

#: One numeric token, optionally $-prefixed, with thousands separators and an
#: optional k/m magnitude suffix ("120,000", "90k", "1.2m").
_SALARY_NUM_RE = re.compile(
    r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([km])?", re.I)

#: Period keyword -> multiplier to annualize. Checked in this order; the first
#: match wins. Hours assume 40h * 52wk = 2080; days assume ~260 working days.
_SALARY_PERIODS = [
    (re.compile(r"(?:per\s*hour|hourly|/\s*hr|/\s*hour|an?\s+hour|p/?h|\bhr\b|\bhour\b)", re.I), 2080.0),
    (re.compile(r"(?:per\s*day|daily|/\s*day|a\s+day|\bday\b)", re.I), 260.0),
    (re.compile(r"(?:per\s*week|weekly|/\s*w(?:k|eek)|a\s+week|\bweek\b|\bwk\b)", re.I), 52.0),
    (re.compile(r"(?:per\s*month|monthly|/\s*mo(?:nth)?|a\s+month|\bmonth\b|\bmo\b)", re.I), 12.0),
    (re.compile(r"(?:per\s*year|per\s*annum|annually|annual|yearly|/\s*y(?:r|ear)|a\s+year|\byear\b|\byr\b|\bp\.?a\.?\b)", re.I), 1.0),
]

#: Reject annualized results outside this band as noise / misparsed.
_SALARY_MIN, _SALARY_MAX = 10_000.0, 1_000_000.0


def parse_salary(text: str | None) -> float | None:
    """Best-effort estimated annual USD salary from a free-text salary string.

    Extracts the numeric value(s) (honoring ``k``/``m`` suffixes and thousands
    commas), takes the midpoint of a range, then annualizes using an explicit
    period keyword ("per hour", "monthly", ...) or, absent one, a magnitude
    heuristic (a bare value under 1,000 is treated as an hourly rate). Returns
    None for blank/unparseable input or results outside a sane annual band.
    """
    if not text or not isinstance(text, str):
        return None
    s = text.strip().lower()
    if not s:
        return None

    nums: list[float] = []
    for match in _SALARY_NUM_RE.finditer(s):
        raw = match.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        suffix = (match.group(2) or "").lower()
        if suffix == "k":
            val *= 1_000
        elif suffix == "m":
            val *= 1_000_000
        nums.append(val)
    if not nums:
        return None

    base = (nums[0] + nums[1]) / 2.0 if len(nums) >= 2 else nums[0]

    factor = next((f for rx, f in _SALARY_PERIODS if rx.search(s)), None)
    if factor is None:
        factor = 2080.0 if base < 1_000 else 1.0  # bare small value ~ hourly

    annual = base * factor
    if annual < _SALARY_MIN or annual > _SALARY_MAX:
        return None
    return round(annual, 2)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _resolve_api_key(api_key: str | None) -> str:
    if api_key:
        return api_key
    key = os.environ.get("KEY")
    if not key and load_dotenv is not None:
        load_dotenv()  # picks up ./.env if present; env vars still win
        key = os.environ.get("KEY")
    if not key:
        raise JoobleApiError(
            "Missing Jooble API key: set the KEY environment variable "
            "or pass api_key=."
        )
    return key


def _fetch_page(url: str, params: dict, timeout: float,
                max_retries: int, retry_wait: float) -> dict:
    """POST one page to the Jooble API with bounded retry/backoff.

    Retries (up to ``max_retries`` extra attempts, sleeping ``retry_wait``
    seconds between attempts) on HTTP 429 and network errors. Raises
    JoobleApiError on 403, other non-200 statuses, or exhausted retries.
    """
    last_error: str = "unknown error"
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(url, timeout=timeout,
                                     headers=HEADERS, json=params)
        except requests.exceptions.RequestException as exc:
            last_error = f"network error: {exc}"
        else:
            if response.status_code == 200:
                return response.json()
            if response.status_code == 403:
                raise JoobleApiError(
                    "Jooble API rejected the request (HTTP 403): the API "
                    "key is invalid or expired.", status_code=403)
            if response.status_code == 429:
                last_error = "rate limited (HTTP 429)"
            else:
                raise JoobleApiError(
                    f"Jooble API error (HTTP {response.status_code}).",
                    status_code=response.status_code)
        if attempt < max_retries:
            time.sleep(retry_wait)
    raise JoobleApiError(
        f"Jooble API request failed after {max_retries + 1} attempts: "
        f"{last_error}")


def _empty_frame() -> pd.DataFrame:
    df = pd.DataFrame({col: pd.Series(dtype="object") for col in COLUMNS})
    df["updated"] = pd.Series(dtype="datetime64[ns]")
    df["lat"] = pd.Series(dtype="float64")
    df["lon"] = pd.Series(dtype="float64")
    return df


def fetch_jobs(
    days: int = 7,
    limit: int | None = 100,
    keywords: str = DEFAULT_KEYWORDS,
    location: str = DEFAULT_LOCATION,
    radius: int = DEFAULT_RADIUS,
    *,
    strict: bool = False,
    api_key: str | None = None,
    max_pages: int = 10,
    max_retries: int = 2,
    retry_wait: float = 2.0,
    timeout: float = 10.0,
) -> pd.DataFrame:
    """Fetch recent job postings from the Jooble API as a DataFrame.

    Paginates the Jooble search endpoint until ``limit`` jobs updated within
    the last ``days`` days have been collected, the API runs out of results,
    or ``max_pages`` pages have been fetched. ``limit`` is a **cap**, never a
    padding target — if only 4 jobs match the criteria, 4 rows come back.
    Pass ``limit=None`` for no cap (pagination is still bounded by
    ``max_pages`` and empty-page detection). The recency filter is applied
    client-side on the ``updated`` timestamp (Jooble has no reliable
    server-side date filter). Pass ``days=2`` for a 2-day window, etc.

    ``strict=True`` additionally keeps only jobs where at least one of the
    comma-separated phrases in ``keywords`` appears (case-insensitive,
    substring match) in the job's title or snippet — trimming Jooble's
    fuzzy matches. Duplicate job ids across pages are always dropped
    (first occurrence wins).

    Returns a DataFrame with columns (in order):
        id (str — sign preserved), title, company, location, salary (str,
        raw), salary_value (float or None — best-effort estimated annual USD
        parsed from the raw salary text), job_type (str), seniority (str or
        None — best-effort level parsed from the title/snippet), min_years
        (int or None — minimum years of experience mentioned), skills
        (list[str] — matched skill keywords), snippet, link (str), updated
        (datetime64[ns], naive), source (str), lat, lon (float64, NaN when
        the location string cannot be geocoded offline).

    Raises JoobleApiError on a missing/invalid API key (403), other HTTP
    errors, or when retries are exhausted (429 / network failures).
    Retry behavior is UI-friendly by default: ``max_retries=2`` extra
    attempts with ``retry_wait=2.0`` seconds between them.
    """
    key = _resolve_api_key(api_key)
    url = JOOBLE_URL_TEMPLATE.format(key=key)
    cutoff = datetime.now() - timedelta(days=days)
    phrases = [p.strip().lower()
               for p in keywords.split(",") if p.strip()] if strict else []

    rows: list[dict] = []
    seen_ids: set[str] = set()
    for page in range(1, max_pages + 1):
        params = {
            "keywords": keywords,
            "location": location,
            "radius": str(radius),
            "page": str(page),
            "companysearch": "false",
        }
        data = _fetch_page(url, params, timeout, max_retries, retry_wait)
        jobs = data.get("jobs") or []
        if not jobs:
            break

        for job in jobs:
            updated = pd.to_datetime(job.get("updated"), errors="coerce")
            if isinstance(updated, pd.Timestamp) and updated.tzinfo is not None:
                updated = updated.tz_localize(None)
            if pd.isna(updated) or updated < cutoff:
                continue
            job_id = str(job.get("id", ""))
            if job_id in seen_ids:
                continue
            if phrases:
                haystack = (f"{job.get('title', '')} "
                            f"{job.get('snippet', '')}").lower()
                if not any(p in haystack for p in phrases):
                    continue
            loc = job.get("location", "")
            lat, lon = geocode_location(loc)
            title = job.get("title", "")
            snippet = job.get("snippet", "")
            seen_ids.add(job_id)
            rows.append({
                "id": job_id,
                "title": title,
                "company": job.get("company", ""),
                "location": loc,
                "salary": job.get("salary", ""),
                "salary_value": parse_salary(job.get("salary", "")),
                "job_type": job.get("type", ""),
                "seniority": parse_seniority(title, snippet),
                "min_years": parse_min_years(title, snippet),
                "skills": extract_skills(f"{title} {snippet}"),
                "snippet": snippet,
                "link": job.get("link", ""),
                "updated": updated,
                "source": job.get("source", ""),
                "lat": lat,
                "lon": lon,
            })
            if limit is not None and len(rows) >= limit:
                break
        if limit is not None and len(rows) >= limit:
            break

    if not rows:
        return _empty_frame()

    df = pd.DataFrame(rows, columns=COLUMNS)
    df["updated"] = pd.to_datetime(df["updated"])
    df["lat"] = df["lat"].astype("float64")
    df["lon"] = df["lon"].astype("float64")
    return df
