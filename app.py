"""Dash UI for jooble_scraper.

Fetch dialog -> jooble_data.fetch_jobs -> DataTable + map. No network calls
happen at import time. Each page load runs one fetch of the default search
(initial_fetch: DEFAULT_KEYWORDS / DEFAULT_LOCATION / DEFAULT_DAYS) so the
dashboard opens populated; further fetches run from the Fetch dialog.
Run with:

    uv run app.py        (or: .venv/Scripts/python app.py)
"""

import os
import smtplib

import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import sample_colorscale
from dash import (Dash, Input, Output, State, dash_table, dcc, html,
                  no_update)

# Dash 4.5 bundles React 19.2.4 but still serves React 18.3.1 by default, and
# Dash Mantine Components v3 refuses to render on React 18 ("DMC v3 requires
# React 19"). Opt in here; this must run before the Dash app is instantiated.
dash._dash_renderer._set_react_version("19.2.4")

from jooble_data import (
    DEFAULT_DAYS,
    DEFAULT_KEYWORDS,
    DEFAULT_LOCATION,
    JoobleApiError,
    fetch_jobs,
    _STATE_CENTROIDS,
    _STATE_NAMES,
)
import mailer

# Light indigo / black / silver theme.
INDIGO = "#5661c9"          # accent: buttons, links, map marker
INDIGO_DARK = "#434db3"     # hover/active
INDIGO_TINT = "#e9ebfa"     # light indigo accent surfaces
SILVER = "#c9ccd8"          # borders
SILVER_SURFACE = "#f4f5f8"  # cards, modal, table header
PAGE_BG = "#eef0f7"
INK = "#111111"
FONT_STACK = "'Sora', 'Segoe UI', system-ui, sans-serif"

# Single-series marker color (indigo, on light map tiles).
MARKER_COLOR = INDIGO

REMOTE_LOCATION = "Remote" 
MAX_DAYS = 21

TABLE_COLUMNS = [
    {"name": "Job Title", "id": "title"},
    {"name": "Company", "id": "company"},
    {"name": "Location", "id": "location"},
    {"name": "Salary", "id": "salary"},
    {"name": "Job Type", "id": "job_type"},
    {"name": "Seniority", "id": "seniority"},
    {"name": "Min Yrs Exp", "id": "min_years"},
    {"name": "Skills", "id": "skills_str"},
    {"name": "Last Updated", "id": "updated"},
    {"name": "Link", "id": "link_md", "presentation": "markdown"},
]

US_CENTER = {"lat": 39.5, "lon": -98.35}


def normalize_search(keywords, location):
    """Blank/whitespace-only inputs fall back to the data-layer defaults."""
    keywords = (keywords or "").strip() or DEFAULT_KEYWORDS
    location = (location or "").strip() or DEFAULT_LOCATION
    return keywords, location


def clamp_days(days) -> int:
    """Coerce the recency window to an int in [1, MAX_DAYS]."""
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 7
    return max(1, min(days, MAX_DAYS))


def do_fetch(days: int, keywords: str | None = None,
             location: str | None = None, remote: bool = False):
    """Core fetch logic, kept as a plain function so it is testable.

    Returns (records, error_message): exactly one of the two is not None.
    `records` is a list of dicts ready for dcc.Store / DataTable.
    """
    days = clamp_days(days)
    keywords, location = normalize_search(keywords, location)
    if remote:
        location = REMOTE_LOCATION
    try:
        df = fetch_jobs(days=days, limit=None, keywords=keywords,
                        location=location, strict=True)
    except JoobleApiError as exc:
        msg = str(exc)
        if exc.status_code in (None, 401, 403):
            msg += (
                " Check that the KEY environment variable is set to a "
                "valid Jooble API key (https://jooble.org/api/about)."
            )
        return None, msg

    df = df.copy()
    df["updated"] = df["updated"].dt.strftime("%Y-%m-%d %H:%M")
    df["link_md"] = [
        f"[Open]({u})" if u else "" for u in df["link"].fillna("")
    ]
    df["skills_str"] = [
        ", ".join(s) if isinstance(s, list) else "" for s in df["skills"]
    ]
    # Whole years ("5", not "5.0"); nullable so missing stays missing.
    df["min_years"] = pd.to_numeric(df["min_years"]).round().astype("Int64")
    # pandas 3 infers a string dtype for text columns and stores missing
    # values (e.g. seniority=None) as NaN. Hand dcc.Store / DataTable plain
    # None instead so blanks serialize as JSON null and render empty.
    df = df.astype(object).where(df.notna(), None)
    return df.to_dict("records"), None


def build_map(df: pd.DataFrame) -> tuple[go.Figure, int]:
    """Scatter map of geocoded rows. Returns (figure, n_unmapped)."""
    fig = go.Figure()
    if df.empty:
        mappable = df
        unmapped = 0
    else:
        mappable = df.dropna(subset=["lat", "lon"])
        unmapped = len(df) - len(mappable)

    if not mappable.empty:
        fig.add_trace(
            go.Scattermap(
                lat=mappable["lat"],
                lon=mappable["lon"],
                mode="markers",
                marker={"size": 12, "color": MARKER_COLOR, "opacity": 0.85},
                customdata=mappable[
                    ["title", "company", "location", "id"]
                ].values,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "%{customdata[1]}<br>"
                    "%{customdata[2]}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        map={"style": "open-street-map", "center": US_CENTER, "zoom": 3},
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        showlegend=False,
    )
    return fig, unmapped


# ---------------------------------------------------------------------------
# Insight charts. Each takes the jobs DataFrame and returns a styled figure;
# all guard against an empty/missing frame the same way build_map does.
# ---------------------------------------------------------------------------

def _ramp(name: str, lo: float, hi: float, steps: int = 7) -> list[str]:
    """Sample the lo..hi slice of a named plotly colorscale (append "_r" to
    reverse). Clipping keeps the light end visible on the white cards and the
    dark end short of near-black."""
    return sample_colorscale(
        name, [lo + (hi - lo) * i / (steps - 1) for i in range(steps)])


# Per-chart sequential colorscales: each bar is shaded by its value (low =
# light, high = deep). Slot order is fixed so a chart keeps its scale across
# fetches; append new slots at the end only.
CHART_SCALES = [
    _ramp("PuBu", 0.15, 0.75),  # 0 top companies (yellow end cut: low contrast)
    _ramp("ice", 0.35, 0.95),  # 1 postings per day
    _ramp("ice_r", 0.25, 0.90),    # 2 jobs by state (reversed: high = dark)
    _ramp("dense", 0.20, 0.90),    # 3 top skills
    _ramp("PuBu", 0.35, 0.95),     # 4 spare
    _ramp("PuRd", 0.35, 0.95),     # 5 spare
]
SCALE_COMPANIES, SCALE_TIMELINE, SCALE_STATES, SCALE_SKILLS = CHART_SCALES[:4]

# Sequential ramp for the one chart where color carries a value: median
# salary in the salary bubble chart. plotly's ColorBrewer "BuPu" (blue ->
# purple), clipped to its upper 35-95% so the light end stays visible on
# white and the dark end stays short of near-black.
SALARY_SCALE = sample_colorscale(
    "BuPu", [0.35 + 0.60 * i / 6 for i in range(7)])

# Indigo ramp for the dashboard *chrome* (title strip, buttons, heading bars).
GRADIENT_INDIGO = [
    "#e9ebfa",  # light periwinkle (INDIGO_TINT)
    "#b8bdec",
    "#8b93e8",
    "#5661c9",  # base indigo (brand)
    "#434db3",
    "#2f378f",
    "#1d2260",  # deep indigo
]

# CSS gradient strings for the dashboard chrome, built from GRADIENT_INDIGO.
_GRAD_STOPS = ", ".join(GRADIENT_INDIGO)
GRADIENT_STRIP = f"linear-gradient(90deg, {_GRAD_STOPS})"          # full ramp
GRADIENT_FILL = "linear-gradient(135deg, #5661c9, #2f378f)"        # solid btn
GRADIENT_FILL_HOVER = "linear-gradient(135deg, #434db3, #1d2260)"  # btn hover
GRADIENT_TITLE = "linear-gradient(135deg, #5661c9, #2f378f 55%, #1d2260)"
GRADIENT_ACCENT = "linear-gradient(180deg, #5661c9, #1d2260)"      # heading bar


def _bar_marker(values, scale: list[str]) -> dict:
    """Bar fill shaded by value along `scale`, with a thin white edge so
    adjacent bars keep a visible gap on the white chart cards."""
    return {
        "color": list(values),
        "colorscale": scale,
        "cmin": 0,  # anchor at zero so a small bar reads as small, not mid-scale
        "line": {"width": 1, "color": "#ffffff"},
    }


def _style_chart(fig: go.Figure, title: str) -> go.Figure:
    """Apply the shared indigo/silver theme to an insight chart."""
    fig.update_layout(
        title={"text": title, "font": {"color": INK, "size": 15}},
        font={"family": FONT_STACK, "color": INK},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        barcornerradius=4,   # rounded data-ends on every bar chart
        bargap=0.25,
        margin={"l": 10, "r": 10, "t": 40, "b": 10},
        showlegend=False,
    )
    return fig


def _empty_chart(title: str) -> go.Figure:
    """Blank placeholder shown before any fetch / when a field is all-empty."""
    fig = go.Figure()
    fig.add_annotation(text="No data", showarrow=False,
                       font={"color": "#8a8fa3"})
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _style_chart(fig, title)


def state_for_location(location) -> str | None:
    """Best-effort US state abbreviation from a Jooble location string.

    Mirrors the parsing in jooble_data.geocode_location but returns the
    state code (e.g. "TX") instead of coordinates. None when nothing matches
    (Remote, non-US, empty).
    """
    if not location or not isinstance(location, str):
        return None

    text = location.strip().lower()

    if not text:
        return None

    parts = [p.strip() for p in text.split(",") if p.strip()]

    if len(parts) >= 2:
        state = parts[-1]
        abbrev = _STATE_NAMES.get(
            state, state.upper() if len(state) == 2 else None)
        if abbrev in _STATE_CENTROIDS:
            return abbrev
    abbrev = _STATE_NAMES.get(text)
    if abbrev is None and len(text) == 2 and text.upper() in _STATE_CENTROIDS:
        abbrev = text.upper()
    return abbrev if abbrev in _STATE_CENTROIDS else None


def build_company_bar(df: pd.DataFrame) -> go.Figure:
    """Top hiring companies by job count (horizontal bar)."""
    title = "Top companies"
    if df.empty or "company" not in df:
        return _empty_chart(title)
    counts = (df["company"].replace("", pd.NA).dropna()
              .value_counts().head(10))
    if counts.empty:
        return _empty_chart(title)
    counts = counts.iloc[::-1]  # largest on top for a horizontal bar
    fig = go.Figure(go.Bar(
        x=counts.values, y=counts.index, orientation="h",
        marker=_bar_marker(counts.values, SCALE_COMPANIES),
    ))
    fig.update_xaxes(gridcolor=SILVER)
    return _style_chart(fig, title)


def build_timeline(df: pd.DataFrame) -> go.Figure:
    """Postings per calendar day over the recency window (bar)."""
    title = "Postings per day"
    if df.empty or "updated" not in df:
        return _empty_chart(title)
    updated = pd.to_datetime(df["updated"], errors="coerce").dropna()
    if updated.empty:
        return _empty_chart(title)
    per_day = updated.dt.floor("D").value_counts().sort_index()
    fig = go.Figure(go.Bar(
        x=per_day.index, y=per_day.values,
        marker=_bar_marker(per_day.values, SCALE_TIMELINE),
    ))
    fig.update_xaxes(gridcolor=SILVER)
    fig.update_yaxes(gridcolor=SILVER)
    return _style_chart(fig, title)


def build_state_bar(df: pd.DataFrame) -> go.Figure:
    """Jobs per US state (bar). Rows that don't geocode are omitted."""
    title = "Jobs by state"
    if df.empty or "location" not in df:
        return _empty_chart(title)
    states = df["location"].map(state_for_location).dropna()
    counts = states.value_counts().head(12)
    if counts.empty:
        return _empty_chart(title)
    fig = go.Figure(go.Bar(
        x=counts.index, y=counts.values,
        marker=_bar_marker(counts.values, SCALE_STATES),
    ))
    fig.update_yaxes(gridcolor=SILVER)
    return _style_chart(fig, title)


def build_salary_bubble(df: pd.DataFrame) -> go.Figure:
    """Median annualized salary per state, as a bubble chart.

    Salary is sparse/messy free text; jooble_data.parse_salary estimates an
    annual USD figure (the ``salary_value`` column). Rows without a usable
    salary or an identifiable US state are dropped. Each bubble is one state
    plotted at its median salary (Y) vs. state (X); the bubble size scales
    with how many salaried jobs back that state's figure, so a big bubble =
    more confidence. Bubble color also encodes the median (SALARY_SCALE,
    light = lower, deep plum = higher), with a colorbar as its key.
    """
    title = "Median salary by state"
    if df.empty or "salary_value" not in df or "location" not in df:
        return _empty_chart(title)
    work = pd.DataFrame({
        "state": df["location"].map(state_for_location),
        "salary": pd.to_numeric(df["salary_value"], errors="coerce"),
    }).dropna(subset=["state", "salary"])
    if work.empty:
        return _empty_chart(title)
    agg = (work.groupby("state")["salary"]
           .agg(median="median", count="count")
           .reset_index().sort_values("median"))
    counts = agg["count"].to_numpy()
    cmax = counts.max()
    # Bubble diameter in px (16..52), scaled by the per-state sample count.
    if cmax <= 1:
        sizes = [22.0] * len(counts)
    else:
        sizes = [16 + 36 * (c - 1) / (cmax - 1) for c in counts]
    fig = go.Figure(go.Scatter(
        x=agg["state"], y=agg["median"], mode="markers",
        marker={
            "size": sizes,
            "color": agg["median"],
            "colorscale": SALARY_SCALE,
            "showscale": True,
            "colorbar": {
                "title": {"text": "Median"},
                "tickprefix": "$", "tickformat": ".3~s",  # $95k, $110k
                "thickness": 10, "outlinewidth": 0,
            },
            # 2px white ring keeps overlapping bubbles distinguishable.
            "line": {"width": 2, "color": "#ffffff"},
            "opacity": 0.9,
        },
        customdata=agg["count"],
        hovertemplate=(
            "<b>%{x}</b><br>Median: $%{y:,.0f}<br>"
            "%{customdata} job(s) with salary<extra></extra>"
        ),
    ))
    fig.update_xaxes(title_text="State", gridcolor=SILVER,
                     categoryorder="array",
                     categoryarray=list(agg["state"]))
    fig.update_yaxes(title_text="Median annual salary", gridcolor=SILVER,
                     tickprefix="$", tickformat=",", rangemode="tozero")
    return _style_chart(fig, title)


def build_skills_bar(df: pd.DataFrame) -> go.Figure:
    """Most-mentioned skills across all listings (horizontal bar)."""
    title = "Top skills mentioned"
    if df.empty or "skills" not in df:
        return _empty_chart(title)
    exploded = df["skills"].explode().dropna()
    exploded = exploded[exploded != ""]
    counts = exploded.value_counts().head(12)
    if counts.empty:
        return _empty_chart(title)
    counts = counts.iloc[::-1]
    fig = go.Figure(go.Bar(
        x=counts.values, y=counts.index, orientation="h",
        marker=_bar_marker(counts.values, SCALE_SKILLS),
    ))
    fig.update_xaxes(gridcolor=SILVER)
    return _style_chart(fig, title)


app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "Jooble Listings"
server = app.server

# Inline theme: light indigo / black / silver. The Google Font link (like
# the Bootstrap CDN stylesheet) needs internet; the font stack and plain
# CSS degrade gracefully without it.
app.index_string = f"""<!DOCTYPE html>
<html>
    <head>
        {{%metas%}}
        <title>{{%title%}}</title>
        {{%favicon%}}
        {{%css%}}
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            body {{
                background-color: {PAGE_BG};
                color: {INK};
                font-family: {FONT_STACK};
            }}
            h1, h2, h3, h4, h5, h6 {{
                color: {INK};
                font-family: {FONT_STACK};
            }}
            .app-title {{
                font-size: 3.25rem;
                font-weight: 700;
                letter-spacing: -0.02em;
                margin-bottom: 0;
                background: {GRADIENT_TITLE};
                -webkit-background-clip: text;
                background-clip: text;
                -webkit-text-fill-color: transparent;
                color: transparent;
            }}
            .author-line {{
                color: #55596a;
                margin-bottom: 0.25rem;
            }}
            .btn-primary {{
                background: {GRADIENT_FILL};
                background-color: {INDIGO};
                border: none;
            }}
            .btn-primary:hover, .btn-primary:focus,
            .btn-primary:active, .btn-primary.active {{
                background: {GRADIENT_FILL_HOVER} !important;
                background-color: {INDIGO_DARK} !important;
                border: none !important;
                box-shadow: 0 2px 8px rgba(29, 34, 96, 0.35) !important;
            }}
            /* Gradient top strip on the hero/title card. */
            .hero-card {{
                position: relative;
                overflow: hidden;
            }}
            .hero-card::before {{
                content: "";
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                height: 5px;
                background: {GRADIENT_STRIP};
            }}
            /* Gradient left-border accent shared by section headings. */
            .section-heading {{
                border-left: 4px solid transparent;
                border-image: {GRADIENT_ACCENT} 1;
                padding-left: 10px;
            }}
            .btn-outline-secondary {{
                color: {INK};
                border-color: {SILVER};
                background-color: {SILVER_SURFACE};
            }}
            .modal-content {{
                background-color: {SILVER_SURFACE};
                border: 1px solid {SILVER};
            }}
            .card {{
                background-color: {SILVER_SURFACE};
                border-color: {SILVER};
            }}
            .form-control {{
                border-color: {SILVER};
            }}
            .form-control:focus {{
                border-color: {INDIGO};
                box-shadow: 0 0 0 0.2rem {INDIGO_TINT};
            }}
            .alert-info {{
                background-color: {INDIGO_TINT};
                border-color: {SILVER};
                color: {INK};
            }}
            /* Soft-rounded white cards on the page background. */
            .chart-card {{
                background-color: #ffffff;
                border: 1px solid {SILVER};
                border-radius: 12px;
                padding: 0.75rem 1rem;
                box-shadow: 0 1px 3px rgba(17, 17, 17, 0.05);
                height: 100%;
            }}
            .title-card {{
                background-color: #ffffff;
                border: 1px solid {SILVER};
                border-radius: 16px;
                box-shadow: 0 1px 3px rgba(17, 17, 17, 0.05);
            }}
            .info-card {{
                background-color: #ffffff;
                border: 1px solid {SILVER};
                border-radius: 12px;
                box-shadow: 0 1px 3px rgba(17, 17, 17, 0.05);
                height: 100%;
            }}
            .app-subtitle {{
                color: #55596a;
                margin-bottom: 0;
                font-weight: 400;
            }}
            /* About modal: readable Markdown sections and tables. */
            .about-md h2 {{
                font-size: 1.15rem;
                font-weight: 600;
                margin: 1.5rem 0 0.6rem;
                padding-left: 10px;
                border-left: 4px solid {INDIGO};
            }}
            .about-md h2:first-child {{ margin-top: 0; }}
            .about-md table {{
                width: 100%;
                margin-bottom: 1rem;
                border-collapse: collapse;
                background-color: #ffffff;
            }}
            .about-md th, .about-md td {{
                padding: 6px 10px;
                border: 1px solid {SILVER};
                vertical-align: top;
            }}
            .about-md thead th {{ background-color: {INDIGO_TINT}; }}
            .about-md thead th:empty {{ display: none; }}
            .about-md code {{
                color: {INDIGO_DARK};
                background-color: {INDIGO_TINT};
                padding: 1px 5px;
                border-radius: 4px;
            }}
        </style>
    </head>
    <body>
        {{%app_entry%}}
        <footer>
            {{%config%}}
            {{%scripts%}}
            {{%renderer%}}
        </footer>
    </body>
</html>"""

fetch_modal = dbc.Modal(
    [
        dbc.ModalHeader(dbc.ModalTitle("Fetch jobs from Jooble")),
        dbc.ModalBody(
            [
                dbc.Label("Keywords", html_for="keywords-input"),
                dbc.Input(
                    id="keywords-input",
                    type="text",
                    value=DEFAULT_KEYWORDS,
                    className="mb-3",
                ),
                dbc.Label("Location", html_for="location-input"),
                dbc.Input(
                    id="location-input",
                    type="text",
                    value=DEFAULT_LOCATION,
                    className="mb-2",
                ),
                dcc.Store(id="remote-store", data=False),
                dbc.Button(
                    "Remote", id="remote-toggle", n_clicks=0,
                    color="secondary", outline=True, size="sm",
                    className="mb-3",
                    style={
                    "marginTop": "10px"
                    } 
                ),
                html.Br(),
                dbc.Label(
                    f"Recency window in days (1-{MAX_DAYS}, up to 100 jobs)",
                    html_for="days-input",
                ),
                dcc.Input(
                    id="days-input",
                    type="number",
                    min=1,
                    max=MAX_DAYS,
                    step=1,
                    value=DEFAULT_DAYS,
                    className="form-control",
                ),
                dcc.Loading(
                    html.Div(id="fetch-status", className="mt-3"),
                    type="default",
                ),
            ]
        ),
        dbc.ModalFooter(
            dbc.Button("Fetch", id="do-fetch", color="primary", n_clicks=0)
        ),
    ],
    id="fetch-modal",
    is_open=False,
)

# Job-detail modal: opened by clicking a cell in the Job Title column.
# Jooble's API only returns a description excerpt (`snippet`), so the modal
# shows that in full plus a link out to the complete posting.
job_modal = dbc.Modal(
    [
        dbc.ModalHeader(dbc.ModalTitle(id="job-modal-title")),
        dbc.ModalBody(id="job-modal-body"),
        dbc.ModalFooter(id="job-modal-footer"),
    ],
    id="job-modal",
    is_open=False,
    size="lg",
    scrollable=True,
)

# About modal: an extra-large, scrollable panel of project documentation.
# Edit ABOUT_MD to change the copy; each "## " heading is one section.
ABOUT_MD = f"""
## Overview

Jooble.com Job Listings pulls recent postings from the
[Jooble REST API](https://jooble.org/api/about), adds a few parsed fields to
each one, and shows them in a searchable table, a map, and a set of charts.
Despite the repo's name, nothing is scraped from HTML pages; every row comes
from the official API.

## Data source: the Jooble API

| Item | Details |
|---|---|
| Endpoint | `POST https://jooble.org/api/<KEY>` |
| Auth | API key as the last URL path segment (`KEY` env var) |
| Request body | JSON: `keywords`, `location`, `radius`, `page`, `companysearch` |
| Response | `jobs[]`: id, title, company, location, salary, type, snippet, link, updated, source |
| Defaults | `"{DEFAULT_KEYWORDS}"` in `"{DEFAULT_LOCATION}"`, last {DEFAULT_DAYS} days |

Jooble has no reliable server-side date filter, so the app applies the
recency window itself, using each job's `updated` timestamp.

## Pipeline

1. The Fetch dialog, or the automatic fetch on page load, calls
   `jooble_data.fetch_jobs(days, keywords, location)`.
2. It requests pages one at a time, up to 10, and stops early once it has
   100 jobs or a page comes back empty.
3. HTTP 429 responses and network errors get a short wait and a retry. A 403
   (bad key) or any other error raises `JoobleApiError`, with the key
   redacted from the message.
4. Rows older than the window are dropped, and so are job ids already seen on
   an earlier page. In strict mode, a row is kept only if its title or
   snippet contains one of the search phrases.
5. Each row is cleaned and parsed offline. Snippet HTML is stripped to plain
   text, the location is matched against a built-in city and state table
   (there's no geocoding API), salary text becomes an estimated annual USD
   figure, and seniority, minimum years of experience, and skill keywords are
   pulled from the title and snippet.
6. The resulting DataFrame is stored in the browser (`dcc.Store`) and feeds
   the table, map, and charts. Changing the state filter redraws from that
   store without calling the API again.

## Architecture

| Layer | File | Role |
|---|---|---|
| Data | `jooble_data.py` | API client, pagination, parsing, enrichment |
| UI | `app.py` | Dash layout, callbacks, charts, modals |
| Email | `mailer.py` | Emails the Listings table as a `.csv` |
| Legacy | `scraper_source.py` | Original CLI script that writes `jooble_list.csv` |

It's written in Python 3.12 with Dash, Plotly, Dash Bootstrap Components,
Dash Mantine Components, pandas, requests, and BeautifulSoup.

## Configuration

Settings come from environment variables. A local `.env` file is loaded with
python-dotenv, but a variable already set in the environment wins.

| Variable | Purpose |
|---|---|
| `KEY` | Jooble API key (required) |
| `SMTP_USER`, `SMTP_APP_PASSWORD` | Gmail account used to send CSV emails |
| `ALERT_FROM` | Optional sender alias (defaults to `SMTP_USER`) |

## Email CSV export

Under **Listings**, enter an email address and press **Email CSV**. The app
emails the rows currently in the table, with the state filter and any column
filters or sorting applied, as a `.csv` attachment through Gmail SMTP. It
sends at most one email every {mailer.SEND_COOLDOWN_SECONDS} seconds.

## Deployment

The Docker image runs the app with gunicorn (`app:server`) on `$PORT`, the
setup Google Cloud Run expects. To run it locally, use `uv run app.py` and
open http://127.0.0.1:8050.

## Limitations

- Jooble returns only a short excerpt of each description, so the app never
  sees the full posting.
- Salary, seniority, and skills are parsed from free text and can be wrong
  or missing.
- Jobs whose location isn't a recognized US city or state don't appear on
  the map.
"""

about_modal = dbc.Modal(
    [
        dbc.ModalHeader(dbc.ModalTitle("About this project")),
        dbc.ModalBody(
            dcc.Markdown(ABOUT_MD, link_target="_blank",
                         className="about-md"),
        ),
        dbc.ModalFooter(
            dbc.Button("Close", id="close-about", color="secondary",
                       outline=True, n_clicks=0)
        ),
    ],
    id="about-modal",
    is_open=False,
    size="xl",
    scrollable=True,
)

# Custom indigo scale (10 shades) centered on INDIGO="#5661c9" at index 6,
# so Mantine's primaryColor matches the app's existing identity.
BRAND_SCALE = [
    "#eef0fb", "#dde0f5", "#b8bde9", "#9199dd", "#7078d3",
    "#5c65cd", "#5661c9", "#4954b3", "#3f4a9f", "#33407f",
]

MANTINE_THEME = {
    "primaryColor": "brand",
    "colors": {"brand": BRAND_SCALE},
    "fontFamily": FONT_STACK,
    "defaultRadius": "lg",
}


def dmc_card(children, **kwargs):
    """White, softly-rounded DMC card used for every structural container."""
    style = {"backgroundColor": "#ffffff", "height": "100%"}
    style.update(kwargs.pop("style", {}))
    return dmc.Card(
        children,
        withBorder=True,
        radius="lg",
        shadow="sm",
        p="md",
        style=style,
        **kwargs,
    )


def chart_card(graph_id):
    """Wrap a single insight chart in its own white DMC card."""
    return dmc_card(dcc.Graph(id=graph_id))


app.layout = dmc.MantineProvider(
    theme=MANTINE_THEME,
    forceColorScheme="light",
    children=dbc.Container(
        [
            dcc.Store(id="jobs-store"),
            # Its pathname is set on every page load, which fires
            # initial_fetch to populate the dashboard with the default search.
            dcc.Location(id="url"),
            # Title card: title/subtitle left, action buttons right.
            dmc_card(
                dmc.Group(
                    [
                        html.Div(
                            [
                                html.H1("Jooble.com Job Listings",
                                        className="app-title"),
                                html.H6(
                                    "Sourced directly through their API.",
                                    className="app-subtitle",
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                dbc.Button(
                                    "Fetch Jobs", id="open-fetch",
                                    color="primary", n_clicks=0,
                                    style={"marginRight": "15px"},
                                ),
                                dbc.Button(
                                    "About", id="open-about",
                                    color="primary", n_clicks=0,
                                    style={"marginRight": "15px"},
                                ),
                                dbc.Button(
                                    "Home", href="https://brucea-lee.com",
                                    external_link=True, color="primary",
                                ),
                            ],
                            className="d-flex align-items-center",
                        ),
                    ],
                    justify="space-between",
                    align="center",
                    wrap="wrap",
                ),
                className="hero-card mt-3 mb-4",
            ),
            fetch_modal,
            job_modal,
            about_modal,
            # Map row: info sidebar (left) + map (right).
            dmc.Grid(
                [
                    dmc.GridCol(
                        dmc_card(
                            [
                                html.H4("Overview",
                                        className="section-heading",
                                        style={"marginBottom": "12px"}),
                                dmc.Select(
                                    id="state-filter",
                                    label="Filter by state",
                                    data=[{"value": "ALL",
                                           "label": "All states"}],
                                    value="ALL",
                                    clearable=False,
                                    allowDeselect=False,
                                    className="mb-3",
                                ),
                                # Spinner while a fetch (incl. the on-load
                                # one) is running; both write active-search.
                                dcc.Loading(
                                    html.Div(id="active-search",
                                             className="text-muted mb-3"),
                                    type="dot",
                                ),
                                html.Div(id="unmapped-note",
                                         className="text-muted mb-3"),
                                html.Div(id="empty-state"),
                            ]
                        ),
                        span={"base": 12, "md": 4},
                    ),
                    dmc.GridCol(
                        dmc_card(
                            [
                                html.H4("Map",
                                        className="section-heading",
                                        style={"marginBottom": "10px"}),
                                dcc.Graph(id="jobs-map",
                                          style={"height": "50vh"}),
                            ]
                        ),
                        span={"base": 12, "md": 8},
                    ),
                ],
                gap="md",
                className="mb-3",
            ),
            html.H4("Insights", className="mt-4 section-heading",
                    style={"marginTop": "20px", "marginBottom": "10px"}),
            dmc.SimpleGrid(
                [
                    chart_card("chart-company"),
                    chart_card("chart-timeline"),
                    chart_card("chart-state"),
                    chart_card("chart-skills"),
                ],
                cols={"base": 1, "md": 2},
                spacing="md",
                verticalSpacing="md",
            ),
            html.Div(chart_card("chart-salary"), className="mt-3"),
            html.H4("Listings", className="mt-4 section-heading", style={"marginTop": "20px", "marginBottom": "20px"}),
            # Email the rows currently shown in the table (state filter,
            # column filters and sort applied) as a .csv attachment.
            html.Div(
                [
                    dbc.InputGroup(
                        [
                            dbc.Input(id="csv-recipient", type="email",
                                      placeholder="you@example.com",
                                      maxLength=254),
                            dbc.Button("Email CSV", id="csv-send",
                                       color="primary", n_clicks=0),
                        ],
                        style={"maxWidth": "420px"},
                    ),
                    dcc.Loading(html.Div(id="csv-status", className="small"),
                                type="dot"),
                ],
                className="d-flex flex-wrap align-items-center gap-3 mb-3",
            ),
            dash_table.DataTable(
            id="jobs-table",
            columns=TABLE_COLUMNS,
            data=[],
            sort_action="native",
            filter_action="native",
            page_size=15,
            row_selectable="single",
            tooltip_duration=None,
            style_table={"overflowX": "auto"},
            style_header={
                "backgroundColor": INDIGO_TINT,
                "borderColor": SILVER,
                "color": INK,
                "fontWeight": "600",
            },
            style_cell={
                "textAlign": "left",
                "maxWidth": "260px",
                "overflow": "hidden",
                "textOverflow": "ellipsis",
                "backgroundColor": "#ffffff",
                "borderColor": SILVER,
                "color": INK,
                "fontFamily": FONT_STACK,
            },
            style_data_conditional=[
                # Job titles look/act like links; clicking opens the
                # job-detail modal (see open_job_modal).
                {
                    "if": {"column_id": "title"},
                    "color": INDIGO,
                    "textDecoration": "underline",
                    "cursor": "pointer",
                    "fontWeight": "500",
                },
                {
                    "if": {"state": "selected"},
                    "backgroundColor": INDIGO_TINT,
                    "border": f"1px solid {INDIGO}",
                }
            ],
        ),
        html.Div(id="snippet-pane", className="my-2"),
        html.Footer(
        "Bruce A. Lee © 2026, All Rights Reserved.",
        style={
            "textAlign": "center",
            "padding": "10px",
            "position": "relative",
            "width": "100%",
            "bottom": "0"
        }
    )
        ],
        fluid=True,
    ),
)


@app.callback(
    Output("fetch-modal", "is_open"),
    Input("open-fetch", "n_clicks"),
    State("fetch-modal", "is_open"),
    prevent_initial_call=True,
)
def open_modal(_n, is_open):
    return not is_open


@app.callback(
    Output("about-modal", "is_open"),
    Input("open-about", "n_clicks"),
    Input("close-about", "n_clicks"),
    State("about-modal", "is_open"),
    prevent_initial_call=True,
)
def toggle_about(_open, _close, is_open):
    return not is_open


# Columns written to the emailed CSV: the table's columns, in order, with the
# plain URL in place of the Markdown link the table renders.
CSV_COLUMNS = [(c["name"], "link" if c["id"] == "link_md" else c["id"])
               for c in TABLE_COLUMNS]


def _status(text, color=None):
    if color is None:
        return html.Div(text, className="text-muted")
    return dbc.Alert(text, color=color, className="py-1 px-2 mb-0")


@app.callback(
    Output("csv-status", "children"),
    Input("csv-send", "n_clicks"),
    State("csv-recipient", "value"),
    State("jobs-table", "derived_virtual_data"),
    State("jobs-table", "data"),
    prevent_initial_call=True,
)
def email_csv(_n, recipient, shown_rows, all_rows):
    """Email the data viewer's current rows as a .csv to the typed address."""
    # derived_virtual_data = rows after the table's own filters/sorting;
    # it is None until the table has rendered once.
    rows = shown_rows if shown_rows is not None else (all_rows or [])
    if not rows:
        return _status("There are no rows to send. Fetch jobs first.",
                       "warning")
    try:
        address = mailer.check_recipient(recipient)
        csv_bytes = mailer.rows_to_csv(rows, CSV_COLUMNS)
        mailer.send_email(mailer.build_email(address, csv_bytes, len(rows)))
    except mailer.MailError as exc:
        return _status(str(exc), "danger")
    except (smtplib.SMTPException, OSError) as exc:
        return _status(f"Email failed: {exc}", "danger")
    noun = "job" if len(rows) == 1 else "jobs"
    return _status(f"Sent {len(rows)} {noun} to {address}.", "success")


@app.callback(
    Output("remote-store", "data"),
    Output("remote-toggle", "outline"),
    Output("remote-toggle", "color"),
    Output("location-input", "disabled"),
    Input("remote-toggle", "n_clicks"),
    State("remote-store", "data"),
    prevent_initial_call=True,
)
def toggle_remote(_n, active):
    active = not bool(active)
    return (
        active,
        not active,                          # solid button when active
        "primary" if active else "secondary",
        active,                              # grey out Location when remote
    )


@app.callback(
    Output("jobs-store", "data"),
    Output("fetch-status", "children"),
    Output("fetch-modal", "is_open", allow_duplicate=True),
    Output("active-search", "children"),
    Input("do-fetch", "n_clicks"),
    State("days-input", "value"),
    State("keywords-input", "value"),
    State("location-input", "value"),
    State("remote-store", "data"),
    prevent_initial_call=True,
)
def run_fetch(_n, days, keywords, location, remote):
    remote = bool(remote)
    records, error = do_fetch(days, keywords, location, remote=remote)
    if error is not None:
        return no_update, dbc.Alert(error, color="danger"), True, no_update
    keywords, location = normalize_search(keywords, location)
    if remote:
        location = REMOTE_LOCATION
    return (
        records,
        dbc.Alert(f"Fetched {len(records)} jobs.", color="success"),
        False,
        f'Showing results for "{keywords}" in "{location}" '
        f"in the last {clamp_days(days)} days.",
    )


@app.callback(
    Output("jobs-store", "data", allow_duplicate=True),
    Output("active-search", "children", allow_duplicate=True),
    Input("url", "pathname"),
    prevent_initial_call="initial_duplicate",
)
def initial_fetch(_pathname):
    """Fetch the default search as soon as the page loads."""
    records, error = do_fetch(DEFAULT_DAYS, DEFAULT_KEYWORDS, DEFAULT_LOCATION)
    if error is not None:
        return no_update, dbc.Alert(error, color="warning")
    return records, (
        f'Showing results for "{DEFAULT_KEYWORDS}" in "{DEFAULT_LOCATION}" '
        f"in the last {DEFAULT_DAYS} days."
    )


@app.callback(
    Output("state-filter", "data"),
    Output("state-filter", "value"),
    Input("jobs-store", "data"),
)
def populate_states(records):
    """Refresh the state dropdown to the states present in the latest fetch
    and reset the selection to 'All states'."""
    base = [{"value": "ALL", "label": "All states"}]
    if not records:
        return base, "ALL"
    states = pd.Series(
        [state_for_location(r.get("location")) for r in records]
    ).dropna()
    counts = states.value_counts()
    options = base + [
        {"value": s, "label": f"{s} ({int(counts[s])})"}
        for s in sorted(counts.index)
    ]
    return options, "ALL"


@app.callback(
    Output("jobs-table", "data"),
    Output("jobs-table", "tooltip_data"),
    Output("jobs-map", "figure"),
    Output("unmapped-note", "children"),
    Output("empty-state", "children"),
    Output("chart-company", "figure"),
    Output("chart-timeline", "figure"),
    Output("chart-state", "figure"),
    Output("chart-skills", "figure"),
    Output("chart-salary", "figure"),
    Input("jobs-store", "data"),
    Input("state-filter", "value"),
)
def render(records, state_value):
    if not records:
        msg = "Click \"Fetch jobs\" to pull listings."
        if not os.environ.get("KEY"):
            msg += (
                " Note: the KEY environment variable is not set - set it "
                "to your Jooble API key before fetching."
            )
        empty_fig, _ = build_map(pd.DataFrame())
        empty = pd.DataFrame()
        return (
            [], [], empty_fig, "", dbc.Alert(msg, color="info"),
            build_company_bar(empty), build_timeline(empty),
            build_state_bar(empty), build_skills_bar(empty),
            build_salary_bubble(empty),
        )

    df = pd.DataFrame(records)
    # The state filter drives the map + table view; the insight charts below
    # always reflect the full fetch. `keep` is a per-record mask so the table
    # rows and tooltips stay aligned. A stale/absent state (e.g. right after a
    # new fetch, before the dropdown resets) falls back to showing everything.
    state_series = df["location"].map(state_for_location)
    if state_value and state_value != "ALL" and (state_series == state_value).any():
        keep = (state_series == state_value).tolist()
    else:
        keep = [True] * len(df)
    view = [r for r, k in zip(records, keep) if k]
    df_view = df[keep]

    tooltips = [
        {"title": {"value": str(r.get("snippet") or ""), "type": "text"}}
        for r in view
    ]
    # DataTable cells must be scalars; the `skills` list is shown via the
    # `skills_str` column, so drop the raw list from the table data.
    table_data = [{k: v for k, v in r.items() if k != "skills"}
                  for r in view]
    fig, unmapped = build_map(df_view)
    scope = "" if len(df_view) == len(df) else f" (filtered to {state_value})"
    note = (
        f"{unmapped} of {len(df_view)} jobs could not be geocoded and appear "
        f"in the table only{scope}."
        if unmapped
        else f"All {len(df_view)} jobs are plotted on the map{scope}."
    )
    return (
        table_data, tooltips, fig, note, None,
        build_company_bar(df), build_timeline(df),
        build_state_bar(df), build_skills_bar(df),
        build_salary_bubble(df),
    )


@app.callback(
    Output("jobs-table", "selected_rows"),
    Input("jobs-map", "clickData"),
    State("jobs-table", "data"),
    prevent_initial_call=True,
)
def select_from_map(click_data, data):
    """Clicking a map point selects that job's row in the table.

    Matches on job id carried in the marker customdata, against the
    table's underlying `data` order — so it works regardless of the
    table's current filter/sort (which only reshuffle the derived view).
    """
    if not click_data or not data:
        return no_update
    try:
        job_id = click_data["points"][0]["customdata"][3]
    except (KeyError, IndexError, TypeError):
        return no_update
    for i, row in enumerate(data):
        if row.get("id") == job_id:
            return [i]
    return no_update


@app.callback(
    Output("snippet-pane", "children"),
    Input("jobs-table", "derived_virtual_selected_rows"),
    Input("jobs-table", "derived_virtual_data"),
    Input("jobs-table", "selected_rows"),
    State("jobs-table", "data"),
)
def show_snippet(dv_selected, dv_rows, selected, data):
    # Prefer the derived view (respects the current filter/sort); fall
    # back to the raw selection so a map-click still shows the detail
    # card even when the row is filtered out of the visible table.
    row = None
    if dv_selected and dv_rows and dv_selected[0] < len(dv_rows):
        row = dv_rows[dv_selected[0]]
    elif selected and data and selected[0] < len(data):
        row = data[selected[0]]
    if row is None:
        return None
    return dbc.Card(
        dbc.CardBody(
            [
                html.H6(f"{row.get('title', '')} - {row.get('company', '')}"),
                dcc.Markdown(
                    str(row.get("snippet") or ""),
                    dangerously_allow_html=False,
                ),
            ]
        )
    )


def job_detail_content(row):
    """(title, body, footer) children for the job-detail modal."""
    title = row.get("title") or "Untitled job"
    facts = [
        ("Company", row.get("company")),
        ("Location", row.get("location")),
        ("Salary", row.get("salary")),
        ("Job type", row.get("job_type")),
        ("Seniority", row.get("seniority")),
        ("Min yrs exp", row.get("min_years")),
        ("Last updated", row.get("updated")),
        ("Source", row.get("source")),
    ]
    fact_items = [
        html.Div([html.Strong(f"{label}: "), str(value)], className="mb-1")
        for label, value in facts
        if value not in (None, "") and not pd.isna(value)
    ]
    skills = [s.strip() for s in str(row.get("skills_str") or "").split(",")
              if s.strip()]
    description = str(row.get("snippet") or "").strip()
    body = [
        html.Div(fact_items, className="mb-3"),
        html.Div(
            [dbc.Badge(s, color="secondary", className="me-1 mb-1")
             for s in skills],
            className="mb-3",
        ) if skills else None,
        html.H6("Job description"),
        html.P(
            description or "No description was provided for this listing.",
            style={"whiteSpace": "pre-wrap", "lineHeight": "1.6"},
        ),
        html.Small(
            "Jooble's API returns a description excerpt; open the posting "
            "for the full text.",
            className="text-muted",
        ),
    ]
    link = row.get("link")
    footer = (
        dbc.Button("Open full posting", href=link, target="_blank",
                   external_link=True, color="primary")
        if link else None
    )
    return title, body, footer


@app.callback(
    Output("job-modal", "is_open"),
    Output("job-modal-title", "children"),
    Output("job-modal-body", "children"),
    Output("job-modal-footer", "children"),
    Output("jobs-table", "active_cell"),
    Input("jobs-table", "active_cell"),
    State("jobs-table", "data"),
    prevent_initial_call=True,
)
def open_job_modal(active_cell, data):
    """Clicking a Job Title cell opens the job-detail modal.

    Rows carry an `id` field, so `active_cell["row_id"]` identifies the job
    regardless of the table's current sort/filter/page. The active cell is
    cleared afterwards so clicking the same title again re-opens the modal.
    """
    if not active_cell or active_cell.get("column_id") != "title" or not data:
        return no_update, no_update, no_update, no_update, no_update
    row_id = active_cell.get("row_id")
    row = next((r for r in data if r.get("id") == row_id), None)
    if row is None:
        return no_update, no_update, no_update, no_update, None
    title, body, footer = job_detail_content(row)
    return True, title, body, footer, None


# if __name__ == "__main__":
#     app.run(debug=False, host="127.0.0.1", port=8050)

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050, use_reloader=True)
    
