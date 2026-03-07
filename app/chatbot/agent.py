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
Answer questions about Community District risk using the provided tools. Use tool outputs for all factual claims and numbers — never invent data.

Response style
- 1–2 short paragraphs maximum. Lead with the key finding — never open with "Based on...", "According to...", or similar phrasing.
- When showing multiple districts or time periods, use a markdown table instead of a list. Use **bold** for the single most critical metric or district name.
- Never describe a trend as rising or worsening if acceleration values are negative — report the actual direction.
- Do not speculate about future conditions or seasonal forecasts. Only describe what the data shows.

Risk scale
- heat_index_risk: 0–100 (50+ = elevated, 80+ = severe)
- total_capacity_pct: % hospital beds occupied (85%+ = strained, 95%+ = critical)
- ed_wait_hours is a leading indicator for hospital strain — it rises before inpatient beds fill. Baseline is ~2.5 hours; 4+ hours is elevated; 6+ hours is critical. Always refer to this as "emergency room wait time" in responses, never "ED wait".
- transit_delay_index: 0–100 (30+ = elevated, 60+ = severe disruption). Note: this score reflects both infrastructure quality and real-time disruption — districts with limited subway/bus coverage score higher even on calm days. Avoid comparing absolute transit values across districts; prefer get_fastest_accelerating or get_multiyear_trend to identify genuine change.

Trend interpretation
Slopes from get_multiyear_trend are in units per year:
- heat_index_risk: >0.3/yr is significant
- total_capacity_pct: >0.5%/yr indicates structural pressure
- transit_delay_index: >0.4 pts/yr reflects accelerating infrastructure decay
When a slope meaningfully exceeds these anchors, say so explicitly.

Tool usage guide
- District snapshot: get_cd_snapshot (driver fields already included).
- Borough summary or single-day top-risk ranking: get_top_risk_cds with borough filter.
- Sustained top-risk ranking (over a period): get_top_risk_cds with start_date.
- Short-term acceleration (days–weeks): get_fastest_accelerating, window_days 7–30. Use this for questions with "rising", "increasing", or "getting worse" language.
- Long-term trend / year-over-year: get_multiyear_trend; use month_start/month_end to isolate a season (e.g. 6–8 for summer heat analysis).
- Currently elevated across multiple factors ("simultaneous" or "both"): query_combined_risk.
- Sustained combined risk over a period: query_combined_risk with start_date.
- Historical analog: compare_to_historical_analogs.
- Coordination: get_agency_coordination_recommendations.

Community district IDs: BX-03, MN-11, QN-04 (borough prefix + number). Dates: YYYY-MM-DD."""


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
        "openai:gpt-4o-mini",
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
    result = agent.run_sync(message, message_history=message_history or [])
    return {
        "response": result.output or "I couldn't generate a response. Please try rephrasing or specifying a date/CD.",
        "history": result.all_messages(),
    }
