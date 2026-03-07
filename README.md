# NYC Urban Risk: Early Warning System

A cloud-based AI decision-support tool for the NYC Department of Emergency Management. Stores and analyzes neighborhood-level time-series data across heat, hospital capacity, and transit — and surfaces AI-generated risk summaries for decision-makers.

---

## Table of contents

- [What it does](#what-it-does)
- [Setup](#setup)
- [Architecture](#architecture)
- [Chatbot tools](#chatbot-tools) — full reference in [CHATBOT_TOOLS.md](CHATBOT_TOOLS.md)
- [Map features](#map-features)
- [Test scenarios](#test-scenarios)
  - [Baseline: Normal conditions (2026-03-06)](#baseline-normal-conditions-2026-03-06)
  - [Scenario 1: Summer heat wave (2025-07-18)](#scenario-1-summer-heat-wave--south-bronx-2025-07-18)
  - [Scenario 2: Post-storm transit disruption (2021-09-02)](#scenario-2-post-storm-transit-disruption--city-wide-2021-09-02)
  - [Scenario 3: Winter hospital strain (2022-01-13)](#scenario-3-winter-hospital-strain--outer-boroughs-2022-01-13)
- [Data](#data)
- [Validation scripts](#validation-scripts)

---

## What it does

NYC Risk Horizon is a split-panel dashboard. The right side is always the map; the left sidebar switches between two modes via tabs.

**Map (right panel)** — An interactive choropleth of all 59 NYC Community Districts, colored by the selected risk metric. Controls at the top let you choose a district, metric, and date; click Search to update. All map values are 7-day rolling averages. Clicking a district opens a summary card (upper right) with all five metrics and a Composite Risk Score, each showing a trend arrow relative to the prior period. Below the map: a ranked "Top Communities At Risk" table and a 30-day trend chart for the active metric.

**AI Summary tab (left sidebar)** — When a district is selected, this tab auto-populates with two AI-generated panels for that district:
- *Risk Overview* — a 2–3 sentence plain-language summary of current conditions
- *Decision Signals* — early-warning language for NYCEM personnel, flagging which domains warrant closer attention

**Chatbot tab (left sidebar)** — A conversational assistant for open-ended analysis. Five suggested prompts are shown on load; users can also type any question. The assistant uses 7 analytical tools backed by a Supabase database of ~133,000 daily records per metric and answers in natural language about current conditions, trends, accelerating risks, and historical patterns.

---

## Setup

### Prerequisites

- Python >= 3.11
- [uv](https://github.com/astral-sh/uv) for Python package management
- A Supabase project with the schema loaded (see `schema.sql`)
- API keys: `OPENAI_API_KEY`, Supabase connection credentials

### 1. Clone and configure environment

```bash
git clone <repo-url>
cd hackathon
```

Create a `.env` file in the project root:

```
OPENAI_API_KEY=sk-...
SUPABASE_HOST=aws-1-us-east-2.pooler.supabase.com
SUPABASE_PORT=5432
SUPABASE_DB=postgres
SUPABASE_USER=...
SUPABASE_PASSWORD=...
```

### 2. Install Python dependencies

```bash
uv venv
uv pip install -r requirements.txt
```

### 3. Load data into Supabase

The processed CSV files are in `data/`. Load them into your Supabase project using `psql`:

```bash
psql "$DATABASE_URL" -f schema.sql

psql "$DATABASE_URL" -c "\copy community_districts FROM 'data/community_districts.csv' CSV HEADER"
psql "$DATABASE_URL" -c "\copy heat_index FROM 'data/heat_index.csv' CSV HEADER"
psql "$DATABASE_URL" -c "\copy hospital_capacity FROM 'data/hospital_capacity.csv' CSV HEADER"
psql "$DATABASE_URL" -c "\copy transit_delays FROM 'data/transit_delays.csv' CSV HEADER"
```

`DATABASE_URL` follows the format `postgresql://user:password@host:port/dbname`.

### 4. Run the app

```bash
uv run shiny run app_ui/app.py
```

The app will be available at `http://localhost:8000`.

---

## Architecture

```
app_ui/
  app.py                 — Shiny for Python app (map tab + chatbot tab)
app/
  backend.py             — Supabase queries for the map (7-day averages)
  nyc_cd_boundaries.geojson
  chatbot/
    agent.py             — PydanticAI agent + run_chat() / run_cd_summary() / run_cd_recommendations()
    tools.py             — 7 tool functions with Pydantic input models
    data_loader.py       — On-demand Supabase queries via SQLAlchemy
    analogs.py           — KNN-based historical analog search
scripts/
  validate_prompts.py    — Chatbot quality checker (GPT-4o scorer)
  validate_cd_summaries.py — Map panel quality checker
  find_test_dates.py     — Query DB for interesting event dates
data/
  community_districts.csv
  heat_index.csv
  hospital_capacity.csv
  transit_delays.csv
  DATA_GENERATION.md     — Synthetic methodology and data documentation
```

**Stack:** Python Shiny + shinychat (frontend) · PydanticAI + GPT-4o (AI agent) · Supabase / PostgreSQL (data store) · Folium / Leaflet (map)

---

## Chatbot tools

The AI assistant uses 7 analytical tools: `get_cd_snapshot`, `get_top_risk_cds`, `get_fastest_accelerating`, `query_combined_risk`, `compare_to_historical_analogs`, `get_agency_coordination_recommendations`, and `get_multiyear_trend`.

See [`CHATBOT_TOOLS.md`](CHATBOT_TOOLS.md) for full parameter tables, return values, and usage notes for each tool.

---

## Map features

- **Date selector** — "Week ending" date picker; map displays 7-day average for heat and hospital metrics, 7-day maximum for transit
- **Metric selector** — Heat Index Risk, Hospital Capacity %, Transit Delay Index
- **Click a district** — Opens a panel with AI-generated Risk Overview (2–3 sentence summary) and Decision Signals (early-warning language for NYCEM personnel)
- **Color scale** — Plasma palette (perceptually uniform, color-blind accessible)

---

## Test scenarios

Three curated test cases demonstrating different risk states, verified against the database. Use these with the chatbot or map.

---

### Baseline: Normal conditions (2026-03-06)

The most recent date in the dataset. Conditions are typical for early March — moderate hospital occupancy, low heat, routine transit. Use this to confirm the system doesn't over-alert under normal conditions and to explore the map interface.

**Suggested queries:**
- "What's the overall risk picture today?" → uses `get_top_risk_cds`
- "Are there any neighborhoods worth watching right now?" → uses `get_cd_snapshot`
- "How does today compare to recent history in BX-03?" → uses `compare_to_historical_analogs`

---

### Scenario 1: Summer heat wave — South Bronx (2025-07-18)

The highest-heat day in the dataset. Average heat_index_risk of 96.7 across the city's highest-risk CDs (BX-01–03, MN-11, BK-16), with multiple districts hitting the maximum score of 100. These neighborhoods — South Bronx, East Harlem, Brownsville — score at the top of [NYC's Heat Vulnerability Index](https://a816-dohbesp.nyc.gov/IndicatorPublic/data-features/hvi/) due to limited green space, low air conditioning prevalence, and concentrated poverty. Demonstrates how overburdened communities run significantly hotter than the city average, and the value of percentile context over absolute thresholds.

**Suggested queries:**
- "What's the risk in BX-03 today?" → uses `get_cd_snapshot`
- "Which neighborhoods have the highest heat risk?" → uses `get_top_risk_cds`
- "Where is heat getting worse year over year?" → uses `get_multiyear_trend`

![AI Summary panel for Longwood/Melrose (BX-02) on July 18, 2025 — severe heat index risk flagged as primary concern](docs/250718_1.png)
![Chatbot response ranking neighborhoods by heat risk on July 18, 2025](docs/250718_2.png)

---

### Scenario 2: Post-storm transit disruption — city-wide (2021-09-02)

Hurricane Ida aftermath — the highest combined-stress day in the entire dataset. Average transit delay index of 91.1 city-wide, with outer Brooklyn and Queens CDs hit hardest. Hospital capacity also elevated (avg 81%) from storm-related ED surge. Demonstrates `get_fastest_accelerating` and `compare_to_historical_analogs`.

**Suggested queries:**
- "Where is risk accelerating the fastest?" → uses `get_fastest_accelerating`
- "How does today compare to similar historical patterns for BK-16?" → uses `compare_to_historical_analogs`
- "Which neighborhoods have elevated transit and hospital risk simultaneously?" → uses `query_combined_risk`

![AI Summary panel for Greenpoint/Williamsburg (BK-01) on September 2, 2021 — transit delay index at record high for the month](docs/210902_1.png)
![Chatbot response identifying neighborhoods with elevated transit and hospital risk simultaneously](docs/210902_2.png)
![Chatbot response continued — Brownsville flagged as having the highest transit delay index](docs/210902_3.png)

---

### Scenario 3: Winter hospital strain — outer boroughs (2022-01-13)

COVID Omicron wave peak — the highest hospital strain day in the dataset. Average total_capacity_pct of 97.5% city-wide, with many CDs at or near 100%. Outer-borough CDs served by community hospitals (e.g. Lincoln in the Bronx, Elmhurst in Queens) are most affected. Demonstrates `get_top_risk_cds` filtered by hospital factor and multi-year trend analysis.

**Suggested queries:**
- "Which neighborhoods show the highest hospital strain?" → uses `get_top_risk_cds` with `factor=hospital`
- "How has hospital capacity changed since 2020 in the Bronx?" → uses `get_multiyear_trend`
- "Is winter hospital strain getting worse year over year?" → uses `get_multiyear_trend` with seasonal filter

![AI Summary panel for Elmhurst/Corona (QN-04) on January 13, 2022 — hospital capacity at maximum, flagged as critical](docs/220113_1.png)
![Chatbot response listing neighborhoods at 100% hospital bed capacity](docs/220113_2.png)
![Chatbot response continued — additional Bronx and Brooklyn districts at critical hospital strain](docs/220113_3.png)

---

## Data

See [`CODEBOOK.md`](CODEBOOK.md) for the full dataset codebook, including schema, variable definitions, modeling assumptions, real-world data source equivalents, and the synthetic trends built into each dataset.

**Coverage:** 59 NYC Community Districts · Daily · 2020-01-01 to 2026-03-06 · ~133,000 rows per table

**Tables:** `community_districts`, `heat_index`, `hospital_capacity`, `transit_delays`

**CSV files** are in `data/` and can be loaded directly into any PostgreSQL instance using `\copy` (see Setup above).

---

## Validation scripts

```bash
# Score chatbot responses on 5 suggested prompts (uses GPT-4o scorer)
uv run scripts/validate_prompts.py --date 2023-08-06 --verbose

# Score map panel AI summaries for specific districts
uv run scripts/validate_cd_summaries.py --date 2021-09-02 --cd BX-03 MN-11 BK-16

# Find interesting dates in the database (event peaks, high-risk days)
uv run scripts/find_test_dates.py
```
