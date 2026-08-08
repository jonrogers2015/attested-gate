#!/usr/bin/env python3
"""
Posts the gate's evidence as a PR comment via the GitHub REST API.
Standard library only (urllib), no added dependency for one HTTP call.

NOTE: this specific step has not been run against a live GitHub PR from
this sandbox (no real token/PR available here) -- it follows the
documented GitHub REST API contract directly, but should get one real
end-to-end run against an actual PR before this is trusted in production.
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


def build_comment_body() -> str:
    output_path = "gatekeeper_output.txt"
    if not os.path.exists(output_path):
        return "**PR Gatekeeper**: no output captured -- the gate step may not have run."

    with open(output_path) as f:
        raw = f.read()

    passed = "[gate] PASSED" in raw
    blocked = "[gate] BLOCKED" in raw
    icon = "✅" if passed else "🚫" if blocked else "⚠️"
    verdict = "PASSED" if passed else "BLOCKED" if blocked else "ERROR"

    # Trim raw output so the comment stays readable -- full detail collapses
    # into a <details> block rather than dominating the PR conversation.
    trimmed = raw if len(raw) < 6000 else raw[:6000] + "\n... (truncated)"

    return (
        f"## {icon} PR Gatekeeper: {verdict}\n\n"
        f"Ran the base branch's own test files against this PR's code, "
        f"in isolation -- not the PR's own version of those files.\n\n"
        f"<details><summary>Raw evidence</summary>\n\n```\n{trimmed}\n```\n</details>"
    )


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
