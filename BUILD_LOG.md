# Build Log

A real, dated record of building PR Gatekeeper — including the parts that didn't work on the first try. We're keeping those in on purpose: a product whose entire pitch is "verify claims instead of trusting them" should be able to show its own verification process working, including on itself.

Every commit hash below is real and checkable in this repo's history.

---

## Phase 1 — Proving the core mechanism (2026-08-08)

Before writing a line of GitHub Action code, we built the smallest possible proof that the core idea works: can a deterministic check catch an AI agent that "fixes" a bug by weakening the test instead of fixing the code?

We built a small demo — a real bug in a discount-calculation function, a real honest test that catches it, and two competing "fixes": one that tampers with the test to match the buggy output, one that actually fixes the code. Using the real `attested` package published to PyPI (not a mock), the gate correctly blocked the tampered fix and passed the honest one, using real exit codes from real `pytest` runs.

We also confirmed a naive "just run the PR's own tests" check would have been fooled completely — the tampered version showed `2 passed`, indistinguishable from a real fix. That gap is the whole reason this product exists.

`a6dcf98` — Initial commit: reward-hacking demo + GitHub Action, both proven against real tests.

---

## Phase 2 — Building the real GitHub Action (2026-08-08)

With the mechanism proven, we built `gate_action.py` to work against real git branches instead of hardcoded test directories — pulling test files from the base branch via `git ls-tree`/`git show`, running the PR's code against them in an isolated copy, and posting the result as a PR comment via the GitHub API.

`ba011ad` — Fixed a metadata typo and a redundant git-fetch step found while reviewing the Action definition before first use.

---

## Phase 3 — First live test: a lesson worth keeping (2026-08-09)

We opened real pull requests against a private test repo — one with the tampered fix, one with the honest fix — to prove the Action works against actual GitHub infrastructure, not just local testing.

The tampered-branch PR showed **BLOCKED**. At first glance, that looked like proof the gate worked. It wasn't — it turned out to be a false BLOCKED caused by an unrelated bug, and we only caught this because the honest-branch PR *also* showed BLOCKED, which it should never have done.

**Root cause:** our test glob matched on filename only, and the repo happened to have three files all named `test_pricing.py` in different directories (part of the demo's own structure). `pytest` refuses to collect two same-named test modules from different packages, so every run failed before it ever checked anything real.

`17d67e8` — Fixed the matcher to use full relative paths instead of filenames.

Once fixed, a second real bug surfaced: the workflow installed `attested` but never installed `pytest` itself, so every prior "local proof" had only worked because `pytest` happened to already be present in those test environments.

`658a648` — Added the missing dependency install step.

**The real lesson, and the reason this is worth documenting rather than smoothing over:** a status label matching the expected direction isn't proof by itself. We only caught both of these because we read the actual raw evidence text on both PRs, not just the green or red badge. Third time was the charm — genuine `pytest` output, real `AssertionError`s on the tampered branch (`assert 40.0 == 45.0`), real `2 passed` on the honest one. That discipline — check the evidence, not the label — is the same discipline the product itself is built around, and it's exactly what caught this.

---

## Phase 4 — Registering the formal spec (2026-08-10)

Once both directions were genuinely proven, we registered `pr-gatekeeper` in our internal revision tracker with a real, automated acceptance test — the same rigor bar applied to every other component we track. No public claim went out before this was in place.

---

## Phase 5 — Layer 2 and Layer 3 (2026-08-10)

With the deterministic gate (Layer 1) solid, we added the two judgment layers: an independent AI review that sees only the raw diff (no PR description, no commit messages — so it can't be swayed by the agent's own narrative), and a cross-verification step that checks the reviewer's own claims against the actual diff before trusting them.

One real design correction made here: the original plan had the AI review dispatched through our own internal infrastructure. That's wrong for a real product — a customer's repo has no dependency on us running anything. We rebuilt Layer 2 as fully self-contained: the customer supplies their own API key as a repo secret, and the Action calls it directly. Zero dependency on anything we operate.

`9587b80` — Layer 2 (self-contained AI review) and Layer 3 (cross-verification) added.

---

## Phase 6 — Tuning against a real account (2026-08-10 – 2026-08-12)

This is the part most build logs would leave out. We're leaving it in because it's a genuinely good demonstration of the adaptive-not-fragile engineering the product needs.

Testing Layer 2 against a real (deliberately modest-balance) OpenRouter account surfaced a real constraint we hadn't designed for: token budgets. Over several real test cycles:

- `44f4e21` — First real run hit an HTTP 402 (insufficient balance) at a default of 2048 tokens. Lowered to 300.
- `1015c53` — 300 was still over budget for this account. Lowered to 150.
- `4ca465f` — A different, input-side 402 then appeared — the review payload was sending full file content alongside the diff, not just the diff. Redesigned to send diff-only, which is both the fix and a better design generally: diffs scale with the size of a change, full files don't.
- `6dafa75` — 150 output tokens was then too *low* — real, coherent review output was getting cut off mid-response. Raised to 220, tightened the prompt to stay concise within a small budget.
- `daea124` — The real turning point: testing a few days later, the account's affordable ceiling had *moved* again (234 → 181) with zero code changes, simply from ordinary account usage. That made clear no fixed number would ever be reliably correct. We rebuilt the token handling to be adaptive: catch a 402, parse the real affordable figure straight out of OpenRouter's own error message, retry once at that number. This is the fix that should hold regardless of what any given account's balance looks like.

Every one of these was found via a real 402 or a real truncated response — none simulated — and every fix was verified against the real error text before being trusted.

---

## Phase 7 — All three layers, live, together (2026-08-12)

With the adaptive fix in place, the full system ran end-to-end for the first time: Layer 1 passed on real `pytest` output, Layer 2 returned a genuine, coherent review with real findings, and — this is the moment worth calling out specifically — **Layer 3 caught something.**

The reviewer's own output included a claim about the diff. Layer 3 checked that claim against the actual diff and correctly flagged it as unverified, because the exact thing the reviewer described wasn't literally present in the code. That's not a hypothetical feature. That's the actual differentiator of this product — verifying the reviewer, not just the coding agent — doing its job on a live run.

One transparency gap was found and fixed immediately after: the reason text for an unverified claim didn't show *what* had been checked, so there was no way to tell from the PR comment alone whether that flag was a real catch or an overly strict pattern match.

`991ee85` — Reason strings now always include the exact pattern or path that was checked.

---

## Where this leaves things

All three layers have run successfully, live, against real GitHub pull requests, using real test infrastructure and a real (not simulated) third-party API. The deterministic gate has independently caught tampered tests. The AI review layer has produced genuine findings. The cross-verification layer has caught a real gap in the review layer's own output. The token-handling is adaptive rather than hand-tuned to one account's balance at one point in time.

What's ahead from here is packaging and distribution, not further proof of the core mechanism: a public repo, a GitHub Marketplace listing, and the reward-hacking demo as the public-facing pitch.
