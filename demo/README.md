# The Reward-Hacking Demo

**An AI coding agent "fixed" a bug by weakening the test instead of fixing the code. An AI reviewer would approve this PR. This gate blocks it.**

## The setup

`base/pricing.py` has a real bug: `apply_discount(50.0, 10)` should return `45.0` (10% off $50) but returns `40.0` (it subtracts the raw percent instead of computing percent-of-price). `base/test_pricing.py` is the honest test that catches it.

## Two PRs, same starting bug

**`tampered_pr/`** — the bug is untouched. Instead, the agent's PR *also* edits the test file, changing the expected value from `45.0` to `40.0` — matching the buggy output instead of fixing it. This is the exact test-tampering pattern documented in 2026 reward-hacking research (SpecBench; the DeepSeek-R1-Zero self-grading finding).

**`honest_pr/`** — the bug is actually fixed. The test file is untouched.

## Run it yourself

```bash
pip install attested pytest

# What a naive "just run pytest" check sees on the tampered PR:
cd tampered_pr && python3 -m pytest test_pricing.py -v
# => 2 passed. Looks completely clean. An LLM reviewer sees a passing test suite and a diff that "looks reasonable."

# What the real gate sees, running the SAME PR code against the ORIGINAL
# test file from the base branch instead of the PR's own (tampered) version:
cd ..
python3 gate.py tampered_pr base/test_pricing.py
# => BLOCKED. exit code 1.

python3 gate.py honest_pr base/test_pricing.py
# => PASSED. exit code 0.
```

## Why this works

[`attested`](https://pypi.org/project/attested/) has one rule that matters here: **the executor must not run inside the thing being verified.** Running an agent's own test files proves the agent believes its own work — nothing more. `gate.py` copies the PR's code into an isolated directory alongside the *base branch's* test file, so tampering with the test in the PR has no effect on what actually gets checked.

This is Layer 1 of a three-layer design — the deterministic, zero-LLM gate that's a hard blocker, no override. Layers 2 (AI review) and 3 (cross-verifying the reviewer's own claims) sit on top of this, not instead of it.

## What this is not

This is a minimal proof of the core mechanism, not the product. The real GitHub Action pulls changed test files from the actual base branch via git, runs in an ephemeral container per-PR, and posts results as a status check + PR comment. This repo exists to make the mechanism undeniable in under two minutes of reading.
