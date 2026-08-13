#!/usr/bin/env python3
"""
PR Gatekeeper -- Layer 2: AI review, self-contained (no Helmward dependency).

Sends ONLY the raw diff to an OpenRouter model -- deliberately no PR
description, no commit messages, no coding agent's own reasoning, so the
reviewer can't be swayed by the agent's own narrative of what it did.
This is the "no shared context" requirement: the reviewer forms its own
opinion from the artifact alone, the same way gate_action.py (Layer 1)
never trusts the PR's own test files.

DIFF-ONLY, not diff + full file content (changed from an earlier version
that sent both). Full file content scales badly -- a single moderately
sized changed file can be many times larger than its own diff, and this
exact tool hit that live: testing with a tiny 1-line change still pulled
in another changed file's ENTIRE ~180-line content and blew a real
OpenRouter prompt-size cap. A unified diff already carries surrounding
context lines, which is enough for a reviewer to judge a change without
needing the whole file -- and it scales with the SIZE OF THE CHANGE, not
the size of whatever file happened to be touched.

ADAPTIVE max_tokens (this is the important part -- read before changing
DEFAULT_MAX_TOKENS again): a fixed default is fundamentally the wrong
approach here, proven by live testing against one real account across a
few days -- the real affordable ceiling moved from 234 to 181 tokens
between two check-ins with no code change at all, because an OpenRouter
balance is a moving target that depletes with ordinary use. No hardcoded
number can stay correct. Instead: call_reviewer() catches a 402, parses
the account's actual current "can only afford N" figure straight out of
OpenRouter's own error message, and retries ONCE with that real number
(minus a small safety margin). This is the durable fix -- every real
customer's account will have a different, changing balance, and this
makes the tool self-adjust to whatever that is rather than needing
anyone to hand-tune a number that will just go stale again.

Adapted from helmward-chat/chat.py's proven OpenRouter-calling pattern
(same headers, same "always set max_tokens explicitly" lesson learned
there) -- reused, not reinvented. No tool-calling loop needed here: this
is a single structured-output completion, not an interactive agent.

Asks for structured JSON output: a verdict, findings, and a list of
specific checkable_claims -- concrete, textually-verifiable statements
("added a test covering the null case") that Layer 3 (crossverify.py)
can independently check against the actual diff, rather than trusting
the reviewer's own account of what it found. Same "don't trust the
self-report" discipline applied to the coding agent in Layer 1, now
applied to the reviewer too.

Reads config from environment:
  OPENROUTER_API_KEY  -- required (repo secret in real usage)
  REVIEW_MODEL         -- OpenRouter model id, default set below
  REVIEW_MAX_TOKENS    -- starting max_tokens for the review completion.
                          Only a STARTING POINT now, not a hard number --
                          see the ADAPTIVE note above. If the account
                          can't afford it, the real affordable figure is
                          parsed from the 402 and retried automatically.
  BASE_REF             -- e.g. "origin/main"
  WORKSPACE            -- checked-out PR working directory

Writes review_output.json to the workspace and exits 0 regardless of
verdict -- Layer 1 (gate_action.py) remains the only hard blocker; this
is judgment signal layered on top, never a merge gate on its own.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "poolside/laguna-s-2.1:free"
DEFAULT_MAX_TOKENS = 220
# Parses OpenRouter's own 402 wording: "...can only afford 181." -- this
# exact phrase was observed live, twice, with two different real numbers.
AFFORD_PATTERN = re.compile(r"can only afford (\d+)")
# Leave a small margin below the parsed figure -- retrying at EXACTLY
# the reported ceiling risks a boundary/rounding edge case tipping it
# over again.
RETRY_SAFETY_MARGIN = 10

REVIEW_SYSTEM_PROMPT = """You are an independent code reviewer. You will be shown a
git diff -- nothing else. You do not see the PR description, commit
messages, or any explanation from whoever wrote this diff. Form your own
judgment from the diff alone.

Respond with ONLY a JSON object, no other text, in exactly this shape:
{
  "verdict": "approve" or "concerns",
  "findings": ["short specific finding", ...],
  "checkable_claims": [
    {"claim": "short description of something you found in the diff",
     "check_type": "pattern_in_diff" or "file_touched",
     "pattern": "a literal string or short regex that should appear in an ADDED line of the diff if this claim is true (for pattern_in_diff only)",
     "path": "the file path this claim is about (for file_touched only)"}
  ]
}

Only include a checkable_claim for something concrete and verifiable --
e.g. "a new test function was added", "error handling was added for X",
"the debug print statement was removed". Do not include vague claims
that can't be reduced to a pattern or a file path. Keep findings short,
one line each -- you have a VERY tight token budget, so be extremely
terse: at most 2 findings, at most 1 checkable_claim, no filler words.
If you have no concerns, verdict is "approve" and findings can be empty,
but still include a checkable_claim for what the diff actually does, if
anything is concretely checkable."""


def get_diff(workspace: Path, base_ref: str) -> str:
    result = subprocess.run(
        ["git", "diff", f"{base_ref}...HEAD"],
        cwd=str(workspace), capture_output=True, text=True,
    )
    return result.stdout


def build_review_input(workspace: Path, base_ref: str) -> str:
    diff = get_diff(workspace, base_ref)
    return f"=== DIFF ({base_ref}...HEAD) ===\n{diff}"


def _post(api_key: str, model: str, review_input: str, max_tokens: int) -> httpx.Response:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/jonrogers2015/pr-gatekeeper",
        "X-Title": "PR Gatekeeper Layer 2 Review",
    }
    # Always set max_tokens explicitly -- omitting it lets the provider
    # default to its own max output (64000 for Sonnet on OpenRouter),
    # which can exceed what a low-balance account can afford and produce
    # a 402 on the very first call rather than a useful response.
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": review_input},
        ],
        "max_tokens": max_tokens,
    }
    return httpx.post(f"{OPENROUTER_URL}/chat/completions", headers=headers,
                       json=body, timeout=120.0)


def _parse_content(resp: httpx.Response) -> dict:
    data = resp.json()
    if "choices" not in data:
        raise RuntimeError(f"Unexpected OpenRouter response: {json.dumps(data)[:600]}")
    content = data["choices"][0]["message"].get("content", "")
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Reviewer did not return valid JSON: {e}\nraw content: {content[:600]}")


def call_reviewer(api_key: str, model: str, review_input: str, max_tokens: int) -> dict:
    resp = _post(api_key, model, review_input, max_tokens)

    if resp.status_code == 402:
        match = AFFORD_PATTERN.search(resp.text)
        if match:
            affordable = int(match.group(1))
            retry_tokens = max(1, affordable - RETRY_SAFETY_MARGIN)
            print(f"[review] 402 at max_tokens={max_tokens}, account can afford {affordable} -- "
                  f"retrying once at {retry_tokens}")
            resp = _post(api_key, model, review_input, retry_tokens)
        else:
            print(f"[review] 402 but could not parse an affordable-tokens figure from: {resp.text[:300]}")

    if resp.status_code != 200:
        raise RuntimeError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:600]}")

    return _parse_content(resp)


def main() -> int:
    workspace = Path(os.environ.get("WORKSPACE", ".")).resolve()
    base_ref = os.environ.get("BASE_REF", "origin/main")
    model = os.environ.get("REVIEW_MODEL", DEFAULT_MODEL)
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    max_tokens_raw = os.environ.get("REVIEW_MAX_TOKENS", "").strip()
    try:
        max_tokens = int(max_tokens_raw) if max_tokens_raw else DEFAULT_MAX_TOKENS
    except ValueError:
        print(f"[review] WARNING: REVIEW_MAX_TOKENS={max_tokens_raw!r} not an integer, using default {DEFAULT_MAX_TOKENS}")
        max_tokens = DEFAULT_MAX_TOKENS

    if not api_key:
        print("[review] OPENROUTER_API_KEY not set -- Layer 2 skipped (Layer 1 gate is unaffected)")
        result = {"verdict": "skipped", "findings": ["OPENROUTER_API_KEY not configured"], "checkable_claims": []}
        (workspace / "review_output.json").write_text(json.dumps(result, indent=2))
        return 0

    review_input = build_review_input(workspace, base_ref)
    print(f"[review] model: {model}")
    print(f"[review] starting max_tokens: {max_tokens}")
    print(f"[review] review input: {len(review_input)} chars")

    try:
        result = call_reviewer(api_key, model, review_input, max_tokens)
    except Exception as e:
        print(f"[review] ERROR calling reviewer: {e}")
        result = {"verdict": "error", "findings": [str(e)], "checkable_claims": []}

    print(f"[review] verdict: {result.get('verdict')}")
    for finding in result.get("findings", []):
        print(f"[review]   - {finding}")

    (workspace / "review_output.json").write_text(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
