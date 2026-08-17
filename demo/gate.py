#!/usr/bin/env python3
"""
Attested Gate -- Layer 1 deterministic gate, minimal proof of concept.

The core principle this demonstrates: never trust a PR's own test files.
An agent (or a human under pressure) can make tests pass by weakening the
assertion instead of fixing the bug. The gate must run the code under
review against test files pulled from the BASE BRANCH -- the executor
must not run inside the thing being verified (attested's own stated rule).

Usage: python3 gate.py <pr_dir> <base_test_file>
"""
import shutil
import sys
import tempfile
from pathlib import Path

from attested import verify, command_exit_code


def run_gate(pr_dir: str, base_test_file: str) -> bool:
    pr_dir = Path(pr_dir)
    base_test_file = Path(base_test_file)

    # Build an isolated check directory: the PR's code, plus the ORIGINAL
    # (untampered) test file from the base branch -- never the PR's own
    # version of the test, no matter what it contains.
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for py_file in pr_dir.glob("*.py"):
            if py_file.name != base_test_file.name:
                shutil.copy(py_file, tmp / py_file.name)
        shutil.copy(base_test_file, tmp / base_test_file.name)

        print(f"[gate] PR code from: {pr_dir}")
        print(f"[gate] Test file from BASE BRANCH (not the PR): {base_test_file}")
        print(f"[gate] Isolated check dir: {tmp}")
        print()

        spec = command_exit_code(f"cd {tmp} && python3 -m pytest {base_test_file.name} -v")
        result = verify(spec)

        print("[gate] --- raw probe output ---")
        print(result.output)
        print("[gate] --- end raw probe output ---")
        print()

        if result.passed:
            print(f"[gate] PASSED: {result.detail}")
        else:
            print(f"[gate] BLOCKED: {result.detail}")

        return bool(result.passed)


if __name__ == "__main__":
    ok = run_gate(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
