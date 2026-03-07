"""
app_ui/app.py — Shiny for Python: NYC Urban Risk Early Warning System
Run from hackathon root: shiny run app_ui/app.py
"""

import sys
import json
import io
import base64
import copy
import calendar
import asyncio
import concurrent.futures
from pathlib import Path
import markdown as md_lib

import pandas as pd
import numpy as np
import folium
from folium import Element

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

APP_UI_DIR     = Path(__file__).resolve().parent
HACKATHON_ROOT = APP_UI_DIR.parent
APP_DIR        = HACKATHON_ROOT / "app"
WWW_DIR        = APP_UI_DIR / "www"
WWW_DIR.mkdir(exist_ok=True)
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

for env_dir in (HACKATHON_ROOT, HACKATHON_ROOT.parent):
    env_file = env_dir / ".env"
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file)
        break

from shiny import App, ui, render, reactive
from backend import get_risk_data, get_date_range, get_risk_series, borocd_to_cd_id
from chatbot.agent import run_chat, run_cd_summary, run_cd_recommendations

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GEOJSON_PATH = APP_DIR / "nyc_cd_boundaries.geojson"
CD_META_PATH = HACKATHON_ROOT / "data" / "community_districts.csv"

RISK_LAYERS = {
    "heat_index_risk":     {"label": "Heat Index",        "col": "heat_index_risk",     "domain": (0, 80),   "unit": "/ 100"},
    "total_capacity_pct":  {"label": "Hospital Capacity", "col": "total_capacity_pct",  "domain": (50, 100), "unit": "%"},
    "transit_delay_index": {"label": "Transit Index",     "col": "transit_delay_index", "domain": (0, 60),   "unit": ""},
    "composite":           {"label": "Composite Score",   "col": "composite",           "domain": (0, 100),  "unit": "/ 100"},
}
METRICS = {
    "heat_index_risk":     {"label": "Heat Index Risk",     "col": "heat_index_risk",     "domain": (0, 80)},
    "total_capacity_pct":  {"label": "Hospital Capacity %", "col": "total_capacity_pct",  "domain": (50, 100)},
    "transit_delay_index": {"label": "Transit Delay Index", "col": "transit_delay_index", "domain": (0, 60)},
}


_MNAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# ---------------------------------------------------------------------------
# Startup data (module level — runs once on server start)
# ---------------------------------------------------------------------------

def _load_boundaries():
    with open(GEOJSON_PATH, encoding="utf-8") as f:
        gj = json.load(f)
    for feat in gj.get("features", []):
        props = feat.setdefault("properties", {})
        bcd = props.get("BoroCD")
        props["cd_id"] = (borocd_to_cd_id(int(bcd)) or "") if bcd is not None else ""
    if CD_META_PATH.exists():
        meta = pd.read_csv(CD_META_PATH).set_index("cd_id").to_dict("index")
        for feat in gj.get("features", []):
            cd_id = feat["properties"].get("cd_id", "")
            m = meta.get(cd_id, {})
            feat["properties"]["borough"]      = m.get("borough", "")
            feat["properties"]["neighborhood"] = m.get("neighborhood", cd_id)
    else:
        for feat in gj.get("features", []):
            p = feat["properties"]
            p.setdefault("borough", "")
            p.setdefault("neighborhood", p.get("cd_id", ""))
    return gj


BOUNDARIES = _load_boundaries()

CD_LOOKUP = pd.DataFrame([
    {
        "cd_id":        f["properties"]["cd_id"],
        "borough":      f["properties"].get("borough", ""),
        "neighborhood": f["properties"].get("neighborhood", f["properties"]["cd_id"]),
    }
    for f in BOUNDARIES["features"] if f["properties"].get("cd_id")
])

_dr        = get_date_range()
DATE_MIN   = pd.to_datetime(_dr["min"]).date()
DATE_MAX   = pd.to_datetime(_dr["max"]).date()
_dseq      = pd.date_range(DATE_MIN, DATE_MAX, freq="D")
MONTHS_ORD = [_MNAMES[m - 1] for m in sorted(_dseq.month.unique())]
YEARS_ORD  = [str(y) for y in sorted(_dseq.year.unique().tolist())]

# Type-ahead choices: blank placeholder entry first, then CDs sorted borough → neighborhood
CD_CHOICES: dict[str, str] = {"": ""}
for _, _r in CD_LOOKUP.sort_values(["borough", "neighborhood"]).iterrows():
    CD_CHOICES[_r["cd_id"]] = f"{_r['neighborhood']}  ({_r['cd_id']}) — {_r['borough']}"

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def normalize_metric(vals, domain):
    lo, hi = domain
    if hi <= lo:
        return [0.0] * len(vals)
    return np.clip((pd.Series(vals).astype(float) - lo) / (hi - lo) * 100, 0, 100).tolist()


import matplotlib.cm as _plasma_cm
import matplotlib.colors as _mcolors

def _val_color(v):
    """Map a 0-100 display value to a plasma fill color (color-blind accessible)."""
    if v is None:
        return "#cccccc"
    rgba = _plasma_cm.plasma(float(v) / 100.0)
    return _mcolors.to_hex(rgba)


def _dot_color(risk):
    """Map a 0-100 risk level to a status dot color."""
    if risk is None: return "#94a3b8"
    if risk >= 66:   return "#e74c3c"
    if risk >= 33:   return "#f39c12"
    return "#2ecc71"


def _esc(s):
    if s is None: return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


# ---------------------------------------------------------------------------
# Folium map builder
# ---------------------------------------------------------------------------

# Injected into every folium map: on polygon click, fire Shiny.setInputValue
# on the parent window (the Shiny app page — one level up from the srcdoc iframe).
_CLICK_JS = """<script>
(function () {
  function attach() {
    var mapObj = null;
    Object.keys(window).forEach(function (k) {
      if (/^map_[a-z0-9]+$/.test(k) && window[k] && window[k].eachLayer)
        mapObj = window[k];
    });
    if (!mapObj) return false;
    var found = 0;
    mapObj.eachLayer(function (layer) {
      if (!layer.eachLayer) return;
      layer.eachLayer(function (sub) {
        sub.on("click", function (e) {
          var p = e.target.feature && e.target.feature.properties;
          if (!p) return;
          try {
            window.parent.Shiny.setInputValue(
              "map_click",
              {
                cd_id:        p.cd_id        || "",
                borough:      p.borough      || "",
                neighborhood: p.neighborhood || ""
              },
              { priority: "event" }
            );
          } catch (_) {}
        });
        found++;
      });
    });
    return found > 0;
  }
  var tries = 0;
  var t = setInterval(function () {
    if (attach() || ++tries > 80) clearInterval(t);
  }, 150);
})();
</script>"""



def _build_folium_map(boundaries, risk_by_cd, layer_label):
    m = folium.Map(
        location=[40.73, -73.98],
        zoom_start=11,
        tiles="CartoDB positron",
        prefer_canvas=True,
    )
    gj = copy.deepcopy(boundaries)
    for feat in gj["features"]:
        p   = feat["properties"]
        val = risk_by_cd.get(p.get("cd_id"), None)
        p["_v"]     = val
        p["_vfmt"]  = f"{val:.1f}" if val is not None else "N/A"
        p["_color"] = _val_color(val)

    folium.GeoJson(
        gj,
        style_function=lambda f: {
            "fillColor":   f["properties"]["_color"],
            "fillOpacity": 0.75,
            "color":       "white",
            "weight":      1,
        },
        highlight_function=lambda f: {
            "fillOpacity": 0.9,
            "weight":      2,
            "color":       "#333",
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["borough", "neighborhood", "cd_id", "_vfmt"],
            aliases=["Borough:", "Community District:", "CD ID:", f"{layer_label}:"],
            style="font-family:system-ui;font-size:13px;",
        ),
    ).add_to(m)

    m.get_root().html.add_child(Element(_CLICK_JS))
    return m


# ---------------------------------------------------------------------------
# Card / overlay HTML builders
# ---------------------------------------------------------------------------

_CARD_CSS = (
    "border-radius:12px;"
    "background:rgba(255,255,255,0.52);"
    "backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);"
    "box-shadow:0 2px 16px rgba(0,0,0,0.10);"
    "padding:14px 16px;"
    "font-family:system-ui,-apple-system,sans-serif;font-size:14px;"
    "border:1px solid rgba(255,255,255,0.38);"
    "min-width:240px;max-width:300px;"
)

_OVERLAY_CSS = (
    "border-radius:10px;"
    "background:rgba(255,255,255,0.52);"
    "backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);"
    "box-shadow:0 2px 12px rgba(0,0,0,0.08);"
    "padding:12px 14px;"
    "font-family:system-ui,-apple-system,sans-serif;font-size:13px;"
    "border:1px solid rgba(255,255,255,0.38);"
)


def _trend_arrow(curr, prev, tol=0.1):
    """Return (symbol, color) comparing curr vs prev value over 30 days.
    Green ▲ = increased, Red ▼ = decreased, Yellow → = no change."""
    if curr is None or prev is None:
        return "→", "#94a3b8"
    try:
        delta = float(curr) - float(prev)
    except (TypeError, ValueError):
        return "→", "#94a3b8"
    if delta > tol:
        return "▲", "#22c55e"   # green — increased
    if delta < -tol:
        return "▼", "#e74c3c"   # red — decreased
    return "→", "#f59e0b"       # yellow — no change


def _stats_card_html(sc, risk_df, prev_df=None):
    if not sc:
        return (
            f'<div style="{_CARD_CSS}">'
            '<div style="font-size:14px;font-weight:700;color:#0f172a;margin-bottom:8px;">Statistics</div>'
            '<div style="font-size:13px;color:#64748b;">Select a district on the map or use search.</div>'
            '</div>'
        )

    name  = _esc(sc.get("neighborhood") or sc.get("cd_id") or "—")
    sub   = _esc(" | ".join(filter(None, [sc.get("borough", ""), sc.get("cd_id", "")])))
    cd_id = sc.get("cd_id", "")

    header = (
        f'<div style="margin-bottom:4px;">'
        f'  <div style="font-size:20px;font-weight:700;color:#0f172a;">{name}</div>'
        f'  <div style="font-size:12px;color:#64748b;margin-top:2px;">{sub}</div>'
        f'</div>'
    )

    if risk_df is None or risk_df.empty:
        return (
            f'<div style="{_CARD_CSS}">{header}'
            f'<div style="margin-top:10px;font-size:12px;color:#64748b;">No data for this district.</div>'
            f'</div>'
        )

    row = risk_df[risk_df["cd_id"] == cd_id]
    if row.empty:
        return (
            f'<div style="{_CARD_CSS}">{header}'
            f'<div style="margin-top:10px;font-size:12px;color:#64748b;">No data for this district.</div>'
            f'</div>'
        )

    r = row.iloc[0]

    # Previous row (30 days ago) for the same CD
    prev_r = None
    if prev_df is not None and not prev_df.empty:
        prev_row = prev_df[prev_df["cd_id"] == cd_id]
        if not prev_row.empty:
            prev_r = prev_row.iloc[0]

    def norm_val(v, domain):
        if v is None or not pd.notna(v): return None
        lo, hi = domain
        if hi <= lo: return None
        return max(0.0, min(100.0, (float(v) - lo) / (hi - lo) * 100))

    # Composite (average of the three map metrics)
    norms = [n for n in (norm_val(r.get(mv["col"]), mv["domain"]) for mv in METRICS.values()) if n is not None]
    composite_val  = round(sum(norms) / len(norms), 1) if norms else None
    composite_risk = sum(norms) / len(norms) if norms else None

    # Previous composite
    prev_composite = None
    if prev_r is not None:
        p_norms = [n for n in (norm_val(prev_r.get(mv["col"]), mv["domain"]) for mv in METRICS.values()) if n is not None]
        prev_composite = sum(p_norms) / len(p_norms) if p_norms else None

    stat_rows = [
        ("Heat Index Risk",     "heat_index_risk",     r.get("heat_index_risk"),     "/ 100", norm_val(r.get("heat_index_risk"),     (0, 80))),
        ("Hospital Capacity %", "total_capacity_pct",  r.get("total_capacity_pct"),  "%",     norm_val(r.get("total_capacity_pct"),  (50, 100))),
        ("ICU Capacity %",      "icu_capacity_pct",    r.get("icu_capacity_pct"),    "%",     norm_val(r.get("icu_capacity_pct"),    (50, 100))),
        ("ED Wait Hours",       "ed_wait_hours",       r.get("ed_wait_hours"),       " hrs",  norm_val(r.get("ed_wait_hours"),       (0, 24))),
        ("Transit Delay Index", "transit_delay_index", r.get("transit_delay_index"), "",      norm_val(r.get("transit_delay_index"), (0, 60))),
    ]

    rows_html = ""
    for label, col, val, unit, risk in stat_rows:
        dot  = _dot_color(risk)
        vfmt = f"{round(float(val), 1)}{unit}" if (val is not None and pd.notna(val)) else "—"
        prev_val = prev_r.get(col) if prev_r is not None else None
        arrow, ac = _trend_arrow(val, prev_val)
        rows_html += (
            f'<div style="display:flex;align-items:center;gap:8px;margin-top:9px;">'
            f'  <span style="width:8px;height:8px;border-radius:50%;background:{dot};flex-shrink:0;"></span>'
            f'  <span style="flex:1;color:#334155;">{_esc(label)}</span>'
            f'  <span style="font-weight:500;color:#0f172a;">{_esc(vfmt)}</span>'
            f'  <span style="font-size:11px;color:{ac};font-weight:600;">{arrow}</span>'
            f'</div>'
        )

    comp_dot              = _dot_color(composite_risk)
    comp_fmt              = f"{composite_val} / 100" if composite_val is not None else "—"
    comp_arrow, comp_ac   = _trend_arrow(composite_val, prev_composite, tol=0.5)
    comp_row = (
        f'<div style="border-top:1px solid rgba(0,0,0,0.08);margin-top:12px;padding-top:10px;">'
        f'  <div style="display:flex;align-items:center;gap:8px;">'
        f'    <span style="width:8px;height:8px;border-radius:50%;background:{comp_dot};flex-shrink:0;"></span>'
        f'    <span style="flex:1;font-weight:600;color:#0f172a;">Composite Risk Score</span>'
        f'    <span style="font-weight:600;color:#0f172a;">{_esc(comp_fmt)}</span>'
        f'    <span style="font-size:11px;color:{comp_ac};font-weight:600;">{comp_arrow}</span>'
        f'  </div>'
        f'</div>'
    )

    return (
        f'<div style="{_CARD_CSS}">'
        f'{header}'
        f'<div style="margin-top:10px;">{rows_html}{comp_row}</div>'
        f'</div>'
    )


def _top_risk_html(risk_df, layer_info):
    hdr = '<div style="font-weight:700;color:#0f172a;margin-bottom:8px;">Top Communities At Risk</div>'
    if risk_df is None or risk_df.empty or "display_val" not in risk_df.columns:
        return (
            f'<div style="{_OVERLAY_CSS}">{hdr}'
            f'<div style="color:#64748b;font-size:12px;">No data.</div></div>'
        )

    top  = risk_df.nlargest(5, "display_val")
    unit = layer_info.get("unit", "")
    metric_lbl = layer_info["label"]
    rows = ""
    for _, r in top.iterrows():
        name = _esc((r.get("neighborhood") or "") + "  " + (r.get("cd_id") or ""))
        val  = r.get("display_val")
        vstr = f"{round(float(val), 1)}{unit}" if pd.notna(val) else "—"
        dot  = _dot_color(float(val) if pd.notna(val) else None)
        rows += (
            f'<tr>'
            f'<td style="padding:4px 6px;">'
            f'  <span style="width:7px;height:7px;border-radius:50%;background:{dot};'
            f'  display:inline-block;margin-right:5px;vertical-align:middle;"></span>'
            f'  {name}</td>'
            f'<td style="padding:4px 6px;font-weight:500;text-align:right;">{_esc(vstr)}</td>'
            f'</tr>'
        )

    return (
        f'<div style="{_OVERLAY_CSS}">'
        f'{hdr}'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr style="border-bottom:1px solid #e2e8f0;">'
        f'  <th style="text-align:left;padding:4px 6px;font-weight:600;color:#475569;font-size:12px;">Name</th>'
        f'  <th style="text-align:right;padding:4px 6px;font-weight:600;color:#475569;font-size:12px;">{_esc(metric_lbl)}</th>'
        f'</tr></thead>'
        f'<tbody>{rows}</tbody>'
        f'</table></div>'
    )


def _trend_html(sc, risk_layer, layer_info, date_str, trend_days=30):
    hdr = (
        f'<div style="font-weight:700;color:#0f172a;margin-bottom:6px;">'
        f'Trend '
        f'<span style="font-weight:400;color:#64748b;font-size:11px;">(Past {trend_days} days)</span>'
        f'</div>'
    )
    if not sc or not sc.get("cd_id"):
        return (
            f'<div style="{_OVERLAY_CSS}">{hdr}'
            f'<div style="color:#64748b;font-size:12px;">Select a district to see trend.</div></div>'
        )

    start_d = (pd.Timestamp(date_str) - pd.Timedelta(days=int(trend_days) - 1)).strftime("%Y-%m-%d")
    try:
        series = get_risk_series(sc["cd_id"], start_d, date_str)
    except Exception:
        return f'<div style="{_OVERLAY_CSS}">{hdr}<div style="color:#64748b;font-size:12px;">Trend unavailable.</div></div>'
    if not series:
        return f'<div style="{_OVERLAY_CSS}">{hdr}<div style="color:#64748b;font-size:12px;">No data for this range.</div></div>'

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        return f'<div style="{_OVERLAY_CSS}">{hdr}<div style="color:#64748b;font-size:12px;">Install matplotlib for trend chart.</div></div>'

    sdf = pd.DataFrame(series)
    if risk_layer == "composite":
        for mk, mv in METRICS.items():
            sdf[mk + "_n"] = normalize_metric(sdf[mv["col"]].tolist(), mv["domain"])
        sdf["display_val"] = sdf[[mk + "_n" for mk in METRICS]].mean(axis=1)
    else:
        sdf["display_val"] = sdf[layer_info["col"]]
    sdf["date"] = pd.to_datetime(sdf["date"])

    fig, ax = plt.subplots(figsize=(3.0, 1.6), dpi=100)
    ax.plot(sdf["date"], sdf["display_val"], color="#e74c3c", linewidth=1.5)
    ax.fill_between(sdf["date"], sdf["display_val"], alpha=0.12, color="#e74c3c")
    ax.tick_params(labelsize=8)
    ax.set_xlabel("")
    ax.set_ylabel(layer_info["label"], fontsize=8)
    fig.autofmt_xdate()
    plt.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=(1, 1, 1, 0))
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()

    return (
        f'<div style="{_OVERLAY_CSS}">'
        f'{hdr}'
        f'<img src="data:image/png;base64,{b64}" style="width:100%;height:auto;" alt="Trend"/>'
        f'</div>'
    )


def _legend_html(layer_info):
    """Compact floating legend: continuous gradient bar from green → red."""
    lo, hi = layer_info["domain"]
    unit   = layer_info.get("unit", "").strip()
    label  = layer_info["label"]

    def fmt(v):
        s = str(int(round(v)))
        return s + unit if unit and unit != "/ 100" else s

    lo_lbl = fmt(lo)
    hi_lbl = fmt(hi)

    css = (
        "border-radius:10px;"
        "background:rgba(255,255,255,0.52);"
        "backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);"
        "box-shadow:0 2px 12px rgba(0,0,0,0.08);"
        "padding:10px 13px;"
        "font-family:system-ui,-apple-system,sans-serif;"
        "border:1px solid rgba(255,255,255,0.38);"
        "min-width:160px;"
    )
    return (
        f'<div style="{css}">'
        f'<div style="font-weight:700;font-size:12px;color:#0f172a;margin-bottom:6px;">{_esc(label)}</div>'
        f'<div style="height:10px;border-radius:5px;'
        f'background:linear-gradient(to right,#0d0887,#7e03a8,#cc4778,#f89441,#f0f921);"></div>'
        f'<div style="display:flex;justify-content:space-between;margin-top:3px;">'
        f'  <span style="font-size:11px;color:#64748b;">{_esc(lo_lbl)}</span>'
        f'  <span style="font-size:11px;color:#64748b;">{_esc(hi_lbl)}</span>'
        f'</div>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# App CSS
# ---------------------------------------------------------------------------

APP_CSS = """
html, body { font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 0; overflow: hidden; }

/* Remove all bslib padding so map can be truly full-bleed */
.bslib-page-fill {
    background: linear-gradient(160deg, #f0f4f8 0%, #e2e8f0 100%) !important;
    padding: 0 !important;
    height: 100vh !important;
    overflow: hidden !important;
}
.bslib-sidebar-layout {
    height: 100vh !important;
}
.bslib-sidebar-layout > .bslib-main {
    padding: 0 !important;
    overflow: hidden !important;
    height: 100vh !important;
    max-height: 100vh !important;
}
/* Kill scrollability on every wrapper Shiny/bslib might inject */
.bslib-sidebar-layout > .bslib-main > *,
.bslib-sidebar-layout > .bslib-main > * > * {
    overflow: hidden !important;
    max-height: 100vh !important;
}

/* Sidebar */
.bslib-sidebar-layout > .bslib-sidebar-panel {
    background: rgba(255, 255, 255, 0.92) !important;
    border-right: 1px solid rgba(0, 0, 0, 0.06) !important;
}

/* Map container: fills viewport, slight inset so bottom edge is never clipped */
.map-container {
    position: relative;
    width: 100%;
    height: calc(100vh - 8px);
    overflow: hidden;
    border-radius: 8px;
}
/* Iframe absolutely fills the container — bypasses all Shiny output wrapper divs */
.map-container iframe {
    position: absolute !important;
    top: 0 !important;
    left: 0 !important;
    width: 100% !important;
    height: 100% !important;
    border: none !important;
    z-index: 1;
}

/* Floating control bar — transparent, overlaid on top of the map */
.overlay-controls {
    position: absolute;
    top: 12px;
    left: 12px;
    right: 12px;
    z-index: 20;
    display: flex;
    flex-wrap: nowrap;
    align-items: center;
    gap: 8px;
    background: transparent;
    padding: 0;
}
/* Each input container grows/shrinks to fill the bar */
.overlay-controls .shiny-input-container,
.overlay-controls .form-group {
    flex: 1;
    min-width: 70px;
    margin-bottom: 0 !important;
    min-height: unset !important;
}
/* Search bar gets more space */
.overlay-controls .shiny-input-container:first-child { flex: 2.5; min-width: 160px; }
/* Hide all labels */
.overlay-controls label { display: none !important; }
/* White pill inputs */
.overlay-controls input,
.overlay-controls select {
    background: #ffffff !important;
    border-radius: 10px !important;
    font-size: 13px !important;
    height: 38px !important;
    min-height: 38px !important;
    padding: 4px 12px !important;
    border: 1px solid rgba(0,0,0,0.08) !important;
    box-shadow: 0 1px 6px rgba(0,0,0,0.08) !important;
    width: 100% !important;
}
/* Selectize type-ahead — match pill style */
.overlay-controls .selectize-input {
    background: #ffffff !important;
    border-radius: 10px !important;
    font-size: 13px !important;
    min-height: 38px !important;
    height: 38px !important;
    line-height: 28px !important;
    padding: 4px 12px !important;
    border: 1px solid rgba(0,0,0,0.08) !important;
    box-shadow: 0 1px 6px rgba(0,0,0,0.08) !important;
    cursor: text !important;
    display: flex !important;
    align-items: center !important;
}

.overlay-controls .selectize-input.focus {
    border-color: #2563eb !important;
    box-shadow: 0 0 0 2px rgba(37,99,235,0.15) !important;
}
.overlay-controls .selectize-dropdown {
    border-radius: 10px !important;
    box-shadow: 0 4px 20px rgba(0,0,0,0.12) !important;
    font-size: 13px !important;
    border: 1px solid rgba(0,0,0,0.08) !important;
    margin-top: 4px !important;
    overflow: hidden !important;
}
.overlay-controls .selectize-dropdown .option {
    padding: 7px 12px !important;
    cursor: pointer !important;
}
.overlay-controls .selectize-dropdown .option:hover,
.overlay-controls .selectize-dropdown .option.active {
    background: #eff6ff !important;
    color: #1d4ed8 !important;
}

/* Search button */
.overlay-controls .action-button {
    flex-shrink: 0;
    height: 38px;
    min-height: 38px;
    font-size: 13px;
    font-weight: 500;
    border-radius: 10px;
    background-color: #2563eb !important;
    color: white !important;
    border: none !important;
    padding: 0 20px;
    box-shadow: 0 1px 6px rgba(37,99,235,0.3) !important;
    white-space: nowrap;
}
.overlay-controls .action-button:hover { background-color: #1d4ed8 !important; }

/* Overlay cards */
.overlay-stats { position: absolute; top: 68px; right: 12px; z-index: 10; }

/* Legend: bottom right, above leaflet attribution */
.overlay-legend { position: absolute; bottom: 28px; right: 12px; z-index: 10; }

/* Bottom row: Top Communities + Trend side by side, floating inside map */
.overlay-bottom-row {
    position: absolute;
    bottom: 12px;
    left: 12px;
    z-index: 10;
    display: flex;
    gap: 10px;
    align-items: flex-end;
    max-width: 780px;
    pointer-events: none;
}
.overlay-bottom-row > div {
    pointer-events: all;
    flex: 1;
    min-width: 280px;
    max-width: 380px;
}

/* Markdown tables inside chat bubbles */
.chat-bubble-bot table {
    border-collapse: collapse;
    width: 100%;
    font-size: 12px;
    margin: 6px 0;
}
.chat-bubble-bot th, .chat-bubble-bot td {
    border: 1px solid #cbd5e1;
    padding: 5px 8px;
    text-align: left;
}
.chat-bubble-bot th {
    background: rgba(0,0,0,0.06);
    font-weight: 600;
}
.chat-bubble-bot p { margin: 4px 0; }
.chat-bubble-bot strong { font-weight: 700; }

/* Chat bubbles */
.chat-bubble-user {
    background: #2563eb; color: white;
    border-radius: 12px 12px 2px 12px;
    padding: 8px 12px; font-size: 13px;
    margin-left: 20%; margin-bottom: 6px;
}
.chat-bubble-bot {
    background: rgba(0, 0, 0, 0.05); color: #0f172a;
    border-radius: 12px 12px 12px 2px;
    padding: 8px 12px; font-size: 13px;
    margin-right: 20%; margin-bottom: 6px;
}
.chat-area { max-height: 360px; overflow-y: auto; padding: 4px; margin-bottom: 8px; }

/* AI Summary tab panels */
.cd-panel {
    background: #f8fafc; border-left: 4px solid #6c757d;
    border-radius: 6px; padding: 14px 16px; margin-bottom: 12px;
}
.cd-panel h5 {
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.07em; color: #64748b; margin: 0 0 8px 0;
}
.cd-panel .ai-content { font-size: 13px; line-height: 1.65; color: #1e293b; }
.cd-panel .ai-content p { margin: 4px 0; }
.cd-panel .ai-content table { border-collapse: collapse; width: 100%; font-size: 12px; margin: 6px 0; }
.cd-panel .ai-content th, .cd-panel .ai-content td { border: 1px solid #e2e8f0; padding: 4px 7px; }
.cd-panel .ai-content th { background: rgba(0,0,0,0.04); font-weight: 600; }
.cd-panel-summary { border-left-color: #e05c2a; }
.cd-panel-recs    { border-left-color: #2a7ae0; }
#ai_summary_tab { overflow-y: auto; max-height: calc(100vh - 120px); padding-top: 8px; }

/* Typing dots indicator */
.typing-indicator { display: flex; align-items: center; gap: 4px; padding: 10px 14px; }
.typing-indicator span {
    display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: #64748b; animation: typing-bounce 1.2s infinite ease-in-out;
}
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing-bounce {
    0%, 60%, 100% { transform: translateY(0); opacity: 0.6; }
    30% { transform: translateY(-6px); opacity: 1; }
}
"""

# ---------------------------------------------------------------------------
# UI definition
# ---------------------------------------------------------------------------

app_ui = ui.page_fillable(
    ui.tags.head(ui.tags.style(APP_CSS)),
    ui.layout_sidebar(
        ui.sidebar(
            ui.h5("NYC Urban Risk", style="font-weight:700;color:#0f172a;margin-bottom:2px;"),
            ui.p("Early Warning System", style="font-size:12px;color:#64748b;margin-top:0;"),
            ui.navset_tab(
                ui.nav_panel(
                    "Chatbot",
                    ui.p("Suggested prompts",
                         style="font-size:12px;color:#64748b;margin:8px 0 4px;"),
                    ui.input_action_button(
                        "prompt1", "Which CDs show rising heat and hospital strain?",
                        class_="btn btn-outline-primary btn-sm w-100 mb-1",
                        style="text-align:left;white-space:normal;"),
                    ui.input_action_button(
                        "prompt2", "Where is risk accelerating the fastest?",
                        class_="btn btn-outline-primary btn-sm w-100 mb-1",
                        style="text-align:left;white-space:normal;"),
                    ui.input_action_button(
                        "prompt3", "How does today compare to similar patterns?",
                        class_="btn btn-outline-primary btn-sm w-100 mb-1",
                        style="text-align:left;white-space:normal;"),
                    ui.input_action_button(
                        "prompt4", "Which agencies need to coordinate?",
                        class_="btn btn-outline-primary btn-sm w-100 mb-1",
                        style="text-align:left;white-space:normal;"),
                    ui.hr(),
                    ui.div(
                        ui.input_action_button(
                            "clear_chat", "Clear chat",
                            class_="btn btn-outline-secondary btn-sm",
                            style="font-size:11px;padding:2px 10px;"),
                        style="text-align:right;margin-bottom:4px;",
                    ),
                    ui.output_ui("chat_messages_ui"),
                    ui.input_text(
                        "chat_input", None,
                        placeholder="Type your question here...", width="100%"),
                    ui.input_action_button(
                        "chat_send", "Send",
                        class_="btn btn-primary btn-sm w-100 mt-1"),
                ),
                ui.nav_panel(
                    "AI Summary",
                    ui.div(ui.output_ui("ai_summary_tab"), id="ai_summary_tab"),
                ),
            ),
            width=320,
        ),
        # ---------- Main area: full-bleed map with all overlays ----------
        ui.div(
            # Full-bleed map iframe
            ui.div(ui.output_ui("map_html"), class_="map-iframe-wrap"),
            # Floating control bar overlaid on map
            ui.div(
                ui.input_selectize(
                    "search_cd", None,
                    choices=CD_CHOICES,
                    selected="",
                    width="100%",
                    options={
                        "placeholder": "Search your community district...",
                        "allowEmptyOption": True,
                        "maxOptions": 80,
                    },
                ),
                ui.input_select(
                    "risk_layer", None,
                    choices={k: v["label"] for k, v in RISK_LAYERS.items()},
                    width="100%"),
                ui.input_select(
                    "sel_month", None,
                    choices=MONTHS_ORD,
                    selected=MONTHS_ORD[-1] if MONTHS_ORD else None,
                    width="100%"),
                ui.input_numeric(
                    "sel_day", None,
                    value=DATE_MAX.day, min=1, max=31, width="100%"),
                ui.input_select(
                    "sel_year", None,
                    choices=YEARS_ORD,
                    selected=YEARS_ORD[-1] if YEARS_ORD else None,
                    width="100%"),
                class_="overlay-controls",
            ),
            # Stats card (top right)
            ui.div(ui.output_ui("cd_stats"), class_="overlay-stats"),
            # Legend (bottom right)
            ui.div(ui.output_ui("legend_ui"), class_="overlay-legend"),
            # Bottom row: Top Communities At Risk + Trend side by side
            ui.div(
                ui.div(ui.output_ui("top_risk_ui")),
                ui.div(ui.output_ui("trend_ui")),
                class_="overlay-bottom-row",
            ),
            class_="map-container",
        ),
    ),
)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def server(input, output, session):

    selected_cd  = reactive.Value(None)
    chat_msgs    = reactive.Value([])
    is_typing    = reactive.Value(False)

    # ---- Date ----------------------------------------------------------------

    @reactive.calc
    def selected_date():
        m_name = input.sel_month()
        m = _MNAMES.index(m_name) + 1 if m_name in _MNAMES else DATE_MAX.month
        y = int(input.sel_year()) if input.sel_year() else DATE_MAX.year
        d = max(1, min(int(input.sel_day() or 1), 31))
        d = min(d, calendar.monthrange(y, m)[1])
        dt = pd.Timestamp(year=y, month=m, day=d).date()
        return max(DATE_MIN, min(DATE_MAX, dt))

    # ---- Risk data -----------------------------------------------------------

    @reactive.calc
    def risk_data():
        try:
            rows = get_risk_data(str(selected_date()))
            return pd.DataFrame(rows) if rows else pd.DataFrame()
        except Exception as e:
            print(f"Risk data error: {e}")
            return pd.DataFrame()

    @reactive.calc
    def prev_risk_data():
        """Risk data 30 days before selected_date — used for trend arrows in stats card."""
        try:
            prev_date = selected_date() - pd.Timedelta(days=30)
            prev_date = max(DATE_MIN, prev_date)
            rows = get_risk_data(str(prev_date))
            return pd.DataFrame(rows) if rows else pd.DataFrame()
        except Exception as e:
            print(f"Prev risk data error: {e}")
            return pd.DataFrame()

    @reactive.calc
    def composite_data():
        df    = risk_data().copy()
        layer = input.risk_layer()
        if df.empty or not layer:
            return df
        if layer == "composite":
            for mk, mv in METRICS.items():
                df[mk + "_n"] = normalize_metric(df[mv["col"]].tolist(), mv["domain"])
            df["display_val"] = df[[mk + "_n" for mk in METRICS]].mean(axis=1)
        else:
            col = RISK_LAYERS[layer]["col"]
            df["display_val"] = pd.to_numeric(df[col], errors="coerce")
        return df

    # ---- Map click -----------------------------------------------------------
    # JS in the folium iframe calls window.parent.Shiny.setInputValue("map_click", ...)
    # Since the Shiny page is the direct parent of the srcdoc iframe, this works correctly.

    @reactive.effect
    def _on_map_click():
        try:
            click = input.map_click()
        except Exception:
            return
        if click and isinstance(click, dict) and click.get("cd_id"):
            selected_cd.set(dict(click))

    # ---- Search (type-ahead selectize — auto-selects on pick) ----------------

    @reactive.effect
    def _on_search():
        cd_id = (input.search_cd() or "").strip()
        if not cd_id or CD_LOOKUP.empty:
            return
        match = CD_LOOKUP[CD_LOOKUP["cd_id"] == cd_id]
        if not match.empty:
            r = match.iloc[0]
            selected_cd.set({
                "cd_id":        r["cd_id"],
                "borough":      r["borough"],
                "neighborhood": r["neighborhood"],
            })

    # ---- Map render ----------------------------------------------------------

    @render.ui
    def map_html():
        cd    = composite_data()
        layer = input.risk_layer()
        li    = RISK_LAYERS[layer]
        risk_by_cd = (
            cd.set_index("cd_id")["display_val"].to_dict()
            if not cd.empty and "display_val" in cd.columns
            else {}
        )
        m = _build_folium_map(BOUNDARIES, risk_by_cd, li["label"])
        # Save to static file — avoids srcdoc size limits and JS escaping issues
        map_path = WWW_DIR / "map.html"
        m.save(str(map_path))
        # Cache-bust so browser reloads on every risk layer / date change
        cache_bust = int(pd.Timestamp.now().timestamp() * 1000)
        # No inline height — CSS absolutely positions the iframe to fill .map-container
        return ui.HTML(
            f'<iframe src="map.html?v={cache_bust}" '
            f'style="width:100%;border:none;" '
            f'title="NYC Risk Map"></iframe>'
        )

    # ---- Stats card ----------------------------------------------------------

    @render.ui
    def cd_stats():
        return ui.HTML(_stats_card_html(selected_cd(), risk_data(), prev_risk_data()))

    # ---- Top risk ------------------------------------------------------------

    @render.ui
    def top_risk_ui():
        li = RISK_LAYERS[input.risk_layer()]
        return ui.HTML(_top_risk_html(composite_data(), li))

    # ---- Trend ---------------------------------------------------------------

    @render.ui
    def trend_ui():
        layer = input.risk_layer()
        return ui.HTML(_trend_html(
            selected_cd(), layer, RISK_LAYERS[layer], str(selected_date()), trend_days=30,
        ))

    # ---- Legend --------------------------------------------------------------

    @render.ui
    def legend_ui():
        return ui.HTML(_legend_html(RISK_LAYERS[input.risk_layer()]))

    # ---- AI Summary tab ------------------------------------------------------

    @render.ui
    async def ai_summary_tab():
        sc = selected_cd()
        if not sc or not sc.get("cd_id"):
            return ui.div(
                ui.p(
                    "Click a district on the map or use search to load its AI summary.",
                    style="font-size:13px;color:#64748b;margin-top:12px;",
                )
            )

        cd_id    = sc["cd_id"]
        name     = sc.get("neighborhood") or cd_id
        borough  = sc.get("borough", "")
        date_str = str(selected_date())

        header = ui.div(
            ui.tags.strong(name, style="font-size:16px;color:#0f172a;"),
            ui.p(f"{borough} | {cd_id}", style="font-size:12px;color:#64748b;margin:2px 0 10px;"),
        )

        loop = asyncio.get_event_loop()
        try:
            summary = await loop.run_in_executor(
                _CHAT_EXECUTOR, lambda: run_cd_summary(cd_id, date_str)
            )
        except Exception as e:
            summary = f"Error generating summary: {e}"

        try:
            recs = await loop.run_in_executor(
                _CHAT_EXECUTOR, lambda: run_cd_recommendations(cd_id, date_str)
            )
        except Exception as e:
            recs = f"Error generating decision signals: {e}"

        return ui.div(
            header,
            ui.div(
                ui.tags.h5("Risk Overview"),
                ui.div(ui.HTML(md_lib.markdown(summary, extensions=["tables", "nl2br"])),
                       class_="ai-content"),
                class_="cd-panel cd-panel-summary",
            ),
            ui.div(
                ui.tags.h5("Decision Signals"),
                ui.div(ui.HTML(md_lib.markdown(recs, extensions=["tables", "nl2br"])),
                       class_="ai-content"),
                class_="cd-panel cd-panel-recs",
            ),
        )

    # ---- Chat ----------------------------------------------------------------

    async def _send_chat(msg):
        if not msg or not msg.strip():
            return
        chat_msgs.set(chat_msgs() + [{"role": "user", "content": msg}])
        is_typing.set(True)
        date_str = str(selected_date())
        try:
            loop   = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                _CHAT_EXECUTOR, lambda: run_chat(msg, date_str, None)
            )
            response = result["response"]
        except Exception as e:
            response = f"Error: {e}"
        finally:
            is_typing.set(False)
        chat_msgs.set(chat_msgs() + [{"role": "assistant", "content": response}])

    @reactive.effect
    @reactive.event(input.clear_chat)
    def _on_clear_chat():
        chat_msgs.set([])

    @reactive.effect
    @reactive.event(input.chat_send)
    async def _on_chat_send():
        await _send_chat(input.chat_input())
        ui.update_text("chat_input", value="")

    @reactive.effect
    @reactive.event(input.prompt1)
    async def _p1():
        await _send_chat("Which neighborhoods show rising heat and hospital strain?")

    @reactive.effect
    @reactive.event(input.prompt2)
    async def _p2():
        await _send_chat("Where is risk accelerating the fastest?")

    @reactive.effect
    @reactive.event(input.prompt3)
    async def _p3():
        await _send_chat("How does today compare to similar historical patterns?")

    @reactive.effect
    @reactive.event(input.prompt4)
    async def _p4():
        await _send_chat("Which agencies need to coordinate?")

    @render.ui
    def chat_messages_ui():
        msgs = chat_msgs()
        if not msgs:
            return ui.div(
                ui.p(
                    "I can help you analyze current risk across NYC Community Districts. "
                    "What do you want to learn about?",
                    style=(
                        "font-size:13px;color:#334155;"
                        "background:rgba(0,0,0,0.04);"
                        "border-radius:8px;padding:10px;margin:0;"
                    ),
                ),
                class_="chat-area",
            )
        items = []
        for m in msgs:
            if m["role"] == "user":
                items.append(ui.div(m["content"], class_="chat-bubble-user"))
            else:
                rendered = md_lib.markdown(
                    m["content"],
                    extensions=["tables", "nl2br"],
                )
                items.append(ui.div(ui.HTML(rendered), class_="chat-bubble-bot"))
        if is_typing():
            items.append(
                ui.div(
                    ui.HTML('<div class="typing-indicator"><span></span><span></span><span></span></div>'),
                    class_="chat-bubble-bot",
                    style="padding:0;background:rgba(0,0,0,0.05);",
                )
            )
        return ui.div(*items, class_="chat-area")


# ---------------------------------------------------------------------------
# App entry point
# ---------------------------------------------------------------------------

# Thread pool for chatbot calls — isolates asyncio.run() from Shiny's event loop
_CHAT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)

app = App(app_ui, server, static_assets=str(WWW_DIR))
