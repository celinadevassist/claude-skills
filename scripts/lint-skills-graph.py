#!/usr/bin/env python3
"""
Lint the skills-graph.yml against the actual skills on disk.

Fails (exit 1) if any of these are true:
  - A SKILL.md directory exists but has no entry in skills-graph.yml.
  - An entry in skills-graph.yml has no corresponding SKILL.md.
  - A `depends_on` edge points at a slug that's not in the graph.
  - The graph has a cycle (not a DAG).
  - A `level` is set for a skill of `type: audit` (audits must be levelless).
  - A `category` is used that's not declared in the top-level `categories:` block.
  - `level` is inconsistent with `max(level of deps) + 1` (warning only).

Usage:
    python3 scripts/lint-skills-graph.py

Pre-commit:
    Add to .git/hooks/pre-commit or run via the GHA workflow at
    .github/workflows/lint-skills-graph.yml.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Set

try:
    import yaml
except ImportError:
    print('ERROR: PyYAML not installed. Run: pip install pyyaml', file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
GRAPH_FILE = REPO_ROOT / 'skills-graph.yml'

# Directories that look like skill folders but aren't.
NOT_A_SKILL = {'.git', '.github', 'scripts', 'node_modules'}


def red(s: str) -> str:    return f'\033[31m{s}\033[0m'
def green(s: str) -> str:  return f'\033[32m{s}\033[0m'
def yellow(s: str) -> str: return f'\033[33m{s}\033[0m'
def bold(s: str) -> str:   return f'\033[1m{s}\033[0m'


def find_skill_directories() -> Set[str]:
    """Every <slug>/ in the repo root that contains a SKILL.md."""
    found: Set[str] = set()
    for entry in REPO_ROOT.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith('.') and entry.name not in {}:
            continue
        if entry.name in NOT_A_SKILL:
            continue
        if (entry / 'SKILL.md').is_file():
            found.add(entry.name)
    return found


def load_graph() -> dict:
    if not GRAPH_FILE.is_file():
        print(red(f'FATAL: graph file missing: {GRAPH_FILE}'), file=sys.stderr)
        sys.exit(1)
    with GRAPH_FILE.open() as f:
        return yaml.safe_load(f)


def has_cycle(skills: Dict[str, dict]) -> List[str] | None:
    """Returns the cycle as a list of slugs, or None if the graph is a DAG."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {k: WHITE for k in skills}
    parent: Dict[str, str | None] = {k: None for k in skills}

    def dfs(node: str) -> List[str] | None:
        color[node] = GRAY
        for dep in skills[node].get('depends_on') or []:
            if dep not in color:
                continue  # missing dep — reported separately
            if color[dep] == GRAY:
                cycle = [dep]
                cur = node
                while cur is not None and cur != dep:
                    cycle.append(cur)
                    cur = parent[cur]
                cycle.reverse()
                return cycle + [dep]
            if color[dep] == WHITE:
                parent[dep] = node
                found = dfs(dep)
                if found:
                    return found
        color[node] = BLACK
        return None

    for slug in skills:
        if color[slug] == WHITE:
            found = dfs(slug)
            if found:
                return found
    return None


def main() -> int:
    errors: List[str] = []
    warnings: List[str] = []

    on_disk = find_skill_directories()
    graph = load_graph()
    if not isinstance(graph, dict):
        print(red('FATAL: skills-graph.yml is empty or malformed.'), file=sys.stderr)
        return 1

    declared = graph.get('skills') or {}
    if not isinstance(declared, dict):
        print(red('FATAL: skills-graph.yml `skills` key must be a mapping.'), file=sys.stderr)
        return 1

    declared_slugs = set(declared.keys())
    declared_categories = set((graph.get('categories') or {}).keys())

    # --- 1. Slug parity: on-disk vs graph ---
    missing_in_graph = on_disk - declared_slugs
    missing_on_disk = declared_slugs - on_disk
    for slug in sorted(missing_in_graph):
        errors.append(
            f'Skill `{slug}/` exists on disk but has no entry in skills-graph.yml. '
            f'Add an entry under `skills:` — run the `skill-graph-position-inferrer` skill '
            f'for a proposed YAML block.'
        )
    for slug in sorted(missing_on_disk):
        errors.append(
            f'Graph entry `{slug}` has no SKILL.md on disk. '
            f'Either remove the entry from skills-graph.yml or restore the file at '
            f'`{slug}/SKILL.md`.'
        )

    # --- 2. Per-skill validation ---
    for slug, meta in declared.items():
        if not isinstance(meta, dict):
            errors.append(f'`{slug}`: entry must be a mapping, got {type(meta).__name__}.')
            continue

        skill_type = meta.get('type', 'setup')
        level = meta.get('level')
        category = meta.get('category')
        deps = meta.get('depends_on') or []
        desc = meta.get('description_short', '')

        # type validity
        if skill_type not in {'setup', 'audit', 'generative'}:
            errors.append(f'`{slug}`: invalid type `{skill_type}` (must be setup | audit | generative).')

        # category present + declared
        if not category:
            errors.append(f'`{slug}`: missing `category`.')
        elif category not in declared_categories:
            errors.append(
                f'`{slug}`: category `{category}` is not declared in the top-level '
                f'`categories:` block. Add it there, or pick from: '
                f'{sorted(declared_categories)}'
            )

        # level rules
        if skill_type == 'audit':
            if level is not None:
                errors.append(
                    f'`{slug}`: type=audit must have level: null (got {level!r}). '
                    f'Audits can run anytime and don\'t belong on a level rung.'
                )
        else:
            if level is None:
                errors.append(f'`{slug}`: setup skill must have a non-null level.')
            elif not isinstance(level, int) or level < 0:
                errors.append(f'`{slug}`: level must be a non-negative integer (got {level!r}).')

        # deps point at real skills
        for dep in deps:
            if dep not in declared_slugs:
                errors.append(
                    f'`{slug}`: depends_on references `{dep}` which is not a known skill.'
                )

        # description_short
        if not desc:
            warnings.append(f'`{slug}`: missing `description_short` — graph view will be sparse.')
        elif len(desc) > 130:
            warnings.append(
                f'`{slug}`: description_short is {len(desc)} chars (target: <100, hard max: 130).'
            )

        # level coherence (warning only)
        if skill_type != 'audit' and isinstance(level, int) and deps:
            dep_levels = [
                declared[d].get('level')
                for d in deps
                if d in declared and isinstance(declared[d].get('level'), int)
            ]
            if dep_levels:
                min_level = max(dep_levels) + 1
                if level < min_level:
                    errors.append(
                        f'`{slug}`: level={level} but depends on skills at level '
                        f'{max(dep_levels)} — should be at least L{min_level}.'
                    )
                elif level > min_level + 1:
                    warnings.append(
                        f'`{slug}`: level={level} but lowest-possible is L{min_level}. '
                        f'Floating up is OK for grouping but worth double-checking.'
                    )

    # --- 3. Cycle check ---
    cycle = has_cycle(declared)
    if cycle:
        errors.append(
            f'Cycle detected in depends_on graph: {" → ".join(cycle)}. '
            f'Skills must form a DAG.'
        )

    # --- Report ---
    print(bold(f'skills-graph.yml lint — {GRAPH_FILE.relative_to(REPO_ROOT)}'))
    print(f'  on disk: {len(on_disk)} skill directories')
    print(f'  declared: {len(declared_slugs)} graph entries')
    print(f'  errors:   {len(errors)}')
    print(f'  warnings: {len(warnings)}')
    print()

    for w in warnings:
        print(yellow(f'WARN  {w}'))
    for e in errors:
        print(red(f'ERROR {e}'))

    if errors:
        print()
        print(red(bold(f'❌ Lint failed with {len(errors)} error(s).')))
        return 1

    if warnings:
        print()
        print(yellow(bold(f'✓ No errors. {len(warnings)} warning(s) above worth a look.')))
    else:
        print(green(bold('✓ All checks passed.')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
