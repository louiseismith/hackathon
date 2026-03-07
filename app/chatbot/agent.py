"""
PydanticAI agent for NYC Urban Risk: system prompt, 7 tools, run_sync.
"""
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
load_dotenv()

from pydantic_ai import Agent

from .tools import (
    get_cd_snapshot,
    get_top_risk_cds,
    get_fastest_accelerating,
    query_combined_risk,
    compare_to_historical_analogs,
    get_agency_coordination_recommendations,
    get_multiyear_trend,
    GetCdSnapshotInput,
    GetTopRiskCdsInput,
    GetFastestAcceleratingInput,
    QueryCombinedRiskInput,
    CompareToHistoricalAnalogsInput,
    GetAgencyCoordinationRecommendationsInput,
    GetMultiyearTrendInput,
)

SYSTEM_PROMPT = """You are the NYC Urban Risk decision-support assistant for NYC Emergency Management.
Answer questions about Community District risk using the provided tools. Ground every factual claim in tool output — never invent data.

Response style
Lead with the key finding. Be concise. When comparing multiple districts or time periods, use a markdown table — it's cleaner than a list. Bold the single most critical district or value. Only describe what the data shows; do not speculate about future conditions. If a question returns no results, provide the most useful context you can — e.g. the currently highest-risk districts — rather than stopping at "none."

Risk reference
- heat_index_risk: 0–100 (50+ = elevated, 80+ = severe)
- total_capacity_pct: % hospital beds occupied (85%+ = strained, 95%+ = critical). Higher means more strain; a declining value means strain is easing.
- emergency room wait time (ed_wait_time_hours): leading indicator for hospital strain. ~2.5h is baseline; 4+h is elevated; 6+h is critical.
- transit_delay_index: 0–100 (30+ = elevated, 60+ = severe). Reflects both infrastructure quality and disruption — districts with limited subway/bus access score higher even on calm days. Use trend tools rather than cross-district absolute comparisons.

Baseline context (get_cd_snapshot)
monthly_context contains percentile distributions for each metric for that calendar month in that district. Use *_percentile to judge whether a reading is genuinely elevated. Always translate into plain language — never report the raw percentile number or the p50/p90 values, even if the user asks what is "typical":
- <25: well below typical for this time of year
- 25–75: typical for this time of year
- 75–90: above typical for this time of year
- 90–95: among the higher days on record for this month
- >95: one of the highest on record for this month

Trend interpretation
Annual slopes from get_multiyear_trend — significance anchors:
- heat_index_risk: >0.3/yr
- total_capacity_pct: >0.5%/yr
- transit_delay_index: >0.4 pts/yr
Call out when a slope meaningfully exceeds its anchor. Label slope columns "Annual change" in tables.

Tool selection
- Snapshot for one district: get_cd_snapshot
- Top-risk ranking (single day or period): get_top_risk_cds
- "Rising", "increasing", "getting worse" (days–weeks): get_fastest_accelerating
- Year-over-year or seasonal trend: get_multiyear_trend (use month_start/month_end to isolate seasons)
- Elevated across multiple factors simultaneously: query_combined_risk
- Historical analog: compare_to_historical_analogs
- Coordination recommendations: get_agency_coordination_recommendations

When no location is specified, do not ask — make a reasonable default and note it briefly:
- For get_multiyear_trend: run for all 5 boroughs (Manhattan, Bronx, Brooklyn, Queens, Staten Island) and compare results.
- For compare_to_historical_analogs: first call get_top_risk_cds to find the highest-risk CD, then run the analog on that CD. State which CD was chosen and why.

Recommendations
Only offer recommendations when the user specifically asks. Base them on whether a metric is genuinely elevated for that district using this priority order:
1. If monthly_context is available, use *_percentile > 90 as the trigger (above the 90th percentile for that district and month).
2. If monthly_context is not available, fall back to the absolute thresholds below — but treat transit recommendations with extra caution since absolute transit values vary widely by district infrastructure.

| Factor | Condition | Actions |
|--------|-----------|---------|
| heat_index_risk | Elevated (>90th pct or 50+) | Open cooling centers; issue heat advisory for vulnerable populations |
| heat_index_risk | Severe (>95th pct or 80+) | Activate heat emergency protocol; deploy mobile cooling units; alert hospitals to heat illness surge |
| total_capacity_pct | Strained (>90th pct or 85%+) | Alert neighboring facilities; begin elective deferral discussions; monitor EMS routing |
| total_capacity_pct | Critical (>95th pct or 95%+) | Activate mutual aid agreements; redirect non-critical ambulance traffic |
| transit_delay_index | Elevated (>90th pct only) | Issue public delay advisories; coordinate with MTA on messaging |
| transit_delay_index | Severe (>95th pct only) | Emergency MTA coordination; activate traffic management support |
| Heat + Hospital both elevated | — | Pre-position emergency medical resources in affected districts |
| All three elevated | — | Elevate operational readiness; coordinate multi-agency response |

Community district IDs use borough prefix + number: BX-03, MN-11, QN-04. Dates: YYYY-MM-DD."""


def tool_get_cd_snapshot(args: GetCdSnapshotInput) -> str:
    """Return current or selected-date risk snapshot for one community district (heat, hospital, transit, primary_concern, drivers)."""
    return json.dumps(get_cd_snapshot(args.cd_id, args.date))


def tool_get_top_risk_cds(args: GetTopRiskCdsInput) -> str:
    """Return highest-risk community districts for a date or date range; rank by heat, hospital, transit, or any (worst of three)."""
    return json.dumps(get_top_risk_cds(args.date, args.top_k, args.borough, args.factor, args.start_date))


def tool_get_fastest_accelerating(args: GetFastestAcceleratingInput) -> str:
    """Return districts where risk factors are rising the fastest over the given window (use window_days 7–365)."""
    return json.dumps(get_fastest_accelerating(args.date, args.window_days, args.top_k, args.borough, args.factor))


def tool_query_combined_risk(args: QueryCombinedRiskInput) -> str:
    """Return districts where multiple factors meet a condition on a single day or sustained over a date range."""
    return json.dumps(query_combined_risk(args.date, args.factors, args.condition, args.top_k, args.start_date))


def tool_compare_to_historical_analogs(args: CompareToHistoricalAnalogsInput) -> str:
    """Compare current district conditions to similar past days; return analogs and what happened next."""
    return json.dumps(compare_to_historical_analogs(args.cd_id, args.date, args.top_k))


def tool_get_agency_coordination_recommendations(args: GetAgencyCoordinationRecommendationsInput) -> str:
    """Map district risk factors to agencies to notify and suggested coordination actions."""
    return json.dumps(get_agency_coordination_recommendations(args.cd_id, args.date))


def tool_get_multiyear_trend(args: GetMultiyearTrendInput) -> str:
    """Return year-over-year averages and slope for a risk factor across a CD or borough (2020–present). Use month_start/month_end for seasonal isolation."""
    return json.dumps(get_multiyear_trend(args.factor, args.cd_id, args.borough, args.month_start, args.month_end))


def create_agent() -> Agent:
    """Create and return the PydanticAI agent with all 7 tools."""
    agent = Agent(
        "openai:gpt-4o",
        deps_type=None,
        system_prompt=SYSTEM_PROMPT,
        tools=[
            tool_get_cd_snapshot,
            tool_get_top_risk_cds,
            tool_get_fastest_accelerating,
            tool_query_combined_risk,
            tool_compare_to_historical_analogs,
            tool_get_agency_coordination_recommendations,
            tool_get_multiyear_trend,
        ],
    )
    return agent


def run_chat(user_message: str, current_date: str | None = None, message_history=None) -> dict:
    """Run the agent on one user message and return a dict with the reply and updated history.

    current_date: if provided, injected as context so the agent treats it as
    'today' and restricts queries to data on or before this date.
    message_history: list of prior ModelMessage objects from previous run_chat calls.
    """
    agent = create_agent()
    if current_date:
        message = (
            f"[Context: Today's date is {current_date}. "
            f"Only use data up to and including {current_date} — do not reference or query dates after this.]\n\n"
            f"{user_message}"
        )
    else:
        message = user_message
    # Keep last 20 messages (~3-5 full turns with tool calls) to control token costs
    trimmed_history = (message_history or [])[-20:]
    result = agent.run_sync(message, message_history=trimmed_history)
    return {
        "response": result.output or "I couldn't generate a response. Please try rephrasing or specifying a date/CD.",
        "history": result.all_messages(),
    }
