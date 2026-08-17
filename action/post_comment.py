#!/usr/bin/env python3
"""
Posts the gate's evidence as a PR comment via the GitHub REST API.
Standard library only (urllib) for the API call itself, no added
dependency for one HTTP call.

Surfaces all three layers when present:
  Layer 1 (gatekeeper_output.txt)   -- the hard gate, always present
  Layer 2 (review_output.json)      -- AI review, present if
                                        OPENROUTER_API_KEY was configured
  Layer 3 (crossverify_output.json) -- cross-verification of Layer 2's
                                        own claims, present alongside it

Layer 1's verdict is the only one that determines the PASSED/BLOCKED
headline and the exit code that sets the required status check -- Layers
2/3 render as additional sections when present, never change the verdict.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def get_pr_number() -> int | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        return None
    with open(event_path) as f:
        event = json.load(f)
    pr = event.get("pull_request") or event.get("issue")
    return pr.get("number") if pr else None


def build_layer1_section() -> tuple[str, str, str]:
    """Returns (icon, verdict_word, body) for Layer 1."""
    output_path = "gatekeeper_output.txt"
    if not os.path.exists(output_path):
        return "⚠️", "ERROR", "no output captured -- the gate step may not have run."

    with open(output_path) as f:
        raw = f.read()

    passed = "[gate] PASSED" in raw
    blocked = "[gate] BLOCKED" in raw
    icon = "✅" if passed else "🚫" if blocked else "⚠️"
    verdict = "PASSED" if passed else "BLOCKED" if blocked else "ERROR"

    trimmed = raw if len(raw) < 6000 else raw[:6000] + "\n... (truncated)"
    body = (
        f"Ran the base branch's own test files against this PR's code, "
        f"in isolation -- not the PR's own version of those files.\n\n"
        f"<details><summary>Raw evidence</summary>\n\n```\n{trimmed}\n```\n</details>"
    )
    return icon, verdict, body


def build_layer2_3_section() -> str:
    """Returns a markdown section for Layers 2/3, or empty string if not run."""
    review_path = "review_output.json"
    if not os.path.exists(review_path):
        return ""

    review = json.loads(open(review_path).read())
    verdict = review.get("verdict", "unknown")

    if verdict == "skipped":
        return ""  # OPENROUTER_API_KEY not configured -- nothing to show

    icon = {"approve": "✅", "concerns": "⚠️", "error": "❌"}.get(verdict, "❓")
    findings = review.get("findings", [])
    findings_md = "\n".join(f"- {f}" for f in findings) if findings else "_no findings_"

    crossverify_path = "crossverify_output.json"
    crossverify_md = ""
    if os.path.exists(crossverify_path):
        cv = json.loads(open(crossverify_path).read())
        results = cv.get("results", [])
        if results:
            lines = []
            for r in results:
                mark = "✓" if r.get("verified") else "✗ UNVERIFIED"
                lines.append(f"- [{mark}] {r.get('claim', '')} — {r.get('reason', '')}")
            crossverify_md = "\n\n**Cross-verified claims** (checked against the actual diff, not trusted from the review alone):\n" + "\n".join(lines)

    return (
        f"\n\n---\n\n## {icon} Layer 2 review: {verdict}\n\n"
        f"Independent AI review — saw only the raw diff and changed files, no PR description or commit messages.\n\n"
        f"{findings_md}"
        f"{crossverify_md}"
    )


def build_comment_body() -> str:
    icon, verdict, layer1_body = build_layer1_section()
    layer2_3 = build_layer2_3_section()
    return f"## {icon} Attested Gate: {verdict}\n\n{layer1_body}{layer2_3}"


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    pr_number = get_pr_number()

    if not token or not repo or not pr_number:
        print(f"[post_comment] skipping -- missing token={bool(token)}, repo={repo}, pr_number={pr_number}")
        return 0

    url = f"{api_url}/repos/{repo}/issues/{pr_number}/comments"
    body = json.dumps({"body": build_comment_body()}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"[post_comment] posted, status {resp.status}")
    except urllib.error.HTTPError as e:
        print(f"[post_comment] FAILED: {e.code} {e.read().decode(errors='replace')}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
