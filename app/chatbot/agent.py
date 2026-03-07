"""
PydanticAI agent for NYC Urban Risk: system prompt, 8 tools, run_sync.
"""
import json
from pathlib import Path

from dotenv import load_dotenv

# Load .env from workspace root (5381) when running from hackathon/chatbot
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
load_dotenv()

from pydantic_ai import Agent

from .tools import (
    get_cd_snapshot,
    get_top_risk_cds,
    get_fastest_accelerating,
    get_factor_breakdown,
    query_combined_risk,
    compare_to_historical_analogs,
    get_borough_rollup,
    get_agency_coordination_recommendations,
    GetCdSnapshotInput,
    GetTopRiskCdsInput,
    GetFastestAcceleratingInput,
    GetFactorBreakdownInput,
    QueryCombinedRiskInput,
    CompareToHistoricalAnalogsInput,
    GetBoroughRollupInput,
    GetAgencyCoordinationRecommendationsInput,
)

SYSTEM_PROMPT = """You are the NYC Urban Risk decision-support assistant for NYC Emergency Management.
Your job is to answer questions about Community District risk using structured risk tools.
You must use tool outputs for factual claims and numerical values. Do not invent data.
When responding, explain: what district(s) are affected; the current risk level or trend for heat, hospital, and transit; the main drivers; whether risk is rising or critical for any factor; any relevant historical analogs; and any appropriate agency coordination suggestions.
Respond in this structure: (1) Direct answer (2) Evidence with districts/metrics (3) Explanation of main drivers (4) Action/coordination if relevant.
Community district IDs are like BX-03, MN-11, QN-04 (borough prefix + number). Dates are YYYY-MM-DD. Use today or the date the user asks about.

Skills / question types:
- District briefing: use get_cd_snapshot and get_factor_breakdown (and optionally compare_to_historical_analogs).
- Top-risk ranking: use get_top_risk_cds, optionally get_factor_breakdown for top districts.
- Risk acceleration: use get_fastest_accelerating, optionally get_factor_breakdown.
- Combined factor query: use query_combined_risk for "rising heat and hospital strain" etc.
- Historical analog: use compare_to_historical_analogs.
- Coordination: use get_cd_snapshot, get_factor_breakdown, get_agency_coordination_recommendations."""

# Tool wrappers: single Pydantic arg so schema is clean for the LLM


def tool_get_cd_snapshot(args: GetCdSnapshotInput) -> str:
    """Return current or selected-date risk snapshot for one community district (heat, hospital, transit, primary_concern)."""
    return json.dumps(get_cd_snapshot(args.cd_id, args.date))


def tool_get_top_risk_cds(args: GetTopRiskCdsInput) -> str:
    """Return highest-risk community districts for a date; rank by heat, hospital, transit, or any (worst of three)."""
    return json.dumps(get_top_risk_cds(args.date, args.top_k, args.borough, args.factor))


def tool_get_fastest_accelerating(args: GetFastestAcceleratingInput) -> str:
    """Return districts where risk factors are rising the fastest (week-over-week acceleration)."""
    return json.dumps(get_fastest_accelerating(args.date, args.window_days, args.top_k, args.borough, args.factor))


def tool_get_factor_breakdown(args: GetFactorBreakdownInput) -> str:
    """Explain which risk factors (heat, hospital, transit) are driving concern in a district."""
    return json.dumps(get_factor_breakdown(args.cd_id, args.date))


def tool_query_combined_risk(args: QueryCombinedRiskInput) -> str:
    """Return districts where multiple factors meet a condition (e.g. heat and hospital both elevated)."""
    return json.dumps(query_combined_risk(args.date, args.factors, args.condition, args.top_k))


def tool_compare_to_historical_analogs(args: CompareToHistoricalAnalogsInput) -> str:
    """Compare current district conditions to similar past days; return analogs and what happened next."""
    return json.dumps(compare_to_historical_analogs(args.cd_id, args.date, args.top_k))


def tool_get_borough_rollup(args: GetBoroughRollupInput) -> str:
    """Summarize district-level conditions at borough level (averages, highest-concern CDs, trend)."""
    return json.dumps(get_borough_rollup(args.borough, args.date))


def tool_get_agency_coordination_recommendations(args: GetAgencyCoordinationRecommendationsInput) -> str:
    """Map district risk factors to agencies to notify and suggested coordination actions."""
    return json.dumps(get_agency_coordination_recommendations(args.cd_id, args.date))


def create_agent() -> Agent:
    """Create and return the PydanticAI agent with all 8 tools."""
    agent = Agent(
        "openai:gpt-4o-mini",
        deps_type=None,
        system_prompt=SYSTEM_PROMPT,
        tools=[
            tool_get_cd_snapshot,
            tool_get_top_risk_cds,
            tool_get_fastest_accelerating,
            tool_get_factor_breakdown,
            tool_query_combined_risk,
            tool_compare_to_historical_analogs,
            tool_get_borough_rollup,
            tool_get_agency_coordination_recommendations,
        ],
    )
    return agent


def run_chat(user_message: str, current_date: str | None = None) -> str:
    """Run the agent on one user message and return the assistant reply text.

    current_date: if provided, injected as context so the agent treats it as
    'today' and restricts queries to data on or before this date.
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
    result = agent.run_sync(message)
    return result.output or "I couldn't generate a response. Please try rephrasing or specifying a date/CD."
