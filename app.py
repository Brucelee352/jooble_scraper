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

from jooble_data import JoobleApiError, fetch_jobs

# Single-series marker color (accessible mid-blue on light map tiles).
MARKER_COLOR = "#2f6fd6"

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


def do_fetch(days: int):
    """Core fetch logic, kept as a plain function so it is testable.

    Returns (records, error_message): exactly one of the two is not None.
    `records` is a list of dicts ready for dcc.Store / DataTable.
    """
    try:
        df = fetch_jobs(days=days, limit=100)
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
                customdata=mappable[["title", "company", "location"]].values,
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
app.title = "Jooble jobs"
server = app.server

fetch_modal = dbc.Modal(
    [
        dbc.ModalHeader(dbc.ModalTitle("Fetch jobs from Jooble")),
        dbc.ModalBody(
            [
                html.P("Pick the recency window (up to 100 jobs):"),
                dbc.RadioItems(
                    id="window-radio",
                    options=[
                        {"label": "Last 7 days", "value": 7},
                        {"label": "Last 2 days", "value": 2},
                    ],
                    value=7,
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
        html.H2("Jooble job listings", className="mt-3"),
        dbc.Button(
            "Fetch jobs", id="open-fetch", color="primary",
            className="my-2", n_clicks=0,
        ),
        fetch_modal,
        html.Div(id="empty-state", className="my-2"),
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
            style_cell={
                "textAlign": "left",
                "maxWidth": "260px",
                "overflow": "hidden",
                "textOverflow": "ellipsis",
            },
        ),
        html.Div(id="snippet-pane", className="my-2"),
        html.H4("Map", className="mt-4"),
        html.Div(id="unmapped-note", className="mb-2 text-muted"),
        dcc.Graph(id="jobs-map", style={"height": "60vh"}),
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
    Output("jobs-store", "data"),
    Output("fetch-status", "children"),
    Output("fetch-modal", "is_open", allow_duplicate=True),
    Input("do-fetch", "n_clicks"),
    State("window-radio", "value"),
    prevent_initial_call=True,
)
def run_fetch(_n, days):
    records, error = do_fetch(int(days))
    if error is not None:
        return no_update, dbc.Alert(error, color="danger"), True
    return (
        records,
        dbc.Alert(f"Fetched {len(records)} jobs.", color="success"),
        False,
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
        msg = "No data loaded yet. Click \"Fetch jobs\" to pull listings."
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
    Output("snippet-pane", "children"),
    Input("jobs-table", "derived_virtual_selected_rows"),
    Input("jobs-table", "derived_virtual_data"),
)
def show_snippet(selected_rows, rows):
    if not selected_rows or not rows:
        return None
    idx = selected_rows[0]
    if idx >= len(rows):
        return None
    row = rows[idx]
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


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
