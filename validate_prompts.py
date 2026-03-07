"""
validate_prompts.py — Automated quality checker for the NYC Urban Risk chatbot.

Runs a fixed set of test questions through the chatbot (gpt-4o), scores each
response with gpt-4o-mini as the validator, and prints a summary.

Usage:
    .venv/bin/python validate_prompts.py
    .venv/bin/python validate_prompts.py --date 2023-08-06
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic_ai.messages import ToolReturnPart

# --- Path setup ---
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "app"))
load_dotenv(ROOT / ".env")

from chatbot.agent import run_chat  # noqa: E402

# --- Config ---
DEFAULT_DATE = "2023-08-06"  # summer date for interesting heat/hospital data

TEST_QUESTIONS = [
    "Which neighborhoods show rising heat and hospital strain?",
    "Where is risk accelerating the fastest?",
    "How does today compare to similar historical patterns?",
    "Is summer heat risk getting worse year over year?",
    "How has hospital capacity changed since 2020?",
]

DIMENSIONS = ["faithfulness", "clarity", "actionability", "conciseness", "context"]

VALIDATOR_SYSTEM = (
    "You are a quality reviewer for an AI-powered emergency management "
    "decision-support chatbot. Score the response objectively and return valid JSON."
)

VALIDATOR_PROMPT = """\
Question: {question}

Chatbot response:
{response}

Source data returned by tools (ground truth):
{tool_outputs}

Score on each dimension (1–5):
- faithfulness: All numbers and claims in the response match the source data above; no invented figures (1=hallucinated, 5=fully grounded)
- clarity: Plain language suitable for emergency management professionals; technical metrics explained (1=jargon-heavy, 5=clear)
- actionability: Helps the reader identify what needs attention or a decision (1=no useful guidance, 5=clearly actionable)
- conciseness: Appropriately brief without being terse; no filler (1=verbose, 5=just right)
- context: Historical or seasonal context used correctly when relevant; mark 3 if not applicable (1=misleading, 5=well-contextualized)

Return JSON only:
{{"faithfulness": 1-5, "clarity": 1-5, "actionability": 1-5, "conciseness": 1-5, "context": 1-5, "notes": "one sentence"}}
"""


def generate_response(question: str, date: str) -> tuple[str, str]:
    """Returns (response_text, tool_outputs_summary)."""
    result = run_chat(question, current_date=date, message_history=None)
    tool_outputs = []
    for msg in result["history"]:
        for part in getattr(msg, "parts", []):
            if isinstance(part, ToolReturnPart):
                tool_outputs.append(f"[{part.tool_name}]\n{part.content}")
    tool_summary = "\n\n".join(tool_outputs) if tool_outputs else "No tools called."
    return result["response"], tool_summary


def score_response(question: str, response: str, tool_outputs: str, client: OpenAI) -> dict:
    prompt = VALIDATOR_PROMPT.format(question=question, response=response, tool_outputs=tool_outputs)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": VALIDATOR_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return json.loads(completion.choices[0].message.content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=DEFAULT_DATE, help="Test date (YYYY-MM-DD)")
    args = parser.parse_args()

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    print(f"\nNYC Urban Risk — Prompt Validation")
    print(f"Test date : {args.date}")
    print(f"Questions : {len(TEST_QUESTIONS)}")
    print(f"Validator : gpt-4o-mini")
    print("-" * 72)

    results = []
    for i, question in enumerate(TEST_QUESTIONS, 1):
        print(f"\n[{i}/{len(TEST_QUESTIONS)}] {question}")

        response, tool_outputs = generate_response(question, args.date)
        print(f"  → {len(response)} chars  ", end="", flush=True)

        scores = score_response(question, response, tool_outputs, client)
        scores["question"] = question

        avg = sum(scores[d] for d in DIMENSIONS) / len(DIMENSIONS)
        score_str = "  ".join(f"{d[:5]}={scores[d]}" for d in DIMENSIONS)
        print(f"avg={avg:.1f}  [{score_str}]")
        if scores.get("notes"):
            print(f"  {scores['notes']}")

        results.append(scores)

    # --- Summary ---
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    col_w = 16
    print(f"  {'Dimension':<{col_w}} {'Avg':>5}  {'Distribution'}")
    print(f"  {'-'*col_w}  {'-'*5}  {'-'*30}")
    for d in DIMENSIONS:
        scores_for_dim = [r[d] for r in results]
        avg = sum(scores_for_dim) / len(scores_for_dim)
        bar = "█" * round(avg) + "░" * (5 - round(avg))
        per_q = "  ".join(str(r[d]) for r in results)
        print(f"  {d:<{col_w}} {avg:>5.2f}  {bar}  [{per_q}]")

    overall = sum(sum(r[d] for d in DIMENSIONS) for r in results) / (
        len(results) * len(DIMENSIONS)
    )
    print(f"\n  {'Overall':<{col_w}} {overall:>5.2f}/5\n")


if __name__ == "__main__":
    main()
