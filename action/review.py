#!/usr/bin/env python3
"""
PR Gatekeeper -- Layer 2: AI review, self-contained (no Helmward dependency).

Sends ONLY the raw diff + full content of changed files to an OpenRouter
model -- deliberately no PR description, no commit messages, no coding
agent's own reasoning, so the reviewer can't be swayed by the agent's own
narrative of what it did. This is the "no shared context" requirement:
the reviewer forms its own opinion from the artifact alone, the same way
gate_action.py (Layer 1) never trusts the PR's own test files.

Adapted from helmward-chat/chat.py's proven OpenRouter-calling pattern
(same headers, same max_tokens discipline to avoid a 402 on a low-balance
account, same "always set max_tokens explicitly" lesson learned there) --
reused, not reinvented. No tool-calling loop needed here: this is a single
structured-output completion, not an interactive agent.

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
  REVIEW_MAX_TOKENS    -- max_tokens for the review completion. Kept
                          deliberately conservative by default (see
                          DEFAULT_MAX_TOKENS below) -- shipping a default
                          that assumes a well-funded account is a real
                          design mistake, not a hypothetical one: this
                          exact script hit a real HTTP 402 in testing
                          ("requested up to 2048 tokens, but can only
                          afford 234") the first time it ran against a
                          real, ordinary OpenRouter balance. Configurable
                          per-repo via the action's review-max-tokens
                          input for anyone who wants richer review output
                          and has the credits for it.
  BASE_REF             -- e.g. "origin/main"
  WORKSPACE            -- checked-out PR working directory

Writes review_output.json to the workspace and exits 0 regardless of
verdict -- Layer 1 (gate_action.py) remains the only hard blocker; this
is judgment signal layered on top, never a merge gate on its own.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
# Deliberately conservative -- see the REVIEW_MAX_TOKENS docstring note
# above for why this isn't 2048 like an earlier version shipped with.
DEFAULT_MAX_TOKENS = 150

REVIEW_SYSTEM_PROMPT = """You are an independent code reviewer. You will be shown a
git diff and the full content of the changed files -- nothing else. You do
not see the PR description, commit messages, or any explanation from
whoever wrote this diff. Form your own judgment from the artifact alone.

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
one line each -- you have a tight token budget, so be terse. If you have
no concerns, verdict is "approve" and findings can be empty, but still
include checkable_claims for what the diff actually does, if anything
is concretely checkable."""


def get_diff(workspace: Path, base_ref: str) -> str:
    result = subprocess.run(
        ["git", "diff", f"{base_ref}...HEAD"],
        cwd=str(workspace), capture_output=True, text=True,
    )
    return result.stdout


def get_changed_files(workspace: Path, base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=str(workspace), capture_output=True, text=True,
    )
    return [f for f in result.stdout.splitlines() if f]


def build_review_input(workspace: Path, base_ref: str) -> str:
    diff = get_diff(workspace, base_ref)
    files = get_changed_files(workspace, base_ref)

    parts = [f"=== DIFF ({base_ref}...HEAD) ===", diff, ""]
    for f in files:
        full_path = workspace / f
        if full_path.is_file():
            try:
                content = full_path.read_text(errors="replace")
            except OSError:
                continue
            parts.append(f"=== FULL FILE CONTENT: {f} ===")
            parts.append(content)
            parts.append("")
    return "\n".join(parts)


def call_reviewer(api_key: str, model: str, review_input: str, max_tokens: int) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/jonrogers2015/pr-gatekeeper",
        "X-Title": "PR Gatekeeper Layer 2 Review",
    }
    # Always set max_tokens explicitly -- omitting it lets the provider
    # default to its own max output (64000 for Sonnet on OpenRouter),
    # which can exceed what a low-balance account can afford and produce
    # a 402 on the very first call rather than a useful response. Same
    # lesson chat.py already learned the hard way -- and the same lesson
    # this script itself had to re-learn live, the first version here
    # still hardcoded 2048 despite the docstring warning about exactly
    # this failure mode.
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": review_input},
        ],
        "max_tokens": max_tokens,
    }
    resp = httpx.post(f"{OPENROUTER_URL}/chat/completions", headers=headers,
                       json=body, timeout=120.0)
    if resp.status_code != 200:
        raise RuntimeError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:600]}")
    data = resp.json()
    if "choices" not in data:
        raise RuntimeError(f"Unexpected OpenRouter response: {json.dumps(data)[:600]}")
    content = data["choices"][0]["message"].get("content", "")
    # Models sometimes wrap JSON in a markdown fence despite instructions --
    # strip it rather than fail outright on an otherwise-valid response.
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Reviewer did not return valid JSON: {e}\nraw content: {content[:600]}")


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
    print(f"[review] max_tokens: {max_tokens}")
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
