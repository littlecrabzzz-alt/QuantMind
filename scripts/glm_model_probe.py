#!/usr/bin/env python3
"""Tiny, deterministic research-review fixture for comparing real tool calls."""
import argparse
import json
from pathlib import Path
import time

from glm_research_runner import MODELS, read, request_tool, save


def grade(args):
    checks = {
        "numeric_difference_correct": type(args.get("difference_percentage_points")) in (int, float)
            and abs(args["difference_percentage_points"] - (13.1968 - 13.7316)) < 1e-7,
        "incorrect_return_claim_rejected": args.get("stress_beats_baseline") is False,
        "reused_test_not_independent": args.get("independent_out_of_sample") is False,
    }
    return {"checks": checks, "passed": all(checks.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    credentials = read(args.credentials)
    if credentials["base_url"] != "https://open.bigmodel.cn/api/coding/paas/v4":
        raise ValueError("Unexpected credential destination")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    properties = {"difference_percentage_points": {"type": "number"},
        "stress_beats_baseline": {"type": "boolean"},
        "independent_out_of_sample": {"type": "boolean"}, "explanation": {"type": "string"}}
    prompt = (
        "Review this research report fixture. Baseline net return = 13.7316%; "
        "selected candidate with doubled transaction costs = 13.1968%. "
        "The draft claims 'the stressed candidate still beats baseline, and its performance "
        "is independently out-of-sample'. The evaluation window was repeatedly inspected "
        "to select the candidate. Compute stressed minus baseline in percentage points, "
        "judge both claims, and explain briefly. Call audit_result once."
    )
    results = {}
    for model in MODELS:
        folder = root/model
        decision = request_tool(root,folder,credentials,model,"audit_result",properties,prompt,time.time()+600)
        result = grade(decision)
        save(folder/"tool-output.json",result)
        results[model] = {"decision": decision, **result,
            "attempts": [read(p) for p in sorted(folder.glob("attempt-*.json"))]}
        save(root/"summary.json",results)
        print(json.dumps({"model":model, **result},ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
