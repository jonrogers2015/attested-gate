#!/usr/bin/env python3
"""
PR Gatekeeper -- Layer 3: cross-verify the reviewer's own claims.

Layer 2 (review.py) produces a list of checkable_claims -- specific,
concrete statements about what the diff does. This step does not trust
those claims either: each one is checked against the ACTUAL diff, the
same "don't trust the self-report" discipline applied to the coding
agent in Layer 1, now applied to the reviewer itself. A reviewer that
hallucinates its own findings is exactly the failure mode this layer
exists to catch -- the whole research pass behind this project found
that LLM-as-judge is itself unreliable, so a claim from Layer 2 is a
claim, not a fact, until something checks it.

Two check types, deliberately simple and deterministic -- no code
execution here (that is Layer 1's job, and Layer 1 already owns the
"run the real tests" responsibility), just textual verification against
the real diff:
  pattern_in_diff -- the pattern must appear in an ADDED line (a line
                     starting with '+', excluding the '+++' file header)
  file_touched    -- the path must appear in the list of changed files

Reads review_output.json (written by review.py) and the same BASE_REF/
WORKSPACE env vars. Writes crossverify_output.json. Does not itself
block the gate -- Layer 1 remains the only hard blocker -- but flags any
claim that doesn't hold up as real, useful signal.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def get_diff_lines(workspace: Path, base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", f"{base_ref}...HEAD"],
        cwd=str(workspace), capture_output=True, text=True,
    )
    return result.stdout.splitlines()


def get_added_lines(diff_lines: list[str]) -> list[str]:
    return [
        line[1:] for line in diff_lines
        if line.startswith("+") and not line.startswith("+++")
    ]


def get_changed_files(workspace: Path, base_ref: str) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=str(workspace), capture_output=True, text=True,
    )
    return {f for f in result.stdout.splitlines() if f}


def check_claim(claim: dict, added_lines: list[str], changed_files: set[str]) -> dict:
    check_type = claim.get("check_type")
    if check_type == "pattern_in_diff":
        pattern = claim.get("pattern", "")
        if not pattern:
            return {**claim, "verified": False, "reason": "no pattern given"}
        try:
            found = any(re.search(pattern, line) for line in added_lines)
        except re.error:
            found = any(pattern in line for line in added_lines)
        return {**claim, "verified": found,
                "reason": (f"pattern {pattern!r} found in an added line" if found else f"pattern {pattern!r} NOT found in any added line")}
    elif check_type == "file_touched":
        path = claim.get("path", "")
        found = path in changed_files
        return {**claim, "verified": found,
                "reason": (f"{path!r} is in the changed-files list" if found else f"{path!r} NOT in the changed-files list")}
    else:
        return {**claim, "verified": False, "reason": f"unknown check_type: {check_type!r}"}


def main() -> int:
    workspace = Path(os.environ.get("WORKSPACE", ".")).resolve()
    base_ref = os.environ.get("BASE_REF", "origin/main")

    review_path = workspace / "review_output.json"
    if not review_path.exists():
        print("[crossverify] no review_output.json found -- nothing to verify")
        (workspace / "crossverify_output.json").write_text(json.dumps({"results": []}, indent=2))
        return 0

    review = json.loads(review_path.read_text())
    claims = review.get("checkable_claims", [])

    if not claims:
        print("[crossverify] reviewer made no checkable claims")
        (workspace / "crossverify_output.json").write_text(json.dumps({"results": []}, indent=2))
        return 0

    diff_lines = get_diff_lines(workspace, base_ref)
    added_lines = get_added_lines(diff_lines)
    changed_files = get_changed_files(workspace, base_ref)

    results = [check_claim(c, added_lines, changed_files) for c in claims]

    verified_count = sum(1 for r in results if r["verified"])
    print(f"[crossverify] {verified_count}/{len(results)} reviewer claims independently confirmed")
    for r in results:
        mark = "OK" if r["verified"] else "UNVERIFIED"
        print(f"[crossverify]   [{mark}] {r.get('claim', '')} -- {r['reason']}")

    (workspace / "crossverify_output.json").write_text(json.dumps({"results": results}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
