# Attested Gate (GitHub Action)

A required status check that verifies a PR actually fixes what it claims — deterministically, with no model in the check path.

## What it does

Pulls the test files matching `test-glob` as they exist on `base-ref` (the base branch), copies the PR's code into an isolated directory, and runs those *base-branch* test files against it — never the PR's own version of the tests, no matter what changes were made to them.

If an agent (or anyone) "fixes" a failing test by weakening the assertion instead of fixing the code, this catches it: the base branch's original, untampered assertion is what actually runs. See `../pr-gatekeeper-demo` for the mechanism proven end-to-end against real buggy code.

## Usage

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0   # full history needed to reach the base ref

- uses: jonrogers2015/pr-gatekeeper@v1
  with:
    base-ref: origin/main
    test-glob: 'test_*.py'
    test-command: 'python3 -m pytest'
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

Full example: `examples/.github/workflows/gatekeeper.yml`.

## Inputs

| Input | Default | Notes |
|---|---|---|
| `base-ref` | `origin/main` | Where protected test files are pulled from |
| `test-glob` | `test_*.py` | Matched by **filename**, not path — `foo/test_x.py` and `bar/test_x.py` both match `test_*.py` |
| `test-command` | `python3 -m pytest` | Test runner, without file arguments — file paths are appended automatically |
| `github-token` | *(required)* | Used only to post the evidence comment |

## Fails closed

If `test-glob` matches nothing on `base-ref`, the gate **blocks**, it does not silently pass. A check that can't verify anything is not a passing check — same discipline `attested` itself enforces (empty output, missing keys, and timeouts all resolve to failed, never to a false pass).

## What's proven vs. what isn't yet

**Proven, with real tests, in this repo's build process:**
- Base-branch test extraction via real `git` commands against a real repo with real branches (not mocked)
- Test-tampering correctly blocked (real exit code 1)
- An honest fix correctly passed (real exit code 0)
- The "nothing to check" case correctly fails closed (real exit code 1) rather than passing

**Not yet run end-to-end:** the PR-comment posting step (`post_comment.py`) follows the documented GitHub REST API contract but hasn't been exercised against a real PR/token yet — needs one real run on an actual repository before this is trusted in production.

## Current scope

Python + pytest only, single test command. Deliberately narrow for v1 — one language done properly. Language/runner expansion is driven by real demand, not built ahead of it.
