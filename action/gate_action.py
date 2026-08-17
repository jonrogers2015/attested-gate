#!/usr/bin/env python3
"""
Attested Gate -- GitHub Action entrypoint.

Core rule, same as the demo: never trust a PR's own test files. Pulls test
files as they exist on the BASE branch, runs the PR's code against those,
in an isolated copy -- the executor never runs inside the branch being
verified. See attested's own stated design rule: "the executor must not
run inside the thing being verified."

Reads config from environment (set by action.yml):
  BASE_REF       -- e.g. "origin/main"
  TEST_GLOB      -- glob matched against the FULL RELATIVE PATH (not just
                    filename), e.g. "test_*.py" matches any top-level file
                    with that name, "demo/base/test_*.py" matches only
                    within that directory, "**/test_*.py" matches at any
                    depth. Use a path-scoped glob whenever a repo could
                    have multiple files sharing a basename in different
                    directories -- pytest cannot collect two same-named
                    test modules from different packages without proper
                    __init__.py packaging, so an unscoped glob that
                    matches more than one such file will make every run
                    fail to even collect, not just fail to pass. This bit
                    this repo's own self-test (both directions showed
                    BLOCKED on 2026-08-09, from a collection error, not
                    real detection) before being caught and fixed here --
                    v1 matched by basename only, which silently picked up
                    demo/base/, demo/tampered_pr/, and demo/honest_pr/'s
                    three separate test_pricing.py files at once.
  TEST_COMMAND   -- e.g. "python3 -m pytest"
  WORKSPACE      -- checked-out PR working directory (defaults to cwd)

Exit 0 = gate passed. Exit 1 = gate blocked, or a real error occurred.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from attested import verify, command_exit_code


def sh(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def find_base_test_files(workspace: Path, base_ref: str, test_glob: str) -> list[str]:
    """List every file that exists on base_ref and matches test_glob,
    matched against the file's full relative path from repo root."""
    result = sh(["git", "ls-tree", "-r", "--name-only", base_ref], cwd=str(workspace))
    if result.returncode != 0:
        print(f"[gate] ERROR: could not list files on {base_ref!r}: {result.stderr.strip()}")
        return []
    all_files = result.stdout.splitlines()
    return [f for f in all_files if fnmatch.fnmatch(f, test_glob)]


def extract_file_at_ref(workspace: Path, ref: str, path: str, dest: Path) -> bool:
    """Write the content of `path` as it exists at `ref` into `dest`."""
    result = sh(["git", "show", f"{ref}:{path}"], cwd=str(workspace))
    if result.returncode != 0:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result.stdout)
    return True


def build_isolated_check_dir(workspace: Path, base_ref: str, test_files: list[str]) -> Path:
    """
    Copy the PR's current working tree into an isolated temp dir, then
    OVERWRITE every test file with its base-branch version. Whatever the
    PR did to those specific files is discarded for the purpose of this
    check -- only the base branch's version of the test is ever run.
    """
    tmp = Path(tempfile.mkdtemp(prefix="gatekeeper_"))

    result = sh(["git", "ls-files"], cwd=str(workspace))
    tracked_files = result.stdout.splitlines()
    for f in tracked_files:
        src = workspace / f
        if not src.is_file():
            continue
        dst = tmp / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)

    replaced, failed = 0, []
    for test_file in test_files:
        ok = extract_file_at_ref(workspace, base_ref, test_file, tmp / test_file)
        if ok:
            replaced += 1
        else:
            failed.append(test_file)

    print(f"[gate] isolated check dir: {tmp}")
    print(f"[gate] {replaced} base-branch test file(s) placed, {len(failed)} failed to extract")
    if failed:
        print(f"[gate] WARNING: could not extract from base: {failed}")

    return tmp


def main() -> int:
    workspace = Path(os.environ.get("WORKSPACE", ".")).resolve()
    base_ref = os.environ.get("BASE_REF", "origin/main")
    test_glob = os.environ.get("TEST_GLOB", "test_*.py")
    test_command = os.environ.get("TEST_COMMAND", "python3 -m pytest")

    print(f"[gate] workspace: {workspace}")
    print(f"[gate] base ref: {base_ref}")
    print(f"[gate] test glob: {test_glob}")

    test_files = find_base_test_files(workspace, base_ref, test_glob)
    if not test_files:
        print(f"[gate] ERROR: no files matching {test_glob!r} found on {base_ref} -- refusing to pass with nothing checked")
        return 1
    print(f"[gate] {len(test_files)} base-branch test file(s) to protect: {test_files}")

    check_dir = build_isolated_check_dir(workspace, base_ref, test_files)

    spec = command_exit_code(f"cd {check_dir} && {test_command} {' '.join(test_files)}")
    result = verify(spec)

    print()
    print("[gate] --- raw probe output ---")
    print(result.output)
    print("[gate] --- end raw probe output ---")
    print()

    if result.passed:
        print(f"[gate] PASSED: {result.detail}")
    else:
        print(f"[gate] BLOCKED: {result.detail}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
