"""Dash UI for jooble_scraper.

Fetch dialog -> jooble_data.fetch_jobs -> DataTable + map. No network calls
happen at import time or on page load; fetches only run from the modal's
button callback. Run with:

    ./venv/Scripts/python app.py
"""

import os

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, dash_table, dcc, html, no_update

from jooble_data import (
    DEFAULT_KEYWORDS,
    DEFAULT_LOCATION,
    JoobleApiError,
    fetch_jobs,
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

REMOTE_LOCATION = "Remote, United States"
MAX_DAYS = 14

TABLE_COLUMNS = [
    {"name": "Title", "id": "title"},
    {"name": "Company", "id": "company"},
    {"name": "Location", "id": "location"},
    {"name": "Salary", "id": "salary"},
    {"name": "Type", "id": "job_type"},
    {"name": "Updated", "id": "updated"},
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
            }}
            .author-line {{
                color: #55596a;
                margin-bottom: 0.25rem;
            }}
            .btn-primary {{
                background-color: {INDIGO};
                border-color: {INDIGO};
            }}
            .btn-primary:hover, .btn-primary:focus,
            .btn-primary:active, .btn-primary.active {{
                background-color: {INDIGO_DARK} !important;
                border-color: {INDIGO_DARK} !important;
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

app.layout = dbc.Container(
    [
        dcc.Store(id="jobs-store"),
        html.Div(
            [
                html.Div(
                    [
                        html.H1("Jooble Listings", className="app-title"),
                        html.H6("A live window into the job market, one fetch at a time.", className="sub-title"),
                        html.Hr(),
                        html.Br(),
                    ]
                )
            ],
            className="d-flex align-items-center mt-3",
        ),
        dbc.Button(
            "Fetch Jobs", id="open-fetch", color="primary",
            className="my-2", 
            n_clicks=0, 
            style={"marginRight": "15px"}
        ),
        dbc.Button(
            "Home", href="https://brucea-lee.com",
            external_link=True, color="primary",
            className="ms-auto",
        ),
        fetch_modal,
        html.Div(id="active-search", className="mt-2 text-muted",
                 style={"marginTop": "2.5rem", "marginBottom": "2.5rem"}),
        html.Div(id="empty-state", className="my-2"),
        html.H4("Map", className="mt-2", style={"marginTop": "20px", "marginBottom": "5px"}),
        html.Div(id="unmapped-note", className="mb-2 text-muted"),
        dcc.Graph(id="jobs-map", style={"height": "50vh"}),
        html.H4("Listings", className="mt-4", style={"marginTop": "20px", "marginBottom": "20px"}),
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
                "backgroundColor": SILVER_SURFACE,
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
    Output("jobs-table", "data"),
    Output("jobs-table", "tooltip_data"),
    Output("jobs-map", "figure"),
    Output("unmapped-note", "children"),
    Output("empty-state", "children"),
    Input("jobs-store", "data"),
)
def render(records):
    if not records:
        msg = "Click \"Fetch jobs\" to pull listings."
        if not os.environ.get("KEY"):
            msg += (
                " Note: the KEY environment variable is not set - set it "
                "to your Jooble API key before fetching."
            )
        empty_fig, _ = build_map(pd.DataFrame())
        return [], [], empty_fig, "", dbc.Alert(msg, color="info")

    df = pd.DataFrame(records)
    tooltips = [
        {"title": {"value": str(r.get("snippet") or ""), "type": "text"}}
        for r in records
    ]
    fig, unmapped = build_map(df)
    note = (
        f"{unmapped} of {len(df)} jobs could not be geocoded and appear "
        "in the table only."
        if unmapped
        else f"All {len(df)} jobs are plotted on the map."
    )
    return records, tooltips, fig, note, None


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
    
