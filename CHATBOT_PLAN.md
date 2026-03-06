# Chatbot Plan: NYC Urban Risk — Urban Early Warning System

**Product:** Cloud-based, AI-assisted early warning dashboard for NYC Emergency Management that fuses weather, hospital strain, and transit disruption data into community-district risk insights, historical analogs, and prioritized action recommendations.

**Geographic unit:** NYC Community Districts (59 CDs).  
**Time range:** 2020–2026, daily time-series (synthetic data).  
**Core data:** `heat_index.csv`, `hospital_capacity.csv`, `transit_delays.csv`, community district lookup, and derived **historical analogs** only (no composite risk score).

---

## 1. What the Chatbot Should Be

The chatbot is a **grounded AI decision-support assistant** for NYC Emergency Management.

- It is **not** a generic or freeform Q&A bot.
- It acts like a **city risk analyst** that can:
  - Answer questions about NYC Community District risk
  - Combine **weather stress**, **hospital strain**, and **transit disruption**
  - Explain what is happening, where, why, and how fast it is changing
  - Compare current conditions to **historical analogs**
  - Suggest agency coordination and recommended actions

**Value proposition:** *“Ask a natural-language question, and get a structured, evidence-backed risk summary for NYC Community Districts.”*

---

## 2. The Chatbot’s Role in the Product

The dashboard provides maps, layers, trends, rankings, and district details. The chatbot adds a **natural-language interface** on top of that, so decision-makers can ask:

- “Which community districts show rising heat and hospital strain?”
- “Where are risk factors accelerating the fastest?”
- “How does today compare to similar historical patterns?”
- “Which agencies do we need to notify in high-risk areas?”

The chatbot sits on top of:

- `heat_index.csv`
- `hospital_capacity.csv`
- `transit_delays.csv`
- Community district lookup table
- **Historical analogs table** (computed; no composite risk table)

---

## 3. What the Chatbot Should Know About the Product

**Geographic unit:** NYC Community Districts (59), grouped by borough.

**Time granularity:** Daily time series, 2020-01-01 through 2026-03-06.

**Core risk signals:**


| Domain          | Fields / metrics                                           |
| --------------- | ---------------------------------------------------------- |
| **Temperature** | temperature_f, humidity_pct, heat_index_f, heat_index_risk |
| **Hospital**    | total_capacity_pct, icu_capacity_pct, ed_wait_hours        |
| **Transit**     | transit_delay_index                                        |


**Derived analytics (only):**

- Historical analogs (similar past days/weeks, what happened next)
- Suggested actions / coordination outputs

The chatbot must be able to answer questions about:

- Single district
- Top-ranked districts (by heat, hospital, or transit, or multi-factor)
- Multi-factor risk
- Risk trends over time
- Historical comparisons
- Agency coordination

---

## 4. Architecture: Tool-Using Chatbot

**Flow:**

1. User asks a question in plain English.
2. LLM interprets intent and selects one or more **tools**.
3. Backend queries structured data.
4. Tools return structured JSON.
5. LLM summarizes results for the decision-maker.

**Layers:**


| Layer         | Contents                                                                                                                              |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Data**      | Community districts, heat index, hospital capacity, transit delays, historical analogs                                                |
| **Analytics** | Functions that rank districts, compare dates, compute trends, factor breakdowns, retrieve analogs, map risk to agency recommendations |
| **Agent**     | LLM decides which tools to call, chains them if needed, writes the final response                                                     |
| **UI**        | Shiny dashboard: map, trend charts, rankings, **chatbot panel**                                                                       |


---

## 4a. What You Need (Dependencies & Services)

To build the tools, agent, and chat UI you need the following. Nothing here is a special “chatbot API” product — you use standard libraries and a small API you write so Shiny can talk to the agent.


| Need                        | Purpose                                                                   | What to get                                                                                                                                                                                                                                                                                                                                                                              |
| --------------------------- | ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **LLM API**                 | Chatbot reasoning and tool choice                                         | **OpenAI API key** (or Anthropic, etc.). Store in `.env` as `OPENAI_API_KEY`. The agent calls the LLM for each turn.                                                                                                                                                                                                                                                                     |
| **Agent + tool formatting** | Define tools with clear inputs/outputs so the LLM can call them correctly | **PydanticAI** ([ai.pydantic.dev](https://ai.pydantic.dev/)) — Python library for typed agents and function tools. Use `@agent.tool` so each of your 8 tools has a Pydantic schema; the framework handles tool-calling format for the LLM. Alternative: **OpenAI SDK** with manual tool definitions (JSON schema).                                                                       |
| **Data / tools layer**      | Load CSVs, compute analogs, run tool logic                                | **Python:** `pandas` (and optionally `numpy`) to query `heat_index.csv`, `hospital_capacity.csv`, `transit_delays.csv`. No separate “data API” — tools are just functions that read these (and derived analogs).                                                                                                                                                                         |
| **Chat UI in Shiny**        | Input box + message list in the dashboard                                 | **R/Shiny:** **shinychat** ([CRAN](https://cran.r-project.org/package=shinychat), [docs](https://posit-dev.github.io/shinychat/)) — use `chat_ui()` and handle `input$<id>_user_input`, then send that text to your backend. **Python/Shiny:** Shiny for Python’s **ui.Chat** if the whole app is in Python.                                                                             |
| **Shiny → agent bridge**    | Shiny runs in the browser; the agent runs in Python with PydanticAI       | A **small HTTP API** (e.g. **FastAPI** or **Flask**) that: (1) exposes a POST endpoint (e.g. `/chat`) accepting the user message, (2) runs the PydanticAI agent with your tools, (3) returns the assistant reply. Shiny calls this API (e.g. via `httr::POST()` or `req_perform()`) from the server. This is the “chatbot API” for your app — you build it; it’s not a separate product. |


**Summary:** You need an **LLM API key**, **PydanticAI** (or OpenAI SDK) to define the agent and tools, **pandas** for the tool logic, **shinychat** (or Shiny for Python chat) for the UI, and a **FastAPI/Flask** app that wraps the agent so Shiny can call it. No third-party “Shiny chatbot API” — just your own endpoint that the Shiny chat panel talks to.

### What I need (checklist)

- [ ] **LLM API key** — Get an OpenAI (or Anthropic, etc.) API key; add to `.env` as `OPENAI_API_KEY`.
- [ ] **PydanticAI** — `pip install pydantic-ai` (or use OpenAI SDK and define tools as JSON schemas).
- [ ] **pandas** — `pip install pandas` (and optionally `numpy`) for the data/tools layer.
- [ ] **shinychat** (R) or **ui.Chat** (Shiny for Python) — For the chat UI in the dashboard. R: `install.packages("shinychat")`.
- [ ] **FastAPI or Flask** — `pip install fastapi uvicorn` or `pip install flask` for the small API that Shiny will call (POST `/chat` → run agent → return reply).
- [ ] **Community district + CSVs** — `data/` already has `heat_index.csv`, `hospital_capacity.csv`, `transit_delays.csv`; add or compute historical analogs table for tools.

---

## 5. Chatbot Mission Statement

> The chatbot is an AI-assisted decision-support layer for the NYC Urban Risk dashboard. It answers natural-language questions about community-district-level risk using structured **weather, hospital, transit, and historical analog data**. It retrieves grounded evidence, explains the main drivers of risk, identifies where factors are accelerating, compares current conditions to historical patterns, and suggests agency coordination actions.

---

## 6. Design Principle: Grounded in Tools

The chatbot **must not invent numbers or make unsupported claims.**

Every factual answer must come from:

- Structured data tables
- Derived metrics (e.g., week-over-week change, analogs)
- Explicit query tools

**Rule:** *If the question requires data, use tools first. Only summarize after retrieving the data.*

---

## 7. Tools to Build (8 Tools)

No composite risk score is used; all tools use the three core datasets and historical analogs only.

---

### Tool 1: `get_cd_snapshot`

**Purpose:** Current or selected-date risk snapshot for one community district.

**Inputs:** `cd_id`, `date`

**Output:**

- borough, community district, neighborhood name
- heat_index_risk, temperature_f, humidity_pct
- total_capacity_pct, icu_capacity_pct, ed_wait_hours
- transit_delay_index
- primary_concern (e.g. "heat", "hospital", "transit", "multi-factor")

**Example:** “What is happening in BX-03 today?” / “Give me the current risk for MN-11.”

---

### Tool 2: `get_top_risk_cds`

**Purpose:** Highest-risk community districts for a given date, ranked by a chosen factor or by multi-factor elevation.

**Inputs:** `date`, `top_k`, optional `borough`, optional `factor` ("heat" | "hospital" | "transit" | "any")

**Output:** List of cd_id, district name, borough, heat_index_risk, total_capacity_pct, transit_delay_index, main_risk_driver.

**Example:** “Which districts are highest risk today?” / “Show the top 5 high-risk districts in Queens by hospital strain.”

---

### Tool 3: `get_fastest_accelerating`

**Purpose:** Districts where **one or more risk factors** are rising the fastest (e.g. week-over-week change in heat_index_risk, total_capacity_pct, transit_delay_index).

**Inputs:** `date`, `window_days`, `top_k`, optional `borough`, optional `factor` ("heat" | "hospital" | "transit" | "any")

**Output:** List of cd_id, current vs prior values for the relevant factor(s), acceleration value(s), fastest_rising_factor, rising_flag per factor.

**Example:** “Where is risk accelerating the fastest?” / “Which districts have worsened most in the last 7 days for heat?”

---

### Tool 4: `get_factor_breakdown`

**Purpose:** Explain which risk factors are driving concern in a district.

**Inputs:** `cd_id`, `date`

**Output:** heat_index_risk, total_capacity_pct, transit_delay_index; top_driver, secondary_driver; short narrative (e.g. “Heat and hospital strain elevated”).

**Example:** “Why is East Harlem high risk?” / “What is driving risk in QN-04?”

---

### Tool 5: `query_combined_risk`

**Purpose:** Districts where **multiple factors** meet conditions (e.g. heat and hospital both elevated), without a composite score.

**Inputs:** `date`, `factors` (e.g. ["heat", "hospital"]), `condition` (e.g. "rising", "high", "elevated"), `top_k`

**Output:** List of districts matching the multi-factor condition: cd_id, factor values, combined_pattern_summary.

**Example:** “Which community districts show rising heat and hospital strain?” / “Where are transit delays and hospital stress both elevated?”

---

### Tool 6: `compare_to_historical_analogs`

**Purpose:** Compare current district conditions to similar past days/weeks.

**Inputs:** `cd_id`, `date`, optional `top_k`

**Output:** Top similar historical dates, similarity score, what happened next, short analog narrative.

**Example:** “How does today compare to similar historical patterns?” / “Has this happened before in BX-01?”

---

### Tool 7: `get_borough_rollup`

**Purpose:** District-level conditions summarized at borough level (no composite score).

**Inputs:** `borough`, `date`

**Output:** Average (or median) heat_index_risk, total_capacity_pct, transit_delay_index; highest-concern CDs per factor; main borough-wide drivers; borough trend (e.g. “heat rising”, “hospital stable”).

**Example:** “How is Queens doing overall today?” / “Which borough is most stressed right now?”

---

### Tool 8: `get_agency_coordination_recommendations`

**Purpose:** Map district risk **factors** (heat, hospital, transit) to stakeholder actions and agency coordination.

**Inputs:** `cd_id`, `date`, optional risk_profile (e.g. factor levels if already computed)

**Output:** agencies_to_notify, suggested_coordination_reason, suggested_actions, urgency_level.

**Logic (rule-based):**

- High heat only → Emergency Management, Public Health, cooling centers / city services
- High heat + hospital strain → Emergency Management, Public Health / hospitals, EMS / urgent care
- High transit disruption → Transit Ops, Emergency Management, field logistics / service communication
- Multiple factors elevated → multi-agency coordination

**Example:** “Which agencies should coordinate for high-risk areas?” / “Who needs to be notified for QN-04 today?”

---

## 8. Skills to Build (6 Skills)

**Skills** are reusable workflows the chatbot runs using the tools above.

---

### Skill 1: District Risk Briefing

**Answers:** “What’s happening in BX-03?” / “Summarize current risk in MN-11.”

**Workflow:** `get_cd_snapshot` → `get_factor_breakdown` → optionally `compare_to_historical_analogs` → short district briefing.

**Output:** Current factor levels, main drivers, trend, and whether the situation resembles prior events.

---

### Skill 2: Top-Risk Ranking

**Answers:** “Which districts are highest risk today?” / “Show the top 5 most stressed CDs by hospital strain.”

**Workflow:** `get_top_risk_cds` → optionally `get_factor_breakdown` for top 2–3 → summarize ranking and drivers.

**Output:** Ranked list with a one-sentence explanation per top district.

---

### Skill 3: Risk Acceleration Analysis

**Answers:** “Where is risk accelerating the fastest?” / “Which districts are worsening most rapidly for heat?”

**Workflow:** `get_fastest_accelerating` → optionally `get_factor_breakdown` for top districts → explain what is rising and why.

**Output:** Top accelerating districts and whether the increase is driven by heat, hospital strain, or transit.

---

### Skill 4: Combined Factor Query

**Answers:** “Which community districts show rising heat and hospital strain?” / “Where do we see high hospital strain and transit disruption together?”

**Workflow:** `query_combined_risk` → rank results → explain the combined pattern.

**Output:** District list, factor values, short explanation of why these districts stand out.

---

### Skill 5: Historical Analog Analysis

**Answers:** “How does today compare to similar historical patterns?” / “Have we seen this before in East Harlem?”

**Workflow:** `compare_to_historical_analogs` → summarize top matches and what happened next.

**Output:** Analog dates, similarity, narrative insight. *(Strong differentiator for the hackathon.)*

---

### Skill 6: Coordination & Action Planning

**Answers:** “Which agencies need to coordinate?” / “What should we do in high-risk areas?”

**Workflow:** `get_cd_snapshot` → `get_factor_breakdown` → `get_agency_coordination_recommendations` → summarize coordination.

**Output:** Agencies, why they should coordinate, suggested action notes.

---

## 9. Question Categories the Chatbot Should Support


| Category           | Examples                                                                                                  |
| ------------------ | --------------------------------------------------------------------------------------------------------- |
| **Current status** | “What is the current risk in BX-03?” / “Which borough is under the most strain today?”                    |
| **Ranking**        | “Which districts have the highest heat stress?” / “Where are factors rising fastest?”                     |
| **Multi-factor**   | “Which districts show rising heat and hospital strain?” / “Where are transit and hospital both elevated?” |
| **Historical**     | “What past situations does this resemble?” / “What happened next in similar periods?”                     |
| **Coordination**   | “Who needs to be notified?” / “Which agencies need to coordinate?”                                        |


---

## 10. Recommended Response Format

Every response should follow:

1. **Direct answer** — Answer the question clearly first.
2. **Evidence** — Relevant districts, metrics, trends.
3. **Explanation** — Main drivers (weather, hospital, transit).
4. **Action / coordination** — If relevant, which agencies should monitor or coordinate.

**Example:**

> The community districts showing the strongest combined rise in heat and hospital strain today are BX-01, BX-03, and MN-11. BX-03 is rising fastest, driven by elevated heat-index risk and above-baseline hospital occupancy. This pattern is most similar to late-July 2024 high-heat conditions, which were followed by increased ED wait times. Emergency Management and public health coordination may be warranted in these districts.

---

## 11. System Prompt (Internal)

Suggested system prompt for the chatbot:

> You are the NYC Urban Risk decision-support assistant for NYC Emergency Management. Your job is to answer questions about Community District risk using structured risk tools. You must use tool outputs for factual claims and numerical values. Do not invent data. When responding, explain: what district(s) are affected; the current risk level or trend for heat, hospital, and transit; the main drivers; whether risk is rising or critical for any factor; any relevant historical analogs; and any appropriate agency coordination suggestions.

---

## 12. Using the Synthetic Data

The chatbot can leverage the patterns baked into the synthetic data:

- **Weather:** Gradual warming, environmental justice divergence, increasing heat waves.
- **Hospital:** Winter seasonality, COVID-era surges, post-COVID capacity creep, outer-borough divergence.
- **Transit:** Weather-driven delay spikes, low-infrastructure amplification, infrastructure decay, transit desert divergence.
- **Historical analogs:** e.g. “This resembles July 2024 heat wave conditions,” “winter stress patterns from January 2023,” “elevated disruption profile during Feb 2024 storm impacts.”

---

## 13. Implementation Plan


| Phase                   | Focus                                                                                                                                                                                   |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. Data / analytics** | Clean dataframes for community districts, heat, hospital, transit; **precompute historical analogs** (no composite risk). Optionally precompute week-over-week deltas for acceleration. |
| **2. Tools**            | Implement the 8 tools as Python functions: strict inputs, structured JSON/dict output, query dataframes (or DB).                                                                        |
| **3. Agent**            | Use OpenAI tool calling or a typed framework (e.g. PydanticAI). Classify question type → call one or more tools → summarize.                                                            |
| **4. Skills**           | Map common question types to the 6 skills for consistent, demo-friendly behavior.                                                                                                       |
| **5. UI**               | In Shiny: chat panel, suggested prompts, optionally highlight referenced districts on the map.                                                                                          |


---

## 14. MVP Scope (e.g. 24-Hour Hackathon)

**Must-have tools:**

- `get_cd_snapshot`
- `get_top_risk_cds`
- `get_fastest_accelerating`
- `query_combined_risk`
- `compare_to_historical_analogs`
- `get_agency_coordination_recommendations`

**Must-have skills:**

- District briefing
- Top-risk ranking
- Acceleration analysis
- Combined-factor query
- Historical analog analysis

Borough rollup and factor breakdown can be simplified or deferred if time is tight.

---

## 15. Rule-Based Coordination Logic (Quick Win)

Example mapping (no composite score; use factor thresholds):


| Pattern                     | Agencies / actions                                                   |
| --------------------------- | -------------------------------------------------------------------- |
| High heat only              | Emergency Management, Public Health, cooling centers / city services |
| High heat + hospital strain | Emergency Management, Public Health / hospitals, EMS / urgent care   |
| High transit disruption     | Transit Ops, Emergency Management, field logistics / communication   |
| Multiple factors elevated   | Multi-agency coordination                                            |


Implement as a simple dictionary or rules engine.

---

## 16. Tools vs Skills (One-Sentence Summary)

> In our system, **tools** are structured functions that retrieve or analyze Community District risk data (heat, hospital, transit, analogs). **Skills** are reusable workflows the chatbot uses to answer common stakeholder questions such as district briefings, acceleration analysis, historical comparison, and agency coordination.

---

## 17. Final Chatbot Plan Summary

We will build a **grounded AI chatbot** for the NYC Urban Risk dashboard that answers decision-maker questions about Community District risk using structured **weather, hospital, transit, and historical analog** data only (no composite risk score). The chatbot will use tools such as district snapshots, top-risk rankings by factor, acceleration queries, factor breakdowns, analog comparisons, and agency recommendation functions. On top of these tools we will implement reusable **skills** for district briefings, top-risk analysis, combined-factor queries, historical comparison, and coordination planning. This delivers explainable, data-backed summaries of where risk is rising, what is driving it, how current conditions compare to similar past periods, and which agencies should coordinate.

---

## 18. Positioning for the Hackathon

Present the chatbot as: **“An AI risk analyst for NYC Emergency Management.”**

What you are building:

- A natural-language query interface over structured city-risk data  
- Explainable, actionable output  
- No single composite score — decisions are driven by the three core signals and historical analogs.

