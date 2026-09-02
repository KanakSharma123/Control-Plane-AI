"""Evaluation harness.

Answers the question the Round 2 brief puts last and hardest: how would
you report false positive and false negative rates to a skeptical
stakeholder?

Over-flagging causes alert fatigue and gets the system bypassed.
Under-flagging causes liability. This harness makes that tradeoff a
number you can argue about instead of a claim you have to be trusted on.

    python run_eval.py
    python run_eval.py --by-use-case
    python run_eval.py --sweep
"""
import argparse
import json
from pathlib import Path
from typing import Dict, List

from src.control_engine import LADDER
from src.pipeline import assess

DATA = Path(__file__).resolve().parent / "data" / "demo_cases.json"

# Anything at or above this rung counts as "the system intervened".
INTERVENTION_FLOOR = "EDIT"


def load_cases() -> List[Dict]:
    with open(DATA, encoding="utf-8") as handle:
        return json.load(handle)["cases"]


def intervened(control: str, floor: str = INTERVENTION_FLOOR) -> bool:
    return LADDER.index(control) >= LADDER.index(floor)


def run(floor: str = INTERVENTION_FLOOR, use_case_override: str = None) -> Dict:
    tp = fp = tn = fn = 0
    rows = []
    tier1_runs = 0
    total_latency = 0.0

    for case in load_cases():
        result = assess(
            case_id=case["case_id"],
            use_case=use_case_override or case["use_case"],
            action_type=case["action_type"],
            source_context=case["source_context"],
            generated_action=case["generated_action"],
            samples=case.get("samples", []),
            actual_cost=case.get("actual_cost", 0.30),
            retries=case.get("retries", 0),
            tool_calls=case.get("tool_calls", 1),
        )

        predicted = intervened(result.decision.control, floor)
        actual = case["label_should_intervene"]

        if predicted and actual:
            outcome, tp = "TP", tp + 1
        elif predicted and not actual:
            outcome, fp = "FP", fp + 1
        elif not predicted and actual:
            outcome, fn = "FN", fn + 1
        else:
            outcome, tn = "TN", tn + 1

        tier1_runs += 1 if result.tier1_ran else 0
        total_latency += result.total_latency_ms()

        rows.append(
            {
                "case_id": case["case_id"],
                "title": case["title"],
                "control": result.decision.control,
                "expected_intervention": actual,
                "outcome": outcome,
                "risk": result.health.blocking_risk,
                "criticality": result.criticality.level,
                "confidence": result.decision.confidence,
                "tier1": result.tier1_mode,
                "latency_ms": round(result.total_latency_ms(), 2),
            }
        )

    total = tp + fp + tn + fn
    return {
        "floor": floor,
        "rows": rows,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "total": total,
        "recall": tp / (tp + fn) if (tp + fn) else 0.0,
        "precision": tp / (tp + fp) if (tp + fp) else 0.0,
        "false_positive_rate": fp / (fp + tn) if (fp + tn) else 0.0,
        "false_negative_rate": fn / (fn + tp) if (fn + tp) else 0.0,
        "tier1_share": tier1_runs / total if total else 0.0,
        "mean_latency_ms": total_latency / total if total else 0.0,
    }


def print_report(report: Dict, verbose: bool = True) -> None:
    if verbose:
        print(f"\n{'CASE':<9} {'CONTROL':<9} {'R':<3} {'C':<3} {'CONF':<6} "
              f"{'OUT':<4} {'LAT(ms)':<9} TITLE")
        print("-" * 104)
        for row in report["rows"]:
            print(
                f"{row['case_id']:<9} {row['control']:<9} {row['risk']:<3} "
                f"{row['criticality']:<3} {row['confidence']:<6.2f} "
                f"{row['outcome']:<4} {row['latency_ms']:<9.2f} {row['title'][:44]}"
            )

    print("\n" + "=" * 60)
    print(f"CONFUSION MATRIX   (intervention floor = {report['floor']})")
    print("=" * 60)
    print(f"  True positives  {report['tp']:>3}    False positives {report['fp']:>3}")
    print(f"  False negatives {report['fn']:>3}    True negatives  {report['tn']:>3}")
    print()
    print(f"  Recall (caught / should have caught)  {report['recall']:.1%}")
    print(f"  Precision (correct / all flagged)     {report['precision']:.1%}")
    print(f"  False positive rate                   {report['false_positive_rate']:.1%}")
    print(f"  False negative rate                   {report['false_negative_rate']:.1%}")
    print()
    print(f"  Tier 1 ran on                         {report['tier1_share']:.0%} of traffic")
    print(f"  Mean end-to-end latency               {report['mean_latency_ms']:.1f} ms")
    print("=" * 60)


def sweep() -> None:
    print("\nTuning the over-flag / under-flag tradeoff")
    print("Lower floor = intervene more readily = fewer misses, more noise.\n")
    print(f"{'FLOOR':<9} {'RECALL':<9} {'PRECISION':<11} {'FPR':<8} {'FNR':<8}")
    print("-" * 50)
    for floor in ["MONITOR", "EDIT", "VERIFY", "HOLD", "BLOCK"]:
        r = run(floor=floor)
        print(
            f"{floor:<9} {r['recall']:<9.1%} {r['precision']:<11.1%} "
            f"{r['false_positive_rate']:<8.1%} {r['false_negative_rate']:<8.1%}"
        )
    print(
        "\nUnder-flagging is the more expensive error here, so the shipped "
        f"default floor is {INTERVENTION_FLOOR}."
    )


def by_use_case() -> None:
    print("\nSame 22 cases, three checking policies")
    print("Demonstrates that risk appetite and latency budget are policy, "
          "not engineering.\n")
    print(f"{'USE CASE':<20} {'RECALL':<9} {'FPR':<8} {'TIER 1':<9} {'MEAN LAT':<10}")
    print("-" * 60)
    for use_case in ["customer_chatbot", "internal_copilot", "decision_support"]:
        r = run(use_case_override=use_case)
        print(
            f"{use_case:<20} {r['recall']:<9.1%} {r['false_positive_rate']:<8.1%} "
            f"{r['tier1_share']:<9.0%} {r['mean_latency_ms']:<10.1f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="ControlPlane evaluation harness")
    parser.add_argument("--sweep", action="store_true", help="threshold tradeoff table")
    parser.add_argument("--by-use-case", action="store_true", help="per-policy comparison")
    parser.add_argument("--quiet", action="store_true", help="summary only")
    args = parser.parse_args()

    if args.sweep:
        sweep()
        return
    if args.by_use_case:
        by_use_case()
        return

    print_report(run(), verbose=not args.quiet)


if __name__ == "__main__":
    main()
