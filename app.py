"""Dash UI for jooble_scraper.

Fetch dialog -> jooble_data.fetch_jobs -> DataTable + map. No network calls
happen at import time or on page load; fetches only run from the modal's
button callback. Run with:

    ./venv/Scripts/python app.py
"""

import os

import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import sample_colorscale
from dash import Dash, Input, Output, State, dash_table, dcc, html, no_update

# Dash 2.x serves React 16 by default, but Dash Mantine Components (Mantine 7)
# needs React 18 (it calls the React 18 `useId` hook). This must run before
# the Dash app is instantiated below.
dash._dash_renderer._set_react_version("18.2.0")

from jooble_data import (
    DEFAULT_KEYWORDS,
    DEFAULT_LOCATION,
    JoobleApiError,
    fetch_jobs,
    _STATE_CENTROIDS,
    _STATE_NAMES,
)

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
    {"name": "Senority", "id": "seniority"},
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

# Indigo-adjacent accents so each chart reads as part of one coordinated set
# rather than an all-indigo wall. Single-series bars each take one accent;
# categorical charts (donut, seniority) cycle the full sequence.
ACCENT_INDIGO = "#5661c9"      # base indigo
ACCENT_VIOLET = "#7c5cd8"
ACCENT_PERIWINKLE = "#8b93e8"
ACCENT_SLATE = "#4a56b0"
ACCENT_TEAL = "#4db6ac"
ACCENT_PLUM = "#9b5bb8"
ACCENT_STEEL = "#5c7cba"

# Multi-hue sequence for categorical charts.
CHART_COLORS = [
    ACCENT_INDIGO, ACCENT_VIOLET, ACCENT_TEAL, ACCENT_PLUM,
    ACCENT_PERIWINKLE, ACCENT_SLATE, ACCENT_STEEL,
]

# Single indigo gradient (light -> dark) applied across every chart so the
# dashboard reads as one coordinated ramp. Bars are shaded by magnitude
# (small = light, large = dark); ordinal/categorical charts sample the ramp
# evenly. Keeps everything on-brand with INDIGO / the map marker.
GRADIENT_INDIGO = [
    "#e9ebfa",  # light periwinkle (INDIGO_TINT)
    "#b8bdec",
    "#8b93e8",
    "#5661c9",  # base indigo (brand)
    "#434db3",
    "#2f378f",
    "#1d2260",  # deep indigo
]

# CSS gradient strings for the dashboard *chrome* (not the charts). Built from
# the same GRADIENT_INDIGO ramp so page furniture matches the Plotly charts.
_GRAD_STOPS = ", ".join(GRADIENT_INDIGO)
GRADIENT_STRIP = f"linear-gradient(90deg, {_GRAD_STOPS})"          # full ramp
GRADIENT_FILL = "linear-gradient(135deg, #5661c9, #2f378f)"        # solid btn
GRADIENT_FILL_HOVER = "linear-gradient(135deg, #434db3, #1d2260)"  # btn hover
GRADIENT_TITLE = "linear-gradient(135deg, #5661c9, #2f378f 55%, #1d2260)"
GRADIENT_ACCENT = "linear-gradient(180deg, #5661c9, #1d2260)"      # heading bar



def _sample_gradient(pts):
    """Sample GRADIENT_INDIGO at the given points, clamped to [0, 1].

    Float rounding can nudge a computed point just past 1.0 (e.g. 0.18 + 0.82
    == 1.0000000000000002), which makes plotly's sample_colorscale index past
    the end of the scale and raise IndexError. Clamping avoids that.
    """
    pts = [min(1.0, max(0.0, p)) for p in pts]
    return sample_colorscale(GRADIENT_INDIGO, pts)


def gradient_by_value(values, lo: float = 0.18, hi: float = 1.0) -> list:
    """One gradient color per value, darker as the value grows.

    Use for count bars (companies, states, skills, postings/day) so the
    biggest bar is the deepest indigo and the smallest the lightest.
    """
    vals = [float(v) for v in values]
    if not vals:
        return []
    vmin, vmax = min(vals), max(vals)
    if vmax == vmin:
        return _sample_gradient([hi] * len(vals))
    pts = [lo + (hi - lo) * (v - vmin) / (vmax - vmin) for v in vals]
    return _sample_gradient(pts)


def _style_chart(fig: go.Figure, title: str) -> go.Figure:
    """Apply the shared indigo/silver theme to an insight chart."""
    fig.update_layout(
        title={"text": title, "font": {"color": INK, "size": 15}},
        font={"family": FONT_STACK, "color": INK},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
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
        marker={"color": gradient_by_value(counts.values)},
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
        marker={"color": gradient_by_value(per_day.values)},
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
        marker={"color": gradient_by_value(counts.values)},
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
    more confidence.
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
            "color": gradient_by_value(agg["median"].to_numpy()),
            "line": {"width": 1, "color": "#ffffff"},
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
        marker={"color": gradient_by_value(counts.values)},
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
                    value=7,
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
                                html.Div(id="active-search",
                                         className="text-muted mb-3"),
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
                gutter="md",
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


# if __name__ == "__main__":
#     app.run(debug=False, host="127.0.0.1", port=8050)

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050, use_reloader=True)
    
