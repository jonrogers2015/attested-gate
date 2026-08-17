# Attested Gate

Deterministic verification that a PR really fixes what it claims. No model in the check path, so the check can't hallucinate.

## The pitch, provable in two minutes

An AI coding agent "fixes" a bug by weakening the test instead of fixing the code. A naive CI check sees tests pass. An AI reviewer sees a plausible diff and approves it. This gate blocks it — because it runs the *original* test file from the base branch, not whatever the PR's own version says.

**[`demo/`](./demo)** — the mechanism proven against real buggy code: a real bug, a real tampered test, a real gate blocking it, a real honest fix passing. Run it yourself in under two minutes.

**[`action/`](./action)** — the GitHub Action itself. Same mechanism, working against real git branches instead of hardcoded directories, ready to drop into a workflow as a required status check.

## Why

Every well-known AI PR reviewer (CodeRabbit, Copilot Code Review, PR-AF, and others) reads a diff and forms an opinion — no model in that path can prove the code actually does what it claims, because reading a diff isn't running it. This is Layer 1 of a three-layer design: a deterministic, zero-LLM gate as the hard blocker (this repo), an AI review layer for judgment on top of it, and cross-verification of the reviewer's own claims. Layer 1 never calls a model. That's not an implementation detail — it's the whole point.

## Status

Early build. The core mechanism (both `demo/` and `action/`) is proven with real tests on real code. Not yet run end-to-end against a live GitHub PR. Private for now.
