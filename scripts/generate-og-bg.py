#!/usr/bin/env python3
"""
Generate an AI-painted OG-image BACKGROUND via OpenAI Images API (DALL-E 3).

This script produces the BACKGROUND layer only — the text overlay (icon,
wordmark, tagline, right-column preview card) is added in a separate
compositing step by the refiner via SVG. Two-layer split keeps text
pixel-precise (image models misspell + can't pixel-match brand colors).

Usage:
    OPENAI_API_KEY=sk-... python3 scripts/generate-og-bg.py \\
        --project-path /home/sammy/mission-control \\
        --theme-color "#6366f1" \\
        --purpose "Internal team console for portfolio orchestration: project tiles, skill catalog, audit trail, terminal access" \\
        --category dashboard

Output:
    Writes 1792x1024 PNG to <project-path>/frontend/public/og-banner-bg.png
    (DALL-E 3's closest size to 1.91:1 — the SVG composite center-crops
    to 1200x630 via preserveAspectRatio="xMidYMid slice", no Pillow needed.)

Exit codes:
    0 — success, PNG written
    1 — bad args / missing API key / no internet
    2 — OpenAI API error (rate limit, invalid prompt, etc.)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

OPENAI_URL = "https://api.openai.com/v1/images/generations"
MODEL = os.environ.get("OG_AI_IMAGE_MODEL", "gpt-image-1")
# gpt-image-1 returns b64_json by default; dall-e-3 returns a URL.
# Landscape sizes vary by model — pick the closest-to-16:9 each supports.
SIZE = "1536x1024" if MODEL == "gpt-image-1" else "1792x1024"
QUALITY = "high" if MODEL == "gpt-image-1" else "hd"
REQUEST_TIMEOUT = 120  # seconds — image gen + download


# Prompt recipes per project category. Each emits a complete prompt; the
# refiner picks the category from its $findings.inferredPurpose or from the
# catalog tier table.
PROMPT_BY_CATEGORY: dict[str, str] = {
    "finance": (
        "An abstract minimal illustration of personal finance and multi-currency tracking. "
        "Soft floating receipts, coin discs, and currency symbol shapes in negative space. "
        "Smooth gradient background in {color}. No people, no text, no logos, no brand marks. "
        "Clean editorial vector style with subtle depth. Professional, calm, modern. "
        "Composition leaves the left half OPEN and DARKER for text overlay."
    ),
    "dashboard": (
        "An abstract minimal illustration of a control room or operations dashboard. "
        "Floating UI cards, soft progress arcs, light grid lines, gentle data flow lines. "
        "Smooth gradient background in {color}. No people, no text, no logos. "
        "Clean editorial vector style with subtle depth. Professional, modern, slightly futuristic. "
        "Composition leaves the left half OPEN and DARKER for text overlay."
    ),
    "ecommerce": (
        "An abstract minimal illustration of multi-store retail and online shopping. "
        "Floating storefront cards, shopping bag silhouettes, soft tag shapes. "
        "Smooth gradient background in {color}. No people, no text, no logos, no real brands. "
        "Clean editorial vector style with subtle depth. Professional, inviting, modern. "
        "Composition leaves the left half OPEN and DARKER for text overlay."
    ),
    "knowledge": (
        "An abstract minimal illustration of a knowledge base or AI content studio. "
        "Floating index cards in a soft stack, gentle connection lines, glowing nodes. "
        "Smooth gradient background in {color}. No people, no text, no logos. "
        "Clean editorial vector style with subtle depth. Thoughtful, calm, modern. "
        "Composition leaves the left half OPEN and DARKER for text overlay."
    ),
    "cms": (
        "An abstract minimal illustration of content management. "
        "Stacked document silhouettes, soft layout grids, gentle layering. "
        "Smooth gradient background in {color}. No people, no text, no logos. "
        "Clean editorial vector style with subtle depth. Professional, modern. "
        "Composition leaves the left half OPEN and DARKER for text overlay."
    ),
    "tasks": (
        "An abstract minimal illustration of task management. "
        "Floating checklist cards, soft progress indicators, gentle priority swatches. "
        "Smooth gradient background in {color}. No people, no text, no logos. "
        "Clean editorial vector style with subtle depth. Energetic, modern. "
        "Composition leaves the left half OPEN and DARKER for text overlay."
    ),
    "generic": (
        "An abstract minimal illustration evoking software craftsmanship and developer tooling. "
        "Floating geometric shapes, soft layered cards, gentle data flow lines, subtle dots. "
        "Smooth gradient background in {color}. No people, no text, no logos. "
        "Clean editorial vector style with subtle depth. Professional, modern, technical. "
        "Composition leaves the left half OPEN and DARKER for text overlay."
    ),
}


def red(s: str) -> str:   return f'\033[31m{s}\033[0m'
def green(s: str) -> str: return f'\033[32m{s}\033[0m'
def dim(s: str) -> str:   return f'\033[2m{s}\033[0m'
def bold(s: str) -> str:  return f'\033[1m{s}\033[0m'


def build_prompt(category: str, theme_color: str, purpose: str) -> str:
    template = PROMPT_BY_CATEGORY.get(category, PROMPT_BY_CATEGORY["generic"])
    prompt = template.format(color=theme_color)
    if purpose:
        prompt = (
            f"{prompt} "
            f"The illustration's visual metaphors should evoke: {purpose.strip()}. "
            f"But render only the abstract metaphors — NEVER write text in the image."
        )
    return prompt


def call_openai(api_key: str, prompt: str) -> dict[str, Any]:
    """Call OpenAI Images API. Returns the first item from data[] (has either
    a `url` field for dall-e-3 or `b64_json` for gpt-image-1)."""
    payload: dict[str, Any] = {
        "model": MODEL,
        "prompt": prompt,
        "size": SIZE,
        "n": 1,
    }
    # Quality + response_format are model-specific.
    if MODEL == "dall-e-3":
        payload["quality"] = QUALITY        # "hd" | "standard"
        payload["response_format"] = "url"  # legacy: returns a URL
    elif MODEL == "gpt-image-1":
        payload["quality"] = QUALITY        # "high" | "medium" | "low"
        # Don't pass response_format — gpt-image-1 returns b64_json always.

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            response = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(red(f"OpenAI API error {e.code}: {body[:600]}"), file=sys.stderr)
        sys.exit(2)
    except urllib.error.URLError as e:
        print(red(f"Network error: {e.reason}"), file=sys.stderr)
        sys.exit(2)

    data = response.get("data") or []
    if not data:
        print(red(f"Unexpected response shape: {response}"), file=sys.stderr)
        sys.exit(2)
    return data[0]


def save_image(item: dict[str, Any], dest: Path) -> int:
    """Persist the image to dest. Handles both URL (dall-e-3) and base64
    (gpt-image-1) response shapes. Returns bytes written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if item.get("url"):
        try:
            with urllib.request.urlopen(item["url"], timeout=REQUEST_TIMEOUT) as resp:
                data = resp.read()
        except urllib.error.URLError as e:
            print(red(f"Download failed: {e.reason}"), file=sys.stderr)
            sys.exit(2)
    elif item.get("b64_json"):
        import base64
        data = base64.b64decode(item["b64_json"])
    else:
        print(red(f"Response item has neither url nor b64_json: keys={list(item.keys())}"), file=sys.stderr)
        sys.exit(2)
    dest.write_bytes(data)
    return len(data)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an AI-painted OG-image BACKGROUND via DALL-E 3.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--project-path", type=Path, required=True,
                        help="Project root (must contain frontend/public/)")
    parser.add_argument("--theme-color", required=True,
                        help="Manifest theme_color (e.g. '#6366f1')")
    parser.add_argument("--category", default="generic",
                        choices=sorted(PROMPT_BY_CATEGORY.keys()),
                        help="Project category — picks a prompt template")
    parser.add_argument("--purpose", default="",
                        help="One-line project purpose from .project-meta.json $findings.inferredPurpose")
    parser.add_argument("--out-name", default="og-banner-bg.png",
                        help="Output filename inside frontend/public/")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the prompt that would be sent; don't call the API")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key and not args.dry_run:
        print(red("ERROR: OPENAI_API_KEY env var not set"), file=sys.stderr)
        return 1

    project_path = args.project_path.resolve()
    if not (project_path / "frontend" / "public").is_dir():
        print(red(f"ERROR: {project_path}/frontend/public/ does not exist"), file=sys.stderr)
        return 1

    out_path = project_path / "frontend" / "public" / args.out_name
    prompt = build_prompt(args.category, args.theme_color, args.purpose)

    print(bold(f"OpenAI Images / DALL-E 3 → {out_path.name}"))
    print(dim(f"  project:   {project_path}"))
    print(dim(f"  category:  {args.category}"))
    print(dim(f"  color:     {args.theme_color}"))
    print(dim(f"  size:      {SIZE}  quality: {QUALITY}"))
    print()
    print(bold("Prompt:"))
    print(dim(prompt))
    print()

    if args.dry_run:
        print(dim("(--dry-run — no API call)"))
        return 0

    print(dim(f"Calling OpenAI ({MODEL})…"))
    item = call_openai(api_key, prompt)
    mode = "URL download" if item.get("url") else "base64 decode"
    print(dim(f"Response: {mode}"))
    n = save_image(item, out_path)
    print(green(f"WROTE  {out_path}  ({n:,} bytes)"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(red("\nInterrupted."), file=sys.stderr)
        sys.exit(130)
