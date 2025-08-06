import streamlit as st
import pandas as pd
import geopandas as gpd
import pydeck as pdk
import matplotlib.pyplot as plt
import matplotlib as mpl
from io import BytesIO
import base64
from difflib import get_close_matches

# ─── Configuration ──────────────────────────────────────────────────────────

st.set_page_config(page_title="Map of Campus and building work-orders", layout="wide")
st.title("Map of Campus and building work-orders")

CRAFT_COLORS = {
    "HVAC":              "#1f77b4",
    "ELECTRIC":          "#ff7f0e",
    "CARPENTRY":         "#2ca02c",
    "PLUMBING":          "#d62728",
    "MULTI-CRAFT":       "#9467bd",
    "PAINT":             "#8c564b",
    "ADMINISTRATIVE":    "#e377c2",
    "PROJECT MANAGEMENT":"#7f7f7f",
}

SEASON_MONTHS = {
    "Winter": [12, 1, 2],
    "Spring": [3, 4, 5],
    "Summer": [6, 7, 8],
    "Fall":   [9, 10, 11],
}

PCT_ON_SLICE = 5.0


# ─── Sidebar Filters ────────────────────────────────────────────────────────

st.sidebar.header("🔍 Filters")

@st.cache_data
def load_years():
    tmp = pd.read_csv("DF_WO_GaTech.csv", parse_dates=["WORKDATE"], usecols=["WORKDATE"])
    yrs = tmp["WORKDATE"].dt.year
    return int(yrs.min()), int(yrs.max())

min_year, max_year = load_years()
years_sel = st.sidebar.slider("Year range", min_year, max_year, (min_year, max_year))

filter_months = st.sidebar.checkbox("Filter by month-range", False)
if filter_months:
    tmp2 = pd.read_csv("DF_WO_GaTech.csv", parse_dates=["WORKDATE"], usecols=["WORKDATE"])
    mn, mx = tmp2["WORKDATE"].dt.month.min(), tmp2["WORKDATE"].dt.month.max()
    months_sel = st.sidebar.slider("Month range", int(mn), int(mx), (int(mn), int(mx)))
else:
    months_sel = (None, None)

filter_season = st.sidebar.checkbox("Filter by season", False)
if filter_season:
    season_sel = st.sidebar.selectbox("Season", list(SEASON_MONTHS))
    season_months = SEASON_MONTHS[season_sel]
else:
    season_months = None


# ─── Load & Filter Work-Orders ──────────────────────────────────────────────

@st.cache_data
def load_and_filter_orders(years, months, season):
    df = pd.read_csv("DF_WO_GaTech.csv", parse_dates=["WORKDATE"])
    df["year"]   = df["WORKDATE"].dt.year
    df["month"]  = df["WORKDATE"].dt.month
    df["FAC_ID"] = df["FAC_ID"].str.upper().str.strip()

    mask = df["year"].between(*years)
    if months[0] is not None:
        mask &= df["month"].between(*months)
    if season is not None:
        mask &= df["month"].isin(season)

    return df.loc[mask].copy()

df = load_and_filter_orders(years_sel, months_sel, season_months)


# ─── Load Building Footprints ───────────────────────────────────────────────

@st.cache_data
def load_buildings():
    gdf = gpd.read_file("campus_buildings.geojson")
    gdf["FAC_ID"] = gdf["Sheet3__Common_Name"].str.upper().str.strip()
    return gdf

gdf = load_buildings()


# ─── Normalize FAC_ID to match GeoJSON ───────────────────────────────────────

manual_map = {
    "COC": "COLLEGE OF COMPUTING",
    # add any other one-offs here…
}

# Only keep real strings for fuzzy matching
valid_names = {name for name in gdf["FAC_ID"].unique() if isinstance(name, str)}

def standardize_fac_id(fid):
    if not isinstance(fid, str):
        return fid
    key = fid.strip().upper()
    if key in manual_map:
        return manual_map[key]
    if key in valid_names:
        return key
    # now safe to fuzzy-match, because valid_names contains only strings
    matches = get_close_matches(key, valid_names, n=1, cutoff=0.7)
    return matches[0] if matches else key

df["FAC_ID"] = df["FAC_ID"].apply(standardize_fac_id)


# ─── Aggregate by Craft ─────────────────────────────────────────────────────

craft_counts = df.groupby("FAC_ID")["CRAFT"].value_counts().unstack(fill_value=0)


# ─── Pie‐Chart Renderer ──────────────────────────────────────────────────────

def make_pie_datauri(counts):
    fig, ax = plt.subplots(figsize=(2, 2))
    colors = [CRAFT_COLORS.get(c, "#CCCCCC") for c in counts.index]
    autopct = lambda p: f"{p:.0f}%" if p >= PCT_ON_SLICE else ""
    ax.pie(
        counts,
        labels=None,
        autopct=autopct,
        startangle=90,
        colors=colors,
        wedgeprops={"edgecolor": "white"},
    )
    ax.axis("equal")
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# ─── Tooltip HTML ───────────────────────────────────────────────────────────

def build_tooltip_html(feature):
    fid = feature["properties"]["FAC_ID"]
    counts = craft_counts.get(fid, pd.Series(dtype=int))
    counts = counts[counts > 0]

    if counts.empty:
        return f"<div><strong>{fid}</strong><br>No work-order data</div>"

    pct = (counts / counts.sum() * 100).round(1)
    uri = make_pie_datauri(counts)

    lines = []
    for c, p in zip(counts.index, pct):
        col = CRAFT_COLORS.get(c, "#CCCCCC")
        swatch = (
            f"<span style='display:inline-block;"
            f"width:12px;height:12px;"
            f"background:{col};"
            f"margin-right:4px;'></span>"
        )
        lines.append(f"{swatch}{c}: {p}%")

    legend = "<br>".join(lines)
    return (
        "<div style='text-align:center;'>"
        f"<strong>{fid}</strong><br>"
        f"<img src='{uri}' width='120px'><br>"
        f"<div style='column-count:2; column-gap:8px; "
        f"font-size:0.9em; overscroll-behavior:contain;'>{legend}</div>"
        "</div>"
    )

gdf["tooltip_html"] = gdf.apply(lambda r: build_tooltip_html(r), axis=1)


# ─── Render Map ─────────────────────────────────────────────────────────────

view_state = pdk.ViewState(latitude=33.7756, longitude=-84.3963, zoom=16, pitch=0)

layer = pdk.Layer(
    "GeoJsonLayer",
    data=gdf,
    pickable=True,
    stroked=True,
    filled=True,
    extruded=False,
    get_fill_color=[50, 100, 200, 80],
    get_line_color=[255, 255, 255, 200],
)

deck = pdk.Deck(
    layers=[layer],
    initial_view_state=view_state,
    tooltip={
        "html": "{tooltip_html}",
        "style": {"backgroundColor": "rgba(0,0,0,0.8)", "color": "white"}
    }
)

st.write("Hover over a building to see its pie-chart and legend.")
st.pydeck_chart(deck)








