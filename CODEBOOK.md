# Dataset Codebook — NYC Urban Risk

This codebook describes the database schema, tables, and variables used in the NYC Urban Risk system. The app reads all data from a Supabase (PostgreSQL) database. CSV exports of the same data are in `data/`.

For methodology — how each dataset was synthetically generated, what real-world sources it models, and what trends are built in — see [`data/DATA_GENERATION.md`](data/DATA_GENERATION.md).

---

## Database

**Host:** Supabase (PostgreSQL), AWS us-east-2
**Connection mode:** Session pooler
**Schema:** `schema.sql` (root of repo)

**Coverage:** 59 NYC Community Districts · Daily · 2020-01-01 through 2026-03-06 · ~133,000 rows per time-series table

### Tables

| Table | Type | Rows |
|-------|------|------|
| `community_districts` | Static lookup | 59 |
| `heat_index` | Time series | ~133,000 |
| `hospital_capacity` | Time series | ~133,000 |
| `transit_delays` | Time series | ~133,000 |

All time-series tables use a composite primary key of `(cd_id, date)` and reference `community_districts(cd_id)`.

### Indexes

Date-based indexes exist on all three time-series tables to support efficient range queries:

```sql
idx_heat_index_date
idx_hospital_capacity_date
idx_transit_delays_date
```

---

## `community_districts`

Static lookup table. Join to any time-series table on `cd_id`.

| Column | Type | Description |
|--------|------|-------------|
| `cd_id` | TEXT (PK) | Community district identifier, e.g. `BX-03`, `MN-11`, `QN-04` |
| `borough` | TEXT | Borough name: `Manhattan`, `Bronx`, `Brooklyn`, `Queens`, `Staten Island` |
| `community_district` | INTEGER | CD number within the borough (1–18) |
| `neighborhood` | TEXT | Common neighborhood name(s) for that district |

**CD ID format:** borough prefix + zero-padded two-digit number. Prefixes: `MN` (Manhattan, 01–12), `BX` (Bronx, 01–12), `BK` (Brooklyn, 01–18), `QN` (Queens, 01–14), `SI` (Staten Island, 01–03).

---

## `heat_index`

Daily heat stress conditions per community district.

| Column | Type | Units | Range | Description |
|--------|------|-------|-------|-------------|
| `cd_id` | TEXT (PK, FK) | — | — | Community district identifier |
| `date` | DATE (PK) | — | 2020-01-01 to 2026-03-06 | Observation date |
| `temperature_f` | NUMERIC(5,1) | °F | ~20–110 | Daily maximum temperature |
| `humidity_pct` | NUMERIC(5,1) | % | ~30–95 | Relative humidity |
| `heat_index_f` | NUMERIC(5,1) | °F | ~20–125 | Apparent temperature (NOAA Rothfusz formula); equals `temperature_f` below 80°F |
| `heat_index_risk` | NUMERIC(5,2) | 0–100 | 0–100 | Normalized risk score: 0 at 80°F heat index, 100 at 125°F. Values below 10 indicate cool/mild conditions. |

**Thresholds:** heat_index_risk ≥ 50 = elevated · ≥ 80 = severe. Used for internal classification (snapshot labels, multi-factor filtering). User-facing recommendations use within-district percentile ranking (>90th percentile) as the primary trigger, with absolute thresholds as fallback only when historical context is unavailable.

**Real-world source equivalent:** NOAA National Weather Service hourly observations (Central Park, JFK, LaGuardia), interpolated to CD level by nearest-station weighting or ERA5 gridded reanalysis (~9 km).

---

## `hospital_capacity`

Daily hospital system load per community district. Values represent estimated accessible capacity for residents of each CD, weighted by proximity to serving hospitals.

| Column | Type | Units | Range | Description |
|--------|------|-------|-------|-------------|
| `cd_id` | TEXT (PK, FK) | — | — | Community district identifier |
| `date` | DATE (PK) | — | 2020-01-01 to 2026-03-06 | Observation date |
| `total_capacity_pct` | NUMERIC(5,1) | % | ~55–100 | Percentage of total hospital beds occupied. Higher = more strained. |
| `icu_capacity_pct` | NUMERIC(5,1) | % | ~55–100 | Percentage of ICU beds occupied. Stored but not surfaced in current app views. |
| `ed_wait_hours` | NUMERIC(5,1) | hours | ~1.5–10 | Average ED wait time. Leading indicator: ED backs up before inpatient beds fill. Baseline ~2.5h · elevated ≥ 4h · critical ≥ 6h. |

**Thresholds:** total_capacity_pct ≥ 85% = strained · ≥ 95% = critical. Used for internal classification and multi-factor filtering. User-facing recommendations use within-district percentile ranking (>90th percentile) as the primary trigger, with absolute thresholds as fallback only when historical context is unavailable.

**Real-world source equivalent:** NYS DOH Statewide Hospital Data (health.data.ny.gov); NYS Healthcare Emergency Preparedness Program (HEPP). ED wait time data is not fully public and would require a data-sharing agreement with NYC Health + Hospitals or a commercial feed.

---

## `transit_delays`

Daily transit disruption level per community district.

| Column | Type | Units | Range | Description |
|--------|------|-------|-------|-------------|
| `cd_id` | TEXT (PK, FK) | — | — | Community district identifier |
| `date` | DATE (PK) | — | 2020-01-01 to 2026-03-06 | Observation date |
| `transit_delay_index` | NUMERIC(5,2) | 0–100 | 0–60+ | Composite delay score reflecting both infrastructure quality and active disruption. Districts with limited subway/bus access score higher even on calm days — interpret relative to each district's own historical baseline, not as an absolute cross-district comparison. |

**Thresholds:** transit_delay_index ≥ 30 = elevated · ≥ 60 = severe. Used for internal classification and multi-factor filtering only. All user-facing recommendations use within-district percentile ranking exclusively (>90th percentile) — no absolute fallback — because absolute values are not meaningful for cross-district comparison.

**Real-world source equivalent:** MTA subway and bus performance data via MTA Developer Resources and NYC Open Data. Reported at route/line level; aggregated to CD level by mapping stations and routes to community district boundaries.

---

## Background

**NYC Community Districts:** NYC is divided into 59 community districts, each governed by a community board. They are the primary sub-borough administrative unit used by city agencies. Boundaries are published by the NYC Department of City Planning; the GeoJSON file used for the map is at `app/nyc_cd_boundaries.geojson`.

**Heat index formula:** The NOAA Rothfusz regression is only valid at temperatures ≥ 80°F. Below that threshold, temperature is used directly as the apparent temperature.

**Hospital capacity:** Bed occupancy above 85% is generally considered strained system-wide. The CD-level values represent a weighted estimate of accessible capacity for residents of that district, not the occupancy of a single hospital. CDs near large academic medical centers (NYP, Bellevue, Mt. Sinai, NYU Langone) have more buffer; CDs served primarily by community hospitals (Lincoln in the Bronx, Elmhurst in Queens) have less.

**Transit delay index:** A given score means something different in a transit-rich district (e.g. MN-06, Midtown) vs. a transit-limited one (e.g. SI-02, mid-Staten Island). Always interpret transit values relative to that district's historical baseline using the monthly percentile context, not as an absolute cross-district comparison.
