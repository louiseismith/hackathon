"""
app_ui/app.py — Python UI for NYC Urban Risk Early Warning System.
Run with: streamlit run app.py (from app_ui folder) or streamlit run app_ui/app.py (from hackathon).
"""

import os
import sys
from pathlib import Path

# Add hackathon/app to path so we can import backend and chatbot (avoid naming conflict with this file app.py)
APP_UI_DIR = Path(__file__).resolve().parent
HACKATHON_ROOT = APP_UI_DIR.parent
APP_DIR = HACKATHON_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# Load .env from hackathon or parent 5381
for env_dir in (HACKATHON_ROOT, HACKATHON_ROOT.parent):
    env_file = env_dir / ".env"
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file)
        break

import base64
import io
import re
import streamlit as st
import pandas as pd
import numpy as np
import streamlit.components.v1 as components
import json

try:
    import pydeck as pdk
except ModuleNotFoundError:
    pdk = None

from backend import get_risk_data, get_date_range, get_risk_series, borocd_to_cd_id
from chatbot.agent import run_chat

# Paths relative to hackathon
GEOJSON_PATH = APP_DIR / "nyc_cd_boundaries.geojson"
CD_META_PATH = HACKATHON_ROOT / "data" / "community_districts.csv"

RISK_LAYERS = {
    "heat_index_risk":     {"label": "Heat Index",        "col": "heat_index_risk",     "domain": (0, 80),   "unit": "/ 100"},
    "total_capacity_pct":  {"label": "Hospital Capacity", "col": "total_capacity_pct",  "domain": (50, 100), "unit": "%"},
    "transit_delay_index": {"label": "Transit Index",     "col": "transit_delay_index", "domain": (0, 60),   "unit": ""},
    "composite":           {"label": "Composite Score",   "col": "composite",           "domain": (0, 100), "unit": "/ 100"},
}
METRICS = {
    "heat_index_risk":     {"label": "Heat Index Risk",     "col": "heat_index_risk",     "domain": (0, 80)},
    "total_capacity_pct":  {"label": "Hospital Capacity %", "col": "total_capacity_pct",  "domain": (50, 100)},
    "transit_delay_index": {"label": "Transit Delay Index", "col": "transit_delay_index", "domain": (0, 60)},
}


@st.cache_data(show_spinner=False)
def load_boundaries():
    """Load GeoJSON and attach cd_id, borough, neighborhood. Cached so type-ahead stays fast."""
    with open(GEOJSON_PATH, encoding="utf-8") as f:
        gj = json.load(f)
    for feat in gj.get("features", []):
        props = feat.setdefault("properties", {})
        bcd = props.get("BoroCD")
        if bcd is not None:
            props["cd_id"] = borocd_to_cd_id(int(bcd)) or ""
        else:
            props["cd_id"] = ""
    if CD_META_PATH.exists():
        cd_meta = pd.read_csv(CD_META_PATH)
        meta_by_cd = cd_meta.set_index("cd_id").to_dict("index")
        for feat in gj.get("features", []):
            cd_id = feat["properties"].get("cd_id")
            if cd_id and cd_id in meta_by_cd:
                feat["properties"]["borough"] = meta_by_cd[cd_id].get("borough", "")
                feat["properties"]["neighborhood"] = meta_by_cd[cd_id].get("neighborhood", cd_id)
            else:
                feat["properties"]["borough"] = feat["properties"].get("borough", "")
                feat["properties"]["neighborhood"] = feat["properties"].get("neighborhood", cd_id or "")
    else:
        for feat in gj.get("features", []):
            feat["properties"]["borough"] = feat["properties"].get("borough", "")
            feat["properties"]["neighborhood"] = feat["properties"].get("neighborhood", feat["properties"].get("cd_id", ""))
    return gj


def normalize_metric(vals, domain):
    lo, hi = domain[0], domain[1]
    if hi <= lo:
        return [0.0] * len(vals)
    arr = pd.Series(vals).astype(float)
    return (np.clip((arr - lo) / (hi - lo) * 100, 0, 100)).tolist()


# Risk colors for map (same as plan: green -> yellow -> orange -> red)
def _display_val_to_hex(v):
    if v is None:
        return "#cccccc"
    if v <= 25:
        return "#2ecc71"
    if v <= 50:
        return "#f1c40f"
    if v <= 75:
        return "#e67e22"
    return "#e74c3c"


def _hex_to_rgb(hex_str):
    """Convert hex color to [r, g, b] for deck.gl."""
    h = hex_str.lstrip("#")
    return [int(h[i : i + 2], 16) for i in (0, 2, 4)]


def _build_deck_risk_map(boundaries, layer_label, height_px=650):
    """Build a deck.gl map of NYC CDs colored by risk (like energy-burden). Returns HTML string for iframe embed."""
    if pdk is None:
        return """
<!doctype html>
<html><body style="font-family:system-ui;padding:12px;color:#374151;">
<div style="font-weight:600;margin-bottom:6px;">Map dependency missing</div>
<div>Install <code>pydeck</code>: <code>pip install pydeck</code></div>
</body></html>
"""
    # Copy and add color_rgba to each feature for GeoJsonLayer
    import copy
    gj = copy.deepcopy(boundaries)
    for feat in gj.get("features", []):
        props = feat.setdefault("properties", {})
        v = props.get("_display_val")
        hex_color = _display_val_to_hex(v)
        props["color_rgba"] = _hex_to_rgb(hex_color) + [192]  # alpha for fill
        # Format for tooltip
        props["_display_val_fmt"] = f"{v:.1f}" if v is not None else "N/A"
    geojson_data = gj

    layer = pdk.Layer(
        "GeoJsonLayer",
        data=geojson_data,
        get_fill_color="[properties.color_rgba[0], properties.color_rgba[1], properties.color_rgba[2], properties.color_rgba[3]]",
        get_line_color=[255, 255, 255],
        line_width_min_pixels=1,
        filled=True,
        stroked=True,
        opacity=0.85,
        pickable=True,
        auto_highlight=True,
    )
    tooltip = {
        "html": (
            "<b>Neighborhood:</b> {neighborhood}<br/>"
            "<b>CD:</b> {cd_id}<br/>"
            f"<b>{layer_label}:</b> {{_display_val_fmt}}"
        ),
        "style": {
            "backgroundColor": "#fff",
            "color": "#374151",
            "padding": "10px",
            "fontFamily": "system-ui, sans-serif",
        },
    }
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(
            latitude=40.73,
            longitude=-73.98,
            zoom=11,
            pitch=0,
            bearing=0,
        ),
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        tooltip=tooltip,
        height=height_px,
    )
    return deck.to_html(as_string=True)


def _prepare_pydeck_html_for_embed(map_html, height_px=650):
    """Ensure pydeck HTML fills iframe and inject click handler so selecting a district updates the app."""
    embed_css = f"html,body{{height:{height_px}px;margin:0;overflow:hidden;}}"
    if "</head>" in map_html:
        map_html = map_html.replace("</head>", f"<style>{embed_css}</style></head>", 1)
    # Inject script: on district click, set parent URL to ?cd_id=... so Streamlit can set selected_cd
    click_script = """
<script>
(function() {
  function attachClick() {
    if (typeof deck === 'undefined' || !deck.on) return false;
    deck.on('click', function(evt) {
      if (evt.object && evt.object.properties) {
        var p = evt.object.properties;
        var base = window.parent.location.pathname || '/';
        var q = '?cd_id=' + encodeURIComponent(p.cd_id || '') + '&borough=' + encodeURIComponent(p.borough || '') + '&neighborhood=' + encodeURIComponent(p.neighborhood || '');
        window.parent.location = base + q;
      }
    });
    return true;
  }
  if (attachClick()) return;
  var tries = 0;
  var t = setInterval(function() {
    if (attachClick() || ++tries > 80) clearInterval(t);
  }, 100);
})();
</script>
"""
    if "</body>" in map_html:
        map_html = map_html.replace("</body>", click_script + "\n</body>", 1)
    return map_html


def _risk_to_dot_color(risk_0_100):
    """Return hex color for indicator dot: red (high), orange (mid), green (low)."""
    if risk_0_100 is None:
        return "#94a3b8"
    if risk_0_100 >= 66:
        return "#e74c3c"
    if risk_0_100 >= 33:
        return "#f39c12"
    return "#2ecc71"


def _build_stats_card_html(selected_cd, risk_df):
    """Build the Statistics card overlay to match UI mockup: transparent card with district name,
    borough | CD id, phone/menu icons, then metrics with colored dots and values. Populates for
    whatever community district the user selects (via search)."""
    card_style = (
        "border-radius: 12px; background: rgba(255, 255, 255, 0.75); "
        "backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); "
        "box-shadow: 0 2px 16px rgba(0,0,0,0.08); padding: 14px 16px; "
        "font-family: system-ui, -apple-system, sans-serif; font-size: 14px; "
        "border: 1px solid rgba(255,255,255,0.5); min-width: 240px; max-width: 300px;"
    )
    if not selected_cd:
        return f"""<div style="{card_style}">
        <div style="font-size: 14px; font-weight: 700; color: #0f172a; margin-bottom: 8px;">Statistics</div>
        <div style="font-size: 15px; font-weight: 600; color: #334155;">Select a district</div>
        <div style="font-size: 12px; color: #64748b; margin-top: 2px;">Use search above or click a district on the map</div>
        </div>"""
    name = selected_cd.get("neighborhood") or selected_cd.get("cd_id") or "—"
    borough = selected_cd.get("borough") or ""
    cd_id = selected_cd.get("cd_id") or ""
    sub = " | ".join(filter(None, [borough, cd_id]))
    # Phone and menu icons (Unicode)
    icons = "<span style='color:#94a3b8;font-size:14px;margin-left:6px;'>📞</span><span style='color:#94a3b8;font-size:14px;'>☰</span>"
    header = f"""
    <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 8px;">
        <div>
            <div style="font-size: 20px; font-weight: 700; color: #0f172a;">{_escape_html(name)}</div>
            <div style="font-size: 12px; color: #64748b; margin-top: 2px;">{_escape_html(sub)}</div>
        </div>
        <div style="flex-shrink: 0;">{icons}</div>
    </div>"""
    if risk_df is None or risk_df.empty:
        return f"<div style='{card_style}'>{header}<div style='margin-top:12px;font-size:12px;color:#64748b;'>No data for this district</div></div>"
    match = risk_df[risk_df["cd_id"] == cd_id]
    if match.empty:
        return f"<div style='{card_style}'>{header}<div style='margin-top:12px;font-size:12px;color:#64748b;'>No data for this district</div></div>"
    row = match.iloc[0]
    # Normalize each metric to 0-100 risk (higher = worse) for dot color
    def norm_risk(col, domain, invert=False):
        v = row.get(col)
        if v is None or not pd.notna(v):
            return None
        lo, hi = domain[0], domain[1]
        if hi <= lo:
            return None
        pct = (float(v) - lo) / (hi - lo) * 100
        pct = max(0, min(100, pct))
        return 100 - pct if invert else pct
    # Composite
    norms = []
    for m in METRICS:
        col = METRICS[m]["col"]
        if col in row and pd.notna(row[col]):
            v = float(row[col])
            lo, hi = METRICS[m]["domain"][0], METRICS[m]["domain"][1]
            if hi > lo:
                n = max(0, min(100, (v - lo) / (hi - lo) * 100))
                norms.append(n)
    composite_val = round(sum(norms) / len(norms), 1) if norms else None
    composite_risk = (sum(norms) / len(norms)) if norms else None
    # Metrics: (label, value_fmt, risk_0_100 for dot). Hospital/ICU: high % = low risk
    heat_v = row.get("heat_index_risk")
    heat_risk = norm_risk("heat_index_risk", (0, 80), invert=False)
    hosp_v = row.get("total_capacity_pct")
    hosp_risk = norm_risk("total_capacity_pct", (50, 100), invert=True)  # low capacity = high risk
    icu_v = row.get("icu_capacity_pct")
    icu_risk = norm_risk("icu_capacity_pct", (50, 100), invert=True)
    ed_v = row.get("ed_wait_hours")
    ed_risk = norm_risk("ed_wait_hours", (0, 24), invert=False) if ed_v is not None else None  # assume 0-24 hr range
    if ed_risk is None and ed_v is not None:
        ed_risk = min(100, float(ed_v) * 4)  # rough
    transit_v = row.get("transit_delay_index")
    transit_risk = norm_risk("transit_delay_index", (0, 60), invert=False)
    metrics = [
        ("Heat Index Risk", heat_v, "/ 100", heat_risk),
        ("Hospital Capacity %", hosp_v, "%", hosp_risk),
        ("ICU Capacity %", icu_v, "%", icu_risk),
        ("ED Wait Hours", ed_v, " hrs", ed_risk),
        ("Transit Delay Index", transit_v, "", transit_risk),
    ]
    lines = []
    for label, val, unit, risk in metrics:
        dot = _risk_to_dot_color(risk)
        if val is not None and pd.notna(val):
            v_fmt = f"{round(float(val), 1)}{unit}" if isinstance(val, (int, float)) else f"{val}{unit}"
        else:
            v_fmt = "—"
        trend_icon = "<span style='color:#e74c3c;font-size:10px;'>▲</span>" if (risk is not None and risk >= 66) else "<span style='color:#94a3b8;font-size:10px;'>→</span>"
        lines.append(f"""
        <div style="display: flex; align-items: center; gap: 8px; margin-top: 10px;">
            <span style="width: 8px; height: 8px; border-radius: 50%; background: {dot}; flex-shrink: 0;"></span>
            <span style="flex: 1;">{_escape_html(label)}</span>
            <span style="color: #334155; font-weight: 500;">{_escape_html(str(v_fmt))}</span>
            {trend_icon}
        </div>""")
    # Composite row at bottom with divider
    comp_fmt = f"{composite_val}/ 100" if composite_val is not None else "—"
    comp_dot = _risk_to_dot_color(composite_risk)
    comp_icon = "<span style='color:#e74c3c;font-size:10px;'>▲</span>" if (composite_risk is not None and composite_risk >= 66) else "<span style='color:#94a3b8;font-size:10px;'>→</span>"
    body = "".join(lines) + f"""
        <div style="border-top: 1px solid rgba(0,0,0,0.08); margin-top: 12px; padding-top: 10px;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="width: 8px; height: 8px; border-radius: 50%; background: {comp_dot}; flex-shrink: 0;"></span>
                <span style="flex: 1; font-weight: 600;">Composite Risk Score</span>
                <span style="color: #334155; font-weight: 600;">{_escape_html(str(comp_fmt))}</span>
                {comp_icon}
            </div>
        </div>"""
    return f"<div style='{card_style}'>{header}<div style='margin-top: 12px;'>{body}</div></div>"


def _build_trend_html(selected_cd, risk_layer_key, layer_info, date_str, trend_days):
    """Build overlay HTML for Trend: line chart of risk layer over time (matplotlib PNG base64) or placeholder."""
    if not selected_cd:
        return "<strong>Trend</strong><br/><span style='font-size: 12px; color: #666;'>Select a district for trend.</span>"
    cd_id = selected_cd.get("cd_id")
    if not cd_id:
        return "<strong>Trend</strong><br/><span style='font-size: 12px; color: #666;'>Select a district for trend.</span>"
    start_d = pd.Timestamp(date_str) - pd.Timedelta(days=int(trend_days) - 1)
    start_str = start_d.strftime("%Y-%m-%d")
    try:
        series = get_risk_series(cd_id, start_str, date_str)
    except Exception:
        return "<strong>Trend</strong><br/><span style='font-size: 12px; color: #666;'>Trend unavailable.</span>"
    if not series:
        return "<strong>Trend</strong><br/><span style='font-size: 12px; color: #666;'>No trend data for this range.</span>"
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        return "<strong>Trend</strong><br/><span style='font-size: 12px; color: #666;'>Install matplotlib for trend chart.</span>"
    sdf = pd.DataFrame(series)
    if risk_layer_key == "composite":
        for m in METRICS:
            sdf[m + "_n"] = normalize_metric(sdf[METRICS[m]["col"]].tolist(), METRICS[m]["domain"])
        sdf["display_val"] = sdf[[m + "_n" for m in METRICS]].mean(axis=1)
    else:
        sdf["display_val"] = sdf[layer_info["col"]]
    sdf["date"] = pd.to_datetime(sdf["date"])
    fig, ax = plt.subplots(figsize=(3.2, 1.8), dpi=100)
    ax.plot(sdf["date"], sdf["display_val"], color="steelblue", linewidth=1.5)
    ax.set_xlabel("")
    ax.set_ylabel(layer_info["label"], fontsize=9)
    ax.tick_params(axis="both", labelsize=8)
    fig.autofmt_xdate()
    ax.set_title("", fontsize=10)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=(1, 1, 1, 0.9))
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    return f"<strong>Trend</strong> <span style='font-size: 11px; color: #666;'>(Past {trend_days} days)</span><br/><img src='data:image/png;base64,{b64}' style='width: 100%; height: auto; margin-top: 4px;' alt='Trend'/>"


def _build_top_risk_html(risk_df, layer_info):
    """Build overlay HTML for Top Communities At Risk: table with Name, Risk Type, Desired Metric (top 10)."""
    if risk_df is None or risk_df.empty or "display_val" not in risk_df.columns:
        return "<strong>Top Communities At Risk</strong><br/><span style='font-size: 12px; color: #666;'>No risk data for selected date.</span>"
    top = risk_df.nlargest(10, "display_val")
    risk_label = layer_info["label"]
    unit = layer_info.get("unit") or ""
    rows = []
    for _, r in top.iterrows():
        name = _escape_html((r.get("neighborhood") or "") + " " + (r.get("cd_id") or ""))
        val = r.get("display_val")
        if pd.notna(val):
            desired = f"{round(float(val), 1)}{unit}"
        else:
            desired = "—"
        rows.append(f"<tr><td style='padding: 4px 8px;'>{name}</td><td style='padding: 4px 8px;'>{_escape_html(risk_label)}</td><td style='padding: 4px 8px;'>{_escape_html(desired)}</td></tr>")
    table_body = "".join(rows)
    return f"""
    <strong>Top Communities At Risk</strong>
    <table style='width: 100%; margin-top: 8px; font-size: 13px; border-collapse: collapse;'>
        <thead><tr style='border-bottom: 1px solid #e2e8f0;'>
            <th style='text-align: left; padding: 6px 8px;'>Name</th>
            <th style='text-align: left; padding: 6px 8px;'>Risk Type</th>
            <th style='text-align: left; padding: 6px 8px;'>Desired Metric</th>
        </tr></thead>
        <tbody>{table_body}</tbody>
    </table>
    """


def _escape_html(s):
    """Escape string for safe use in HTML."""
    if s is None:
        return ""
    s = str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _prepare_folium_html_for_embed(map_html, height_px=650):
    """Prepare Folium HTML for iframe embed: set explicit height so map renders (avoids 'Trust Notebook' / Branca height=None)."""
    # Strip Jupyter/Branca trust message if present (so it never shows in Streamlit)
    for phrase in ("Make this Notebook Trusted", "Trust Notebook", "File -> Trust Notebook"):
        map_html = map_html.replace(phrase, "")
    # Inject CSS so html/body and map container have explicit height (fixes Branca height=None in iframe)
    embed_css = f"html,body{{height:{height_px}px;margin:0;overflow:hidden;}}"
    if "</head>" in map_html:
        map_html = map_html.replace("</head>", f"<style>{embed_css}</style></head>", 1)
    else:
        map_html = map_html.replace("<body>", f"<head><style>{embed_css}</style></head><body>", 1)
    # Ensure Folium's root map div has pixel height (100% may not resolve in iframe)
    map_html = map_html.replace('style="width: 100%; height: 100%;"', f'style="width: 100%; height: {height_px}px;"', 1)
    if 'height: 100%;' in map_html and f'height: {height_px}px' not in map_html:
        map_html = map_html.replace("height: 100%;", f"height: {height_px}px;", 1)
    return map_html


def _build_map_dashboard_html(map_html, stats_card_html, top_risk_html, trend_html, map_is_pydeck=True):
    """Build one HTML block: wrapper div with map (iframe) + overlay divs (identity, stats, table, trend)."""
    # Prepare map HTML for iframe (explicit height so map renders)
    if map_is_pydeck:
        map_html = _prepare_pydeck_html_for_embed(map_html, height_px=650)
    else:
        map_html = _prepare_folium_html_for_embed(map_html, height_px=650)
    # Escape map_html for embedding in srcdoc
    map_srcdoc = map_html.replace("'", "&#39;").replace('"', "&quot;")
    overlay_style = (
        "z-index: 10; border-radius: 10px; background: rgba(255,255,255,0.92); "
        "box-shadow: 0 2px 12px rgba(0,0,0,0.08); padding: 12px; "
        "font-family: system-ui, -apple-system, sans-serif; font-size: 14px; border: 1px solid rgba(0,0,0,0.06);"
    )
    # Full document so iframe body has no margin/padding and map fills the square; overlays on top
    map_wrapper = f"""
    <div style="position: relative; width: 100%; height: 650px; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08); background: #e2e8f0; border: 1px solid rgba(0,0,0,0.06); margin: 0; padding: 0; box-sizing: border-box;">
        <iframe srcdoc="{map_srcdoc}" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none; border-radius: 8px; z-index: 1;" title="NYC Risk Map"></iframe>
        <div style="position: absolute; top: 12px; right: 12px; z-index: 10;">
            {stats_card_html}
        </div>
        <div style="position: absolute; bottom: 12px; left: 12px; max-width: 380px; max-height: 220px; overflow-y: auto; {overlay_style}">
            {top_risk_html}
        </div>
        <div style="position: absolute; bottom: 12px; right: 12px; width: 320px; height: 200px; {overlay_style}">
            {trend_html}
        </div>
    </div>
    """
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;}</style></head><body>"
        + map_wrapper +
        "</body></html>"
    )


def _inject_dashboard_css():
    """Inject CSS for page background, control bar, and typography. Sidebar uses Streamlit default (drag + collapse arrow)."""
    st.markdown(
        """
        <style>
        /* Page background: clear gradient */
        .stApp, [data-testid="stAppViewContainer"], .main {
            background: linear-gradient(165deg, #f0f4f8 0%, #e2e8f0 50%, #cbd5e1 100%) !important;
        }
        /* Main: no padding so map can fill the square to the right of sidebar */
        [data-testid="stAppViewContainer"] { padding: 0 !important; }
        .main { padding: 0 !important; max-width: none !important; }
        .main .block-container {
            padding-top: 0.5rem;
            padding-left: 0.5rem;
            padding-right: 0.5rem;
            padding-bottom: 0 !important;
            max-width: none !important;
            width: 100%;
        }
        /* Map block (2nd: control bar, then map): no margin/padding so map fills area */
        .main .block-container > div:nth-child(2) {
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
            max-width: none !important;
        }
        .main .block-container > div:nth-child(2) iframe {
            display: block !important;
            width: 100% !important;
        }
        /* Top control bar: frosted, skinnier (match inspiration) */
        .main .block-container > div:first-child {
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.88);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.05);
            padding: 0.4rem 1rem;
            margin-bottom: 0.5rem;
            border: 1px solid rgba(255, 255, 255, 0.6);
        }
        /* Streamlit widget labels in control bar */
        .main .block-container > div:first-child label {
            font-weight: 500;
            color: #475569;
        }
        /* Skinnier: white inputs and selectboxes (reduced height/padding) */
        .main .block-container > div:first-child input, .main .block-container > div:first-child [data-baseweb="select"] {
            background: #fff !important;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
            min-height: 32px !important;
            padding: 4px 10px !important;
            font-size: 0.8125rem !important;
        }
        .main .block-container > div:first-child [data-baseweb="select"] > div {
            min-height: 32px !important;
            padding: 4px 10px !important;
        }
        /* Search button: force blue (Streamlit primary is red; target only last column button) */
        .main .block-container > div:first-child div[data-testid="column"]:last-child button,
        .main .block-container > div:first-child button[kind="primary"] {
            background-color: #2563eb !important;
            background: #2563eb !important;
            color: #fff !important;
            border: none !important;
            border-radius: 8px;
            font-weight: 500;
            min-height: 32px !important;
            padding: 4px 14px !important;
            font-size: 0.8125rem !important;
        }
        .main .block-container > div:first-child div[data-testid="column"]:last-child button:hover,
        .main .block-container > div:first-child button[kind="primary"]:hover {
            background-color: #1d4ed8 !important;
            background: #1d4ed8 !important;
            color: #fff !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def run():
    st.set_page_config(page_title="NYC Urban Risk — Early Warning System", layout="wide")
    _inject_dashboard_css()

    if "boundaries" not in st.session_state:
        st.session_state.boundaries = load_boundaries()
    if "selected_cd" not in st.session_state:
        st.session_state.selected_cd = None
    # Allow selecting a district via URL query params (e.g. from map click in iframe)
    qp = st.query_params
    if qp.get("cd_id"):
        st.session_state.selected_cd = {
            "cd_id": qp.get("cd_id", ""),
            "borough": qp.get("borough", ""),
            "neighborhood": qp.get("neighborhood", ""),
        }
        # Clear query params so URL is clean (triggers rerun)
        st.query_params.clear()
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = None

    date_range = get_date_range()
    date_min = pd.to_datetime(date_range["min"]).date()
    date_max = pd.to_datetime(date_range["max"]).date()
    date_seq = pd.date_range(date_min, date_max, freq="D")
    months = sorted(date_seq.month.unique())
    month_names = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    months_ord = [month_names[m - 1] for m in months]
    years_ord = sorted(date_seq.year.unique().tolist())

    # Sidebar
    with st.sidebar:
        st.header("NYC Urban Risk — Early Warning System")
        (chat_tab,) = st.tabs(["Chatbot"])
        with chat_tab:
            st.caption("Suggested prompts")
            if st.button("Which CDs show rising heat and hospital strain?", use_container_width=True):
                st.session_state.suggested_prompt = "Which neighborhoods show rising heat and hospital strain?"
            if st.button("Where is risk accelerating the fastest?", use_container_width=True):
                st.session_state.suggested_prompt = "Where is risk accelerating the fastest?"
            if st.button("How does today compare to similar historical patterns?", use_container_width=True):
                st.session_state.suggested_prompt = "How does today compare to similar historical patterns?"
            if st.button("Which agencies need to coordinate?", use_container_width=True):
                st.session_state.suggested_prompt = "Which agencies need to coordinate?"
            st.divider()
            chat_input = st.chat_input("Type your question here...")

    # Build CD lookup once from cached boundaries (fast)
    cd_lookup_list = []
    for f in st.session_state.boundaries.get("features", []):
        p = f["properties"]
        cd_id = p.get("cd_id")
        if cd_id:
            cd_lookup_list.append({"cd_id": cd_id, "borough": p.get("borough", ""), "neighborhood": p.get("neighborhood", cd_id)})
    cd_lookup_df = pd.DataFrame(cd_lookup_list)

    def _search_matches(query, df, max_results=12):
        if not query or df.empty:
            return df.head(0)
        q = query.strip().lower()
        mask = (
            df["cd_id"].str.lower().str.contains(q, na=False) |
            df["neighborhood"].str.lower().str.contains(q, na=False) |
            df["borough"].str.lower().str.contains(q, na=False)
        )
        return df.loc[mask].head(max_results)

    # Top bar: search with type-ahead list directly underneath, then risk layer, date, Search.
    col1, col2, col3, col4, col5, col6 = st.columns([2, 1, 1, 1, 1, 1])
    with col1:
        search_cd = st.text_input("Search community district", placeholder="Search your community district...", label_visibility="collapsed", key="search_cd_input")
        # Type-ahead: list of matching districts directly under the search bar (only when there's input and matches)
        if search_cd:
            search_matches = _search_matches(search_cd, cd_lookup_df)
            if not search_matches.empty:
                option_labels = [f"{row['neighborhood']} ({row['borough']} | {row['cd_id']})" for _, row in search_matches.iterrows()]
                choice = st.radio(
                    "Matching districts",
                    options=option_labels,
                    key="cd_typeahead",
                    label_visibility="collapsed",
                    index=None,
                )
                if choice is not None:
                    idx = option_labels.index(choice)
                    row = search_matches.iloc[idx]
                    st.session_state.selected_cd = {"cd_id": row["cd_id"], "borough": row["borough"], "neighborhood": row["neighborhood"]}
    with col2:
        risk_layer = st.selectbox("Risk Layer", list(RISK_LAYERS.keys()), format_func=lambda k: RISK_LAYERS[k]["label"], label_visibility="collapsed")
    with col3:
        sel_month = st.selectbox("Month", months_ord, index=len(months_ord) - 1 if months_ord else 0, label_visibility="collapsed")
    with col4:
        sel_day = st.number_input("Day", min_value=1, max_value=31, value=min(15, date_max.day), step=1, label_visibility="collapsed")
    with col5:
        sel_year = st.selectbox("Year", years_ord, index=len(years_ord) - 1 if years_ord else 0, label_visibility="collapsed")
    with col6:
        btn_search = st.button("Search")

    # Resolve selected date
    month_num = month_names.index(sel_month) + 1
    try:
        selected_date = pd.Timestamp(year=sel_year, month=month_num, day=min(sel_day, pd.Timestamp(year=sel_year, month=month_num, day=1).days_in_month)).date()
    except Exception:
        selected_date = date_max
    selected_date = max(date_min, min(date_max, selected_date))
    date_str = str(selected_date)

    # Search: resolve to CD only when user clicks Search or a suggestion (map does not update while typing)
    if btn_search and search_cd and not cd_lookup_df.empty:
        q = search_cd.strip().lower()
        # Match: exact cd_id, or neighborhood/borough contains query, or query contains borough/neighborhood (e.g. "the bronx" matches borough "Bronx")
        def field_matches(series, query):
            s = series.astype(str).str.lower().fillna("")
            return s.str.contains(query, na=False) | s.apply(lambda v: query.find(v) >= 0 if v else False)
        match = cd_lookup_df[
            cd_lookup_df["cd_id"].str.lower().eq(q) |
            cd_lookup_df["neighborhood"].str.lower().str.contains(q, na=False) |
            cd_lookup_df["borough"].str.lower().str.contains(q, na=False) |
            field_matches(cd_lookup_df["borough"], q) |
            field_matches(cd_lookup_df["neighborhood"], q)
        ]
        if not match.empty:
            row = match.iloc[0]
            st.session_state.selected_cd = {"cd_id": row["cd_id"], "borough": row["borough"], "neighborhood": row["neighborhood"]}

    # Suggested prompt from chatbot tab
    if "suggested_prompt" in st.session_state and st.session_state.get("suggested_prompt"):
        prompt = st.session_state.suggested_prompt
        del st.session_state.suggested_prompt
        chat_input = prompt  # will be processed below after we have selected_date

    # Risk data
    try:
        rows = get_risk_data(date_str)
        risk_df = pd.DataFrame(rows)
    except Exception as e:
        st.warning(f"Risk data unavailable: {e}. Showing map without data.")
        risk_df = pd.DataFrame()

    # Merge risk into GeoJSON for coloring
    layer_info = RISK_LAYERS[risk_layer]
    if not risk_df.empty and layer_info["col"] in risk_df.columns:
        if risk_layer == "composite":
            for m in METRICS:
                risk_df[m + "_norm"] = normalize_metric(risk_df[METRICS[m]["col"]].tolist(), METRICS[m]["domain"])
            risk_df["display_val"] = risk_df[[m + "_norm" for m in METRICS]].mean(axis=1)
        else:
            risk_df["display_val"] = risk_df[layer_info["col"]]
        risk_by_cd = risk_df.set_index("cd_id")["display_val"].to_dict()
    else:
        risk_by_cd = {}

    for feat in st.session_state.boundaries.get("features", []):
        feat["properties"]["_display_val"] = risk_by_cd.get(feat["properties"].get("cd_id"), None)

    # Map: pydeck (deck.gl) for reliable render in iframe, same approach as energy-burden app
    map_html = _build_deck_risk_map(st.session_state.boundaries, layer_info["label"], height_px=650)

    # Map dashboard: single HTML block with map + overlays (selection via search only)
    sc = st.session_state.selected_cd
    stats_card_html = _build_stats_card_html(sc, risk_df)
    top_risk_html = _build_top_risk_html(risk_df, layer_info)
    trend_days = 7
    trend_html = _build_trend_html(sc, risk_layer, layer_info, date_str, trend_days)
    dashboard_html = _build_map_dashboard_html(map_html, stats_card_html, top_risk_html, trend_html)
    components.html(dashboard_html, height=650)

    if sc:
        st.sidebar.caption(f"**{sc['neighborhood']}** — {sc['borough']} / {sc['cd_id']}")

    # Chat
    if chat_input:
        with st.spinner("Thinking..."):
            try:
                result = run_chat(
                    chat_input,
                    current_date=date_str,
                    message_history=st.session_state.chat_history,
                )
                st.session_state.chat_history = result["history"]
                st.sidebar.chat_message("assistant").write(result["response"])
            except Exception as e:
                st.sidebar.error(f"Chatbot error: {e}")

    # Legend
    st.caption(f"Risk layer: {layer_info['label']} (domain {layer_info['domain']} {layer_info['unit']})")


if __name__ == "__main__":
    run()
