import streamlit as st
import pandas as pd
import geopandas as gpd
import pydeck as pdk
import matplotlib.pyplot as plt
from io import BytesIO
import base64
from difflib import get_close_matches

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(page_title="Map of Campus and building work-orders", layout="wide")
st.title("Map of Campus and building work-orders")

# ── Constants ─────────────────────────────────────────────────────────────────

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

# ── Manual Overrides ──────────────────────────────────────────────────────────

# Upper-cased & stripped keys → exact geojson name
MANUAL_OVERRIDES = {
    "COC":               "COLLEGE OF COMPUTING",
    "COLL OF COMPUTI":   "COLLEGE OF COMPUTING",
    # …add more as you discover them…
}

# ── Helpers for Slider Bounds ─────────────────────────────────────────────────

@st.cache_data
def load_year_bounds(path):
    df = pd.read_csv(path, parse_dates=["WORKDATE"], usecols=["WORKDATE"])
    years = df["WORKDATE"].dt.year.dropna()
    return int(years.min()), int(years.max())

@st.cache_data
def load_month_bounds(path):
    df = pd.read_csv(path, parse_dates=["WORKDATE"], usecols=["WORKDATE"])
    months = df["WORKDATE"].dt.month.dropna()
    return int(months.min()), int(months.max())

# ── Build Sidebar Controls ───────────────────────────────────────────────────

st.sidebar.header("🔍 Filters")

# Year slider (guaranteed no NaN)
min_year, max_year = load_year_bounds("DF_WO_GaTech.csv")
selected_years = st.sidebar.slider(
    "Year range", min_year, max_year, (min_year, max_year)
)

# Month-range slider (optional)
filter_months = st.sidebar.checkbox("Filter by month-range", False)
if filter_months:
    mn, mx = load_month_bounds("DF_WO_GaTech.csv")
    selected_months = st.sidebar.slider("Month range", mn, mx, (mn, mx))
else:
    selected_months = (None, None)

# Season filter
filter_season = st.sidebar.checkbox("Filter by season", False)
if filter_season:
    selected_season = st.sidebar.selectbox("Season", list(SEASON_MONTHS))
    season_months = SEASON_MONTHS[selected_season]
else:
    season_months = None

# ── Load & Filter Work-Orders ─────────────────────────────────────────────────

@st.cache_data
def load_and_filter_orders(path, years, months, season):
    df = pd.read_csv(path, parse_dates=["WORKDATE"])
    df["year"]      = df["WORKDATE"].dt.year
    df["month"]     = df["WORKDATE"].dt.month
    df["FAC_ID_UP"] = df["FAC_ID"].astype(str).str.upper().str.strip()
    # apply manual fixes
    df["FAC_ID_MAPPED"] = df["FAC_ID_UP"].replace(MANUAL_OVERRIDES)

    mask = df["year"].between(*years)
    if months[0] is not None:
        mask &= df["month"].between(*months)
    if season is not None:
        mask &= df["month"].isin(season)

    return df.loc[mask]

df = load_and_filter_orders(
    "DF_WO_GaTech.csv",
    selected_years,
    selected_months,
    season_months
)

# ── Load Building Footprints ──────────────────────────────────────────────────

@st.cache_data
def load_buildings(path):
    gdf = gpd.read_file(path)
    gdf["Sheet3__Common_Name"] = (
        gdf["Sheet3__Common_Name"]
           .astype(str)
           .str.upper()
           .str.strip()
    )
    return gdf

gdf = load_buildings("campus_buildings.geojson")

# ── Fuzzy-Match Suggestions ───────────────────────────────────────────────────

building_names = gdf["Sheet3__Common_Name"].tolist()
unmatched = [
    fid for fid in df["FAC_ID_MAPPED"].unique()
    if fid not in building_names
]
suggestions = {
    fid: get_close_matches(fid, building_names, n=3, cutoff=0.6)
    for fid in unmatched
}
if suggestions:
    st.sidebar.subheader("🛠 Mapping suggestions")
    st.sidebar.write(suggestions)

# ── Aggregate by Craft ────────────────────────────────────────────────────────

grouped = (
    df.groupby("FAC_ID_MAPPED")["CRAFT"]
      .value_counts()
      .unstack(fill_value=0)
)

# ── Pie-Chart Renderer & Tooltip HTML ────────────────────────────────────────

def make_pie_datauri(counts):
    fig, ax = plt.subplots(figsize=(2,2))
    colors  = [CRAFT_COLORS.get(c, "#CCCCCC") for c in counts.index]
    autopct = lambda p: f"{p:.0f}%" if p >= PCT_ON_SLICE else ""
    ax.pie(counts, labels=None, autopct=autopct,
           startangle=90, colors=colors,
           wedgeprops={"edgecolor":"white"})
    ax.axis("equal")
    buf = BytesIO(); fig.savefig(buf, format="png", bbox_inches="tight", transparent=True)
    plt.close(fig); buf.seek(0)
    data = base64.b64encode(buf.read()).decode()
    return f"data:image/png;base64,{data}"

def build_tooltip_html(row):
    name = row["Sheet3__Common_Name"]
    if name in grouped.index:
        raw    = grouped.loc[name]
        counts = raw[raw>0]
        pct    = counts.div(counts.sum())*100
        uri    = make_pie_datauri(counts)
        lines  = []
        for craft, p in zip(counts.index, pct):
            col = CRAFT_COLORS.get(craft, "#CCCCCC")
            swatch = (
                f"<span style='display:inline-block; "
                f"width:12px; height:12px; background:{col}; "
                f"margin-right:4px; vertical-align:middle'></span>"
            )
            lines.append(f"{swatch}{craft}: {p:.1f}%")
        legend = "<br>".join(lines)
        return (
            "<div style='text-align:center;'>"
              f"<strong>{name}</strong><br>"
              f"<img src='{uri}' width='120px'><br>"
              "<div style='text-align:left; font-size:0.9em; "
                         "column-count:2; column-gap:12px; margin-top:4px;'>"
                f"{legend}"
              "</div>"
            "</div>"
        )
    else:
        return (
            "<div style='text-align:center;'>"
              f"<strong>{name}</strong><br>"
              "No work-order data"
            "</div>"
        )

gdf["tooltip_html"] = gdf.apply(build_tooltip_html, axis=1)

# ── Render the Map ────────────────────────────────────────────────────────────

MAP_CENTER = [33.7756, -84.3963]
view_state = pdk.ViewState(latitude=MAP_CENTER[0], longitude=MAP_CENTER[1], zoom=16, pitch=0)

layer = pdk.Layer(
    "GeoJsonLayer", data=gdf, pickable=True, stroked=True, filled=True,
    extruded=False, get_fill_color=[50,100,200,80], get_line_color=[255,255,255,200]
)

deck = pdk.Deck(
    layers=[layer],
    initial_view_state=view_state,
    tooltip={
        "html": "{tooltip_html}",
        "style": {"backgroundColor":"rgba(0,0,0,0.8)","color":"white"}
    }
)

st.write("Hover over a building to see its pie-chart and legend.")
st.pydeck_chart(deck)













