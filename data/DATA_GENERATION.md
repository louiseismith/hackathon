# Synthetic Data Generation

This document describes how each dataset in the NYC Urban Risk system was generated, including real-world data source equivalents, schema, modeling assumptions, and trends baked into the synthetic data.

All datasets cover **59 NYC Community Districts** at **daily granularity from 2020-01-01 to 2026-03-06** (~133,000 rows per table).

---

## Community Districts (`community_districts.csv`)

Static lookup table mapping CD identifiers to human-readable names.


| Column               | Type    | Description                                 |
| -------------------- | ------- | ------------------------------------------- |
| `cd_id`              | TEXT    | Primary key, e.g. `MN-01`, `BX-03`, `QN-14` |
| `borough`            | TEXT    | Borough name                                |
| `community_district` | INTEGER | CD number within borough (1–18)             |
| `neighborhood`       | TEXT    | Common neighborhood name(s)                 |


**Real-world source:** NYC Department of City Planning community district boundaries.

---

## Heat Index (`heat_index.csv`)

**Real-world source:** NOAA National Weather Service hourly station observations (Central Park, JFK, LaGuardia). CD-level values would be interpolated via nearest-station weighting or ERA5 gridded reanalysis (~9km resolution).

**Frequency:** Daily maximum heat index per CD.


| Column            | Type    | Description                                         |
| ----------------- | ------- | --------------------------------------------------- |
| `cd_id`           | TEXT    | Community district                                  |
| `date`            | DATE    | Observation date                                    |
| `temperature_f`   | NUMERIC | Daily temperature in °F                             |
| `humidity_pct`    | NUMERIC | Relative humidity %                                 |
| `heat_index_f`    | NUMERIC | Heat index in °F (NOAA Rothfusz regression)         |
| `heat_index_risk` | NUMERIC | Normalized risk score 0–100 (80°F → 0, 125°F → 100) |


### Modeling

**Seasonal base:** Sinusoidal temperature curve peaking ~July 19 (day 200), mean 55°F, amplitude ±22°F. Humidity peaks in August, ranging 55–72%.

**Heat index formula:** NOAA Rothfusz regression applied when temperature ≥ 80°F. Below 80°F, temperature is used directly (formula is not valid in cold conditions).

**Urban heat island (UHI):** Each CD has a static temperature offset (–1 to +3°F) based on density and green space. Dense urban cores (Midtown, South Bronx) run hotter; coastal and green CDs (Rockaways, Staten Island) run cooler.

**Synthetic heat wave events:**


| Year | Dates                             | Peak Boost                     |
| ---- | --------------------------------- | ------------------------------ |
| 2020 | Aug 3–10                          | +10°F                          |
| 2021 | Jun 30–Jul 6                      | +10°F                          |
| 2022 | Jul 19–23, Aug 28–Sep 2           | +11°F, +9°F                    |
| 2023 | Jun 15–20, Aug 23–28              | +9°F, +11°F                    |
| 2024 | Jun 17–22, Jul 8–14, Aug 30–Sep 4 | +10°F, +13°F, +9°F             |
| 2025 | Jun 10–15, Jul 15–22, Aug 18–24   | +9°F, +12°F, +10°F (synthetic) |


### Trends

1. **Gradual warming:** +0.5°F/year city-wide, reflecting long-term climate trend.
2. **Environmental justice divergence:** High-vulnerability CDs (South Bronx BX-01–03, East Harlem MN-11, Brownsville BK-16, East New York BK-05, Elmhurst QN-04) warm at 1.5× the city rate, widening the gap between dense/poor and green/wealthy neighborhoods.
3. **Increasing heat wave frequency:** 1 event in 2020 scaling to 3 events in 2025, reflecting increasing frequency of extreme heat events.

---

## Hospital Capacity (`hospital_capacity.csv`)

**Real-world source:** NYS DOH "New York State Statewide COVID-19 Hospital Data" (health.data.ny.gov) — daily hospital-level bed and ICU occupancy. Post-COVID capacity reporting continues through the NYS Healthcare Emergency Preparedness Program (HEPP). ED wait time data would require a data-sharing agreement with NYC Health + Hospitals or a commercial feed; it is not fully public.

Data is reported at the hospital level in reality. CD-level values represent the estimated accessible hospital capacity for residents of that CD, weighted by proximity to serving hospitals. CDs near large academic medical centers (NYP, Bellevue, Mt. Sinai, NYU Langone) have more buffer; CDs served primarily by community hospitals (Lincoln in the Bronx, Elmhurst in Queens) have less.


| Column               | Type    | Description                                       |
| -------------------- | ------- | ------------------------------------------------- |
| `cd_id`              | TEXT    | Community district                                |
| `date`               | DATE    | Observation date                                  |
| `total_capacity_pct` | NUMERIC | % of total beds occupied                          |
| `icu_capacity_pct`   | NUMERIC | % of ICU beds occupied                            |
| `ed_wait_hours`      | NUMERIC | Average ED wait time in hours (leading indicator) |


### Modeling

**Baseline:** 74% total occupancy, 70% ICU. Winter seasonal bump via cosine curve (flu/RSV season). Small summer bump from heat-related illness, correlated with `heat_index_risk`.

**ED wait time:** Base 2.5 hours, rising nonlinearly as total capacity exceeds 80%. Acts as a leading indicator — ED backs up before inpatient beds fill.

**Hospital pressure by CD:** Each CD has a static pressure offset (–5 to +7 percentage points) reflecting local hospital infrastructure. Elmhurst (QN-04) carries the highest pressure (+7), consistent with its role as the COVID epicenter in Queens.

**COVID surge events (Gaussian bumps):**


| Wave    | Peak Date    | Total Boost | ICU Boost             |
| ------- | ------------ | ----------- | --------------------- |
| Wave 1  | Apr 10, 2020 | +22%        | +28%                  |
| Wave 2  | Jan 10, 2021 | +15%        | +18%                  |
| Delta   | Aug 20, 2021 | +10%        | +14%                  |
| Omicron | Jan 12, 2022 | +14%        | +8% (less ICU-severe) |
| BA.5    | Jul 22, 2022 | +5%         | +4%                   |
| XBB     | Jan 18, 2023 | +4%         | +3%                   |


### Trends

1. **Post-COVID baseline creep:** +0.5%/year from 2022 onward, reflecting persistent staffing shortages and deferred care backlog.
2. **Worsening winter seasons:** Winter flu/RSV peak severity increases ~1%/year.
3. **Outer borough divergence:** Non-Manhattan CDs drift +0.4%/year relative to Manhattan, as community hospitals fall further behind academic medical centers in capacity investment.

---

## Transit Delays (`transit_delays.csv`)

**Real-world source:** MTA subway and bus performance data, available via MTA Developer Resources and NYC Open Data. Reported at the route/line level; aggregated to CD level by mapping subway stations and bus routes to community districts.


| Column                | Type    | Description                                                           |
| --------------------- | ------- | --------------------------------------------------------------------- |
| `cd_id`               | TEXT    | Community district                                                    |
| `date`                | DATE    | Observation date                                                      |
| `transit_delay_index` | NUMERIC | Composite delay score 0–100 (0 = no disruption, 100 = severe failure) |


### Modeling

**Transit infrastructure score:** Each CD has a static infrastructure score (20–95) reflecting subway line density and bus network coverage. Manhattan scores highest (70–95); Staten Island and the Rockaways score lowest (20–35). Lower infrastructure scores amplify the impact of weather and events.

**Weather correlation:** A synthetic precipitation signal (gamma-distributed daily rainfall) drives delay spikes, amplified by each CD's vulnerability (inverse of infrastructure score). Extreme heat also contributes a summer component (rail buckling above 95°F).

**COVID dip (2020–2021):** Ridership collapse reduced delay frequency; modeled as an exponential decay term in 2020–2021.

**Major disruption events:**


| Event                              | Dates           | Peak Boost               |
| ---------------------------------- | --------------- | ------------------------ |
| Hurricane Ida flooding             | Sep 1–4, 2021   | +55 (stations inundated) |
| Winter Storm Kenan                 | Jan 28–30, 2022 | +40                      |
| Infrastructure failure (synthetic) | May 15–17, 2023 | +30                      |
| Winter storm                       | Feb 3–5, 2024   | +38                      |
| Synthetic storm                    | Mar 14–16, 2025 | +35                      |


Low-infrastructure CDs (score < 50) receive amplified event impacts.

### Trends

1. **Infrastructure decay:** Baseline delay index increases +0.4 pts/year, reflecting NYC subway aging.
2. **Weather disruptions worsening:** Weather-correlated delay spikes grow ~8% more severe per year.
3. **Transit desert divergence:** CDs with infrastructure score < 50 drift an additional +0.5 pts/year, reflecting underinvestment in outer-borough transit.

---

## Stretch Goal Risk Factors

The following were scoped but not implemented for the initial build:

- **AQI (Air Quality Index):** NOAA/EPA AirNow daily AQI by monitoring station. Key events: Canadian wildfire smoke (June 2023). Correlated with heat index (hot stagnant air = worse ozone).
- **Flood/Precipitation Risk:** NOAA precipitation data. Key events: Hurricane Ida (Sept 2021). Correlated with transit delays.

