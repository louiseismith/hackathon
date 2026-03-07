"""
validate_cd_summaries.py — Quality checker for map CD summary + recommendations panels.

For each test CD, runs both run_cd_summary and run_cd_recommendations, then scores
each with gpt-4o-mini as the validator.

Usage:
    .venv/bin/python scripts/validate_cd_summaries.py
    .venv/bin/python scripts/validate_cd_summaries.py --date 2023-08-06
    .venv/bin/python scripts/validate_cd_summaries.py --cd BX-03 MN-11
    .venv/bin/python scripts/validate_cd_summaries.py --verbose
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic_ai.messages import ToolReturnPart

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
load_dotenv(ROOT / ".env")

from chatbot.agent import run_cd_summary, run_cd_recommendations  # noqa: E402

# --- Config ---
DEFAULT_DATE = "2023-08-06"  # summer date — interesting heat/hospital signal

# Mix of boroughs and risk profiles: EJ-heavy, outer borough, lower-risk Manhattan
DEFAULT_CDS = ["BX-03", "MN-11", "BK-16", "QN-04", "SI-01"]

SUMMARY_DIMENSIONS   = ["faithfulness", "clarity", "conciseness", "context"]
RECS_DIMENSIONS      = ["faithfulness", "calibration", "voice", "conciseness"]

VALIDATOR_SYSTEM = (
    "You are a quality reviewer for an AI-powered emergency management "
    "decision-support tool. Score the response objectively and return valid JSON."
)

SUMMARY_PROMPT = """\
Community district: {cd_id}
Date: {date}

AI risk summary:
{response}

Source data returned by tools (ground truth):
{tool_outputs}

Score on each dimension (1–5):
- faithfulness: Every number and claim matches the source data; nothing invented (1=hallucinated, 5=fully grounded)
- clarity: Plain language suitable for emergency managers; metrics explained without jargon (1=unclear, 5=crystal clear)
- conciseness: Covers the key points in 2-3 sentences without padding (1=too long or too terse, 5=just right)
- context: Monthly/seasonal context used correctly; relative language ("above typical") preferred over raw numbers (1=missing or wrong, 5=well-contextualized)

Return JSON only:
{{"faithfulness": 1-5, "clarity": 1-5, "conciseness": 1-5, "context": 1-5, "notes": "one sentence"}}
"""

RECS_PROMPT = """\
Community district: {cd_id}
Date: {date}

AI decision signals:
{response}

Source data (ground truth):
{tool_outputs}

This panel surfaces early-warning signals for NYC Emergency Management decision-makers — it is NOT
meant to issue operational commands. The goal is to help humans notice what warrants attention.

Threshold: metrics above the 75th percentile for that district and month are early signals worth
mentioning; above 90th percentile warrants proactive language. Below 75th = typical, mention nothing.
Check monthly_context *_percentile fields in the source data to verify.

Score on each dimension (1–5):
- faithfulness: Signals are grounded in actual percentile levels in the source data; nothing invented (1=contradicts data, 5=fully grounded)
- calibration: Correctly surfaces metrics above 75th pct; stays quiet about typical conditions; more urgent above 90th (1=misses signals or raises false alarms, 5=well-calibrated)
- voice: Uses early-warning, decision-support language ("worth monitoring", "consider flagging") — NOT operational commands ("activate", "deploy", "redirect") (1=command language or no useful signal, 5=exactly right register)
- conciseness: 2-3 focused sentences; no padding, no raw number restatement (1=bloated, 5=tight)

Return JSON only:
{{"faithfulness": 1-5, "calibration": 1-5, "voice": 1-5, "conciseness": 1-5, "notes": "one sentence"}}
"""


def extract_tool_outputs(history) -> str:
    parts = []
    for msg in history:
        for part in getattr(msg, "parts", []):
            if isinstance(part, ToolReturnPart):
                parts.append(f"[{part.tool_name}]\n{part.content}")
    return "\n\n".join(parts) if parts else "No tools called."


def score(prompt: str, client: OpenAI) -> dict:
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": VALIDATOR_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return json.loads(completion.choices[0].message.content)


def run_and_score_cd(cd_id: str, date: str, client: OpenAI, verbose: bool) -> dict:
    print(f"\n  [{cd_id}] summary ...", end="", flush=True)
    summary_result = run_cd_summary(cd_id, date, return_history=True)
    tool_outputs_summary = extract_tool_outputs(summary_result["history"])
    summary_scores = score(
        SUMMARY_PROMPT.format(
            cd_id=cd_id, date=date,
            response=summary_result["response"],
            tool_outputs=tool_outputs_summary,
        ),
        client,
    )
    summary_avg = sum(summary_scores[d] for d in SUMMARY_DIMENSIONS) / len(SUMMARY_DIMENSIONS)
    print(f" avg={summary_avg:.1f}  ", end="", flush=True)

    print(f"recs ...", end="", flush=True)
    recs_result = run_cd_recommendations(cd_id, date, return_history=True)
    tool_outputs_recs = extract_tool_outputs(recs_result["history"])
    recs_scores = score(
        RECS_PROMPT.format(
            cd_id=cd_id, date=date,
            response=recs_result["response"],
            tool_outputs=tool_outputs_recs,
        ),
        client,
    )
    recs_avg = sum(recs_scores[d] for d in RECS_DIMENSIONS) / len(RECS_DIMENSIONS)
    print(f"avg={recs_avg:.1f}")

    if summary_scores.get("notes"):
        print(f"    summary  : {summary_scores['notes']}")
    if recs_scores.get("notes"):
        print(f"    recs     : {recs_scores['notes']}")

    if verbose:
        print(f"\n    Summary response:\n    {summary_result['response'].strip()}\n")
        print(f"    Recs response:\n    {recs_result['response'].strip()}\n")

    return {
        "cd_id": cd_id,
        "summary": summary_scores,
        "summary_avg": summary_avg,
        "recs": recs_scores,
        "recs_avg": recs_avg,
    }


def print_dimension_table(label: str, dimensions: list[str], results: list[dict], key: str):
    col_w = 16
    print(f"\n  {label}")
    print(f"  {'Dimension':<{col_w}} {'Avg':>5}  {'Distribution'}")
    print(f"  {'-'*col_w}  {'-'*5}  {'-'*30}")
    for d in dimensions:
        vals = [r[key][d] for r in results]
        avg  = sum(vals) / len(vals)
        bar  = "█" * round(avg) + "░" * (5 - round(avg))
        per_cd = "  ".join(str(v) for v in vals)
        print(f"  {d:<{col_w}} {avg:>5.2f}  {bar}  [{per_cd}]")
    avgs = [r[f"{key}_avg"] for r in results]
    overall = sum(avgs) / len(avgs)
    print(f"  {'Overall':<{col_w}} {overall:>5.2f}/5")
    return overall


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date",    default=DEFAULT_DATE,   help="Test date (YYYY-MM-DD)")
    parser.add_argument("--cd",      nargs="+",              help="CD IDs to test (default: 5 CDs)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    cds    = args.cd or DEFAULT_CDS
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    print(f"\nNYC Urban Risk — CD Summary & Recommendations Validation")
    print(f"Test date  : {args.date}")
    print(f"Districts  : {', '.join(cds)}")
    print(f"Validator  : gpt-4o-mini")
    print("-" * 72)

    results = []
    for i, cd_id in enumerate(cds, 1):
        print(f"[{i}/{len(cds)}]", end="")
        row = run_and_score_cd(cd_id, args.date, client, args.verbose)
        results.append(row)

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    s_overall = print_dimension_table("Risk Summary",         SUMMARY_DIMENSIONS, results, "summary")
    r_overall = print_dimension_table("Recommendations",      RECS_DIMENSIONS,    results, "recs")
    combined  = (s_overall + r_overall) / 2
    print(f"\n  Combined overall: {combined:.2f}/5")
    print(f"  CDs tested: {', '.join(r['cd_id'] for r in results)}\n")


if __name__ == "__main__":
    main()
