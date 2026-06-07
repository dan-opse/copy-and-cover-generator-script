#!/usr/bin/env python3
"""CuriousCaiman YouTube Shorts generator — copy + overlay image."""

import argparse
import re
import sys
from pathlib import Path

import subprocess
from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent
INSTRUCTIONS = BASE / "AI Instructions" / "youtube_shorts_instructions.md"
OUTPUT = BASE / "output"
LOGO = BASE / "Logo.png"
VERIFIED = BASE / "verified.png"
FONT_PATH = "/System/Library/Fonts/HelveticaNeue.ttc"

# ── Canvas ─────────────────────────────────────────────────────────────────────
CANVAS_W, CANVAS_H = 1080, 1920
BAR_H = CANVAS_H // 3          # 640 px black bar

# ── Colours ────────────────────────────────────────────────────────────────────
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
GRAY  = (84, 84, 84, 255)      # #545454 for @handle


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size, index=1 if bold else 0)


def _circular_crop(path: Path, size: int) -> Image.Image:
    img = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    img.putalpha(mask)
    return img


def _verified_badge(path: Path, size: int) -> Image.Image:
    """Load verified.png and make the white background transparent."""
    badge = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    pixels = badge.load()
    for y in range(badge.height):
        for x in range(badge.width):
            r, g, b, a = pixels[x, y]
            # White background pixels have all channels very high and low saturation.
            # The blue badge and white checkmark are distinguishable by position but
            # at render size we only need to remove the outer white margin.
            if r > 230 and g > 230 and b > 230:
                pixels[x, y] = (r, g, b, 0)
    return badge


def _wrap(text: str, draw: ImageDraw.ImageDraw, fnt, max_w: int, max_lines: int = 3) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        test = " ".join(current + [word])
        if draw.textlength(test, font=fnt) <= max_w:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            if len(lines) >= max_lines:
                current = []
                break
            current = [word]

    if current and len(lines) < max_lines:
        lines.append(" ".join(current))

    # If text was cut short, add ellipsis to the last line
    full_words = sum(len(l.split()) for l in lines)
    if full_words < len(words):
        last = lines[-1]
        while draw.textlength(last + "...", font=fnt) > max_w:
            last = last.rsplit(" ", 1)[0]
        lines[-1] = last + "..."

    return lines[:max_lines]


def generate_overlay(animal: str, emoji: str, fact: str, out_path: Path) -> None:
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Black bar (top 1/3)
    draw.rectangle([0, 0, CANVAS_W, BAR_H], fill=BLACK)

    SZ_NAME   = 38
    SZ_BODY   = 35
    f_name    = _font(SZ_NAME, bold=True)   # "CuriousCaiman"
    f_handle  = _font(SZ_BODY, bold=False)  # "@CuriousCaiman"
    f_title   = _font(SZ_BODY, bold=True)   # animal name + emoji
    f_fact    = _font(SZ_BODY, bold=False)  # fact lines

    ml        = 120                          # left/right margin
    pic_size  = 135
    line_h    = SZ_BODY + 10                # 45 px per fact line

    # ── Layout anchored from bottom of bar (work upward) ─────────────────────
    bottom_pad   = 40
    content_btm  = BAR_H - bottom_pad       # 600

    fact_y       = content_btm - SZ_BODY - 2 * line_h   # top of line 1
    title_y      = fact_y - 18 - SZ_BODY
    pic_top      = title_y - 26 - pic_size

    # ── Profile picture ────────────────────────────────────────────────────────
    logo = _circular_crop(LOGO, pic_size)
    img.paste(logo, (ml, pic_top), logo)

    # ── Channel name + verified badge (vertically centred in pic) ─────────────
    tx        = ml + pic_size + 20
    name_blk  = SZ_NAME + 10 + SZ_BODY
    ty_name   = pic_top + (pic_size - name_blk) // 2

    draw.text((tx, ty_name), "CuriousCaiman", font=f_name, fill=WHITE)
    name_w    = int(draw.textlength("CuriousCaiman ", font=f_name))

    badge_size = 38
    badge      = _verified_badge(VERIFIED, badge_size)
    img.paste(badge, (tx + name_w, ty_name + 10), badge)

    # ── @handle ────────────────────────────────────────────────────────────────
    ty_handle = ty_name + SZ_NAME + 10
    draw.text((tx, ty_handle), "@CuriousCaiman", font=f_handle, fill=GRAY)

    # ── Animal title + emoji ───────────────────────────────────────────────────
    # Emoji sits lower than text by default; shift up ~30% of font size.
    emoji_up = (0, -int(SZ_BODY * 0.30))
    with Pilmoji(img) as pj:
        pj.text((ml, title_y), f"{animal} {emoji}", font=f_title, fill=WHITE,
                emoji_position_offset=emoji_up)

    # ── Fact text (max 3 lines) ────────────────────────────────────────────────
    lines = _wrap(fact, draw, f_fact, CANVAS_W - 2 * ml)
    with Pilmoji(img) as pj:
        for i, line in enumerate(lines):
            pj.text((ml, fact_y + i * line_h), line, font=f_fact, fill=WHITE,
                    emoji_position_offset=emoji_up)

    OUTPUT.mkdir(exist_ok=True)
    img.save(out_path, "PNG")
    print(f"\nOverlay saved → {out_path}")


# ── Copy generation ────────────────────────────────────────────────────────────

def _parse_copy(raw: str) -> dict:
    patterns = {
        "title":       r"Title:\s*(.+)",
        "overlay":     r"Overlay Text:\s*(.+?)(?=\n\nDescription:|\Z)",
        "description": r"Description:\s*(.+?)(?=\n\nNo copyright|\Z)",
    }
    return {k: (m.group(1).strip() if (m := re.search(p, raw, re.DOTALL)) else "") for k, p in patterns.items()}


def _overlay_fits(text: str) -> bool:
    """Return True if text wraps into ≤3 lines at overlay font/width."""
    fnt   = _font(35, bold=False)
    max_w = CANVAS_W - 2 * 120
    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    words = text.split()
    lines, current = [], []
    for word in words:
        test = " ".join(current + [word])
        if draw.textlength(test, font=fnt) <= max_w:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            if len(lines) >= 3:
                return False
            current = [word]
    if current:
        lines.append(" ".join(current))
    return len(lines) <= 3


def _claude(prompt: str, system: str | None = None) -> str:
    cmd = ["claude", "-p", prompt, "--output-format", "text"]
    if system:
        cmd += ["--system-prompt", system]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI error: {result.stderr.strip()}")
    return result.stdout.strip()


def _shorten_overlay(text: str) -> str:
    return _claude(
        "Shorten this YouTube Shorts overlay text to fit in 3 lines of roughly "
        "38 characters each (≈114 chars total). Keep the most fascinating fact. "
        "Return only the shortened text, no quotes or explanation:\n\n" + text
    )


def generate_copy(video_description: str) -> tuple[dict, str]:
    system = INSTRUCTIONS.read_text()
    raw    = _claude(video_description, system=system)
    parsed = _parse_copy(raw)

    if parsed["overlay"] and not _overlay_fits(parsed["overlay"]):
        print("Overlay text too long — shortening…")
        parsed["overlay"] = _shorten_overlay(parsed["overlay"])

    return parsed, raw


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="CuriousCaiman Shorts Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate.py "sea otter floating on its back holding a pup"
  python generate.py "mantis shrimp punching a crab" --animal "Mantis Shrimp" --emoji 🦐
  python generate.py "axolotl regrowing its limb" --no-overlay
        """,
    )
    parser.add_argument("descriptions", nargs="*", help="One or more video descriptions (omit if using --fact)")
    parser.add_argument("--animal", help="Animal name for overlay — single-video mode only (prompted if omitted)")
    parser.add_argument("--emoji",  help="Apple emoji for overlay — single-video mode only (prompted if omitted)")
    parser.add_argument("--fact",   help="Overlay fact text — skips copy generation entirely (single video)")
    parser.add_argument("--no-overlay", action="store_true", help="Skip overlay PNG generation")
    args = parser.parse_args()

    OUTPUT.mkdir(exist_ok=True)
    batch = len(args.descriptions) > 1

    if args.fact:
        # Image-only mode: single video, no copy generation
        fact = args.fact
        if not args.no_overlay:
            animal = args.animal or input("\nAnimal name for overlay (e.g. Sea Otter): ").strip()
            emoji  = args.emoji  or input("Emoji (e.g. 🦦): ").strip()
            slug   = animal.lower().replace(" ", "_")
            generate_overlay(animal, emoji, fact, OUTPUT / f"{slug}_overlay.png")
        return

    if not args.descriptions:
        parser.error("at least one description is required unless --fact is provided")

    batch_lines: list[str] = []

    for idx, desc in enumerate(args.descriptions, 1):
        prefix = f" ({idx}/{len(args.descriptions)})" if batch else ""
        print(f"Generating copy{prefix}…")
        parsed, raw = generate_copy(desc)
        print("\n" + "═" * 60)
        print(raw)
        print("═" * 60)
        fact = parsed.get("overlay") or input("Overlay fact text: ").strip()

        if batch:
            batch_lines.append(
                f"=== Video {idx} ===\n"
                f"Title: {parsed['title']}\n\n"
                f"Description:\n{parsed['description']}\n"
            )
        else:
            # Determine slug after prompting for animal name below; save after overlay step
            pass

        if not args.no_overlay:
            animal = (args.animal if not batch else None) or input("\nAnimal name for overlay (e.g. Sea Otter): ").strip()
            emoji  = (args.emoji  if not batch else None) or input("Emoji (e.g. 🦦): ").strip()
            slug   = animal.lower().replace(" ", "_")
            generate_overlay(animal, emoji, fact, OUTPUT / f"{slug}_overlay.png")

            if not batch:
                copy_path = OUTPUT / f"{slug}_copy.txt"
                copy_path.write_text(
                    f"Title: {parsed['title']}\n\n"
                    f"Description:\n{parsed['description']}\n"
                )
                print(f"Copy saved    → {copy_path}")

    if batch:
        batch_path = OUTPUT / "batch.txt"
        batch_path.write_text("\n".join(batch_lines))
        print(f"\nBatch copy saved → {batch_path}")


if __name__ == "__main__":
    main()
