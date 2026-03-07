# Chatbot Tools Reference

The AI assistant uses 7 analytical tools backed by a Supabase database of ~133,000 daily records per metric. All tools accept dates in `YYYY-MM-DD` format and district IDs in `BX-03` / `MN-11` / `QN-04` format.

---

### 1. `get_cd_snapshot`
**Purpose:** Full risk snapshot for one community district on a given date.

**Inputs:**
| Parameter | Type   | Description |
|-----------|--------|-------------|
| `cd_id`   | string | Community district ID (e.g. `BX-03`) |
| `date`    | string | Date in YYYY-MM-DD format |

**Returns:** Heat index risk, temperature, humidity, hospital capacity %, ED wait time, transit delay index, primary concern flag, and monthly percentile context (how today compares to the same calendar month historically).

---

### 2. `get_top_risk_cds`
**Purpose:** Rank all 59 community districts by risk on a single day or averaged over a date range.

**Inputs:**
| Parameter    | Type   | Default | Description |
|--------------|--------|---------|-------------|
| `date`       | string | —       | End date (or single day) |
| `start_date` | string | null    | If provided, ranks by average over the range |
| `top_k`      | int    | 10      | Number of districts to return (1–59) |
| `borough`    | string | null    | Filter to one borough |
| `factor`     | string | `any`   | Rank by `heat`, `hospital`, `transit`, or `any` (worst of three) |

**Returns:** Ordered list of districts with all three metric values and the main risk driver.

---

### 3. `get_fastest_accelerating`
**Purpose:** Identify which districts are seeing the fastest increase in risk over a given window.

**Inputs:**
| Parameter     | Type   | Default | Description |
|---------------|--------|---------|-------------|
| `date`        | string | —       | Current date |
| `window_days` | int    | 7       | Lookback window in days (1–90) |
| `top_k`       | int    | 10      | Number of districts to return |
| `borough`     | string | null    | Optional borough filter |
| `factor`      | string | `any`   | Factor to sort by |

**Returns:** Current and prior values for each metric, per-factor acceleration, and which factor is rising fastest.

---

### 4. `query_combined_risk`
**Purpose:** Find districts where multiple risk factors are elevated simultaneously (or sustained over a date range).

**Inputs:**
| Parameter    | Type         | Default    | Description |
|--------------|--------------|------------|-------------|
| `date`       | string       | —          | End date |
| `factors`    | list[string] | —          | e.g. `["heat", "hospital"]` |
| `condition`  | string       | `elevated` | Severity description |
| `start_date` | string       | null       | If provided, finds CDs above thresholds on average over the range |
| `top_k`      | int          | 20         | Max results |

**Thresholds:** heat_index_risk >= 50, total_capacity_pct >= 85%, transit_delay_index >= 30.

**Returns:** Districts meeting all specified factor conditions, with average values and days-elevated counts (range mode).

---

### 5. `compare_to_historical_analogs`
**Purpose:** Find past days that most closely resemble current conditions in a district and show what happened next.

**Inputs:**
| Parameter | Type   | Default | Description |
|-----------|--------|---------|-------------|
| `cd_id`   | string | —       | Community district ID |
| `date`    | string | —       | Current date |
| `top_k`   | int    | 5       | Number of analog days to return (1–20) |

**Returns:** Top-K most similar historical days (by KNN on normalized metric values), with the metric values on those days and the following day (to show what came next).

---

### 6. `get_agency_coordination_recommendations`
**Purpose:** Map current risk conditions to specific agencies and coordination actions (rule-based).

**Inputs:**
| Parameter | Type   | Description |
|-----------|--------|-------------|
| `cd_id`   | string | Community district ID |
| `date`    | string | Date in YYYY-MM-DD format |

**Returns:** Agencies to notify, suggested coordination reason, recommended actions, and urgency level (`moderate` / `elevated` / `high`).

---

### 7. `get_multiyear_trend`
**Purpose:** Show how a risk factor has changed year-over-year for a community district or borough (2020–present).

**Inputs:**
| Parameter     | Type   | Default | Description |
|---------------|--------|---------|-------------|
| `factor`      | string | —       | `heat`, `hospital`, or `transit` |
| `cd_id`       | string | null    | District ID (provide either this or `borough`) |
| `borough`     | string | null    | Borough name |
| `month_start` | int    | null    | Start month for seasonal filter (1–12) |
| `month_end`   | int    | null    | End month for seasonal filter (1–12) |

**Returns:** Annual averages per year, slope (units/year), total change over the period, and trend direction. Use `month_start`/`month_end` to isolate a season (e.g. 6–8 for summer heat trends).
