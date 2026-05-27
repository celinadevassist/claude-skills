#!/usr/bin/env python3
"""
Skill Verification Runner — executes nextActions[] from a project's
.project-skills.json side-car and stamps verified/verifiedAt/verificationOutput
on each alreadyApplied entry.

The runtime half of advisor v2: the advisor populates `nextActions[]`, this
runner executes them and stamps the result. Without this script, every
project's `skillVerification` dimension in `.project-readiness.json` stays
at 0/15.

Usage:
    python3 scripts/run-skill-verification.py /path/to/project
    python3 scripts/run-skill-verification.py /path/to/project --dry-run
    python3 scripts/run-skill-verification.py /path/to/project --only pwa-setup
    python3 scripts/run-skill-verification.py /path/to/project --timeout 60
    python3 scripts/run-skill-verification.py /path/to/project --no-write

Behavior:
  - For each `alreadyApplied[]` entry with `nextActions[]`:
      * Auto actions: run via `bash -c`, cwd = project root
      * Manual: actions (prefix "Manual:") are counted, never executed
      * Exit code 0 → pass; non-zero or timeout → fail
  - Stamps on the entry:
      verified           true | false | null
      verifiedAt         ISO-8601 UTC timestamp
      verificationOutput one-line human-readable summary
  - Preserves every other field verbatim. Writes the side-car back with
    2-space indent + trailing newline.

Exit codes:
  0 — runner completed (irrespective of individual skill results)
  1 — side-car missing / invalid JSON / no matching --only skill
  2 — unexpected runtime error
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANUAL_PREFIX = "Manual:"


def red(s: str) -> str:    return f'\033[31m{s}\033[0m'
def green(s: str) -> str:  return f'\033[32m{s}\033[0m'
def yellow(s: str) -> str: return f'\033[33m{s}\033[0m'
def dim(s: str) -> str:    return f'\033[2m{s}\033[0m'
def bold(s: str) -> str:   return f'\033[1m{s}\033[0m'


def now_iso() -> str:
    """ISO-8601 UTC with milliseconds, matches the rest of the side-car format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def strip_inline_comment(cmd: str) -> str:
    """nextActions often carry `# expect: ...` annotations — strip before exec.

    Conservative: only strip if `#` is preceded by whitespace and not inside
    obvious quoting. Heuristic, but the alternative (full shell parsing) is
    overkill for v1. If users hit a false strip, they can quote the `#`.
    """
    # find the first occurrence of " #" that isn't inside double quotes
    in_dq = False
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if ch == '"' and (i == 0 or cmd[i - 1] != "\\"):
            in_dq = not in_dq
        elif ch == "#" and not in_dq and i > 0 and cmd[i - 1] == " ":
            return cmd[: i - 1].rstrip()
        i += 1
    return cmd


def run_command(cmd: str, cwd: Path, timeout: int) -> tuple[bool, str]:
    """Run shell command; return (passed, error-summary-if-failed)."""
    stripped = strip_inline_comment(cmd)
    try:
        result = subprocess.run(
            stripped,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, ""
        err = (result.stderr or result.stdout or "").strip()
        if len(err) > 120:
            err = "..." + err[-120:]
        if not err:
            err = "no output"
        return False, f"exit {result.returncode}: {err}"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except Exception as exc:  # pragma: no cover — defensive
        return False, f"runtime error: {exc.__class__.__name__}: {exc}"


def verify_skill(
    entry: dict[str, Any], project_root: Path, timeout: int, dry_run: bool
) -> dict[str, Any]:
    """Run nextActions[] for one applied skill, return entry with verification fields stamped."""
    actions = entry.get("nextActions", []) or []
    if not actions:
        return entry  # no actions to run — leave verified untouched

    auto_actions = [a for a in actions if not a.strip().startswith(MANUAL_PREFIX)]
    manual_count = len(actions) - len(auto_actions)

    if not auto_actions:
        entry["verified"] = None
        entry["verifiedAt"] = now_iso()
        entry["verificationOutput"] = (
            f"unknown — {manual_count} manual action(s) only, no auto-checks"
        )
        return entry

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    for action in auto_actions:
        if dry_run:
            print(f"    {dim('[dry-run]')} would run: {action}")
            passed.append(action)
            continue
        ok, err = run_command(action, project_root, timeout)
        if ok:
            print(f"    {green('PASS')} {action}")
            passed.append(action)
        else:
            print(f"    {red('FAIL')} {action}")
            print(f"         {dim(err)}")
            failed.append((action, err))

    if not failed:
        summary = f"all {len(passed)} auto-check(s) passed"
        if manual_count:
            summary += f"; {manual_count} manual action(s) not run"
        entry["verified"] = True
    else:
        summary = (
            f"{len(failed)} of {len(auto_actions)} failed: {failed[0][1]}"
        )
        entry["verified"] = False

    entry["verifiedAt"] = now_iso()
    entry["verificationOutput"] = summary
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute nextActions[] from .project-skills.json and stamp verification fields",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "project_path", type=Path, help="Project root containing .project-skills.json"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show commands without executing them"
    )
    parser.add_argument(
        "--only", metavar="SLUG", help="Run gate for one skill only (by slug)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-command timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not write the side-car back (combine with normal run to preview stamping)",
    )
    args = parser.parse_args()

    project_root = args.project_path.resolve()
    sidecar = project_root / ".project-skills.json"

    if not sidecar.is_file():
        print(red(f"ERROR: {sidecar} not found"), file=sys.stderr)
        return 1

    try:
        data = json.loads(sidecar.read_text())
    except json.JSONDecodeError as exc:
        print(red(f"ERROR: {sidecar} is not valid JSON: {exc}"), file=sys.stderr)
        return 1

    applied = data.get("alreadyApplied", [])
    if not applied:
        print(yellow(f"NOTE: no alreadyApplied[] entries in {sidecar} — nothing to verify"))
        return 0

    if args.only:
        match = [e for e in applied if e.get("skill") == args.only]
        if not match:
            print(
                red(f"ERROR: skill '{args.only}' not found in alreadyApplied[]"),
                file=sys.stderr,
            )
            return 1

    print(bold(f"Skill Verification Runner — {project_root.name}"))
    print(dim(f"  side-car:  {sidecar}"))
    print(dim(f"  cwd:       {project_root}"))
    print(dim(f"  timeout:   {args.timeout}s per command"))
    if args.only:
        print(dim(f"  only:      {args.only}"))
    if args.dry_run:
        print(dim("  dry-run:   ON"))
    print()

    updated: list[dict[str, Any]] = []
    for entry in applied:
        skill = entry.get("skill", "<unknown>")
        if args.only and skill != args.only:
            updated.append(entry)
            continue
        actions = entry.get("nextActions", []) or []
        if not actions:
            print(f"  {dim('—')} {skill}: no nextActions (skipped)")
            updated.append(entry)
            continue
        print(f"  {bold(skill)}:")
        updated.append(verify_skill(dict(entry), project_root, args.timeout, args.dry_run))
        print()

    data["alreadyApplied"] = updated

    verified_true = sum(1 for e in updated if e.get("verified") is True)
    verified_false = sum(1 for e in updated if e.get("verified") is False)
    # `verified: null` (key present, value None) — set when actions exist but are all Manual:
    verified_unknown = sum(1 for e in updated if "verified" in e and e["verified"] is None)
    # `verified` absent entirely — either no nextActions, or --only skipped this entry
    no_field = sum(1 for e in updated if "verified" not in e)

    print(bold("Summary"))
    print(f"  {green('PASS')}  verified=true:   {verified_true}")
    print(f"  {red('FAIL')}  verified=false:  {verified_false}")
    print(f"  {yellow('MAN ')}  verified=null:   {verified_unknown}   (manual-only / nothing to auto-run)")
    print(f"  {dim('SKIP')}  no field:        {no_field}   (no nextActions OR --only skipped this entry)")

    if args.dry_run or args.no_write:
        if args.dry_run:
            print(dim("\n(dry-run — side-car not modified)"))
        elif args.no_write:
            print(dim("\n(--no-write — side-car not modified)"))
        return 0

    sidecar.write_text(json.dumps(data, indent=2) + "\n")
    print(f"\n{dim('Wrote')} {sidecar}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(red("\nInterrupted."), file=sys.stderr)
        sys.exit(130)
