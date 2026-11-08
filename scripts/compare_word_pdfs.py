"""Render and compare native Word PDF exports without changing either PDF.

Run with the Codex bundled Python.  Omit --export to prepare the source pages
while the revised Word PDF is pending.  Every page is rendered at scale 1.5 by
default; pixel comparisons never resize or align the rendered page images.
Differences are evidence for human review, not an automatic acceptance verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageDraw, ImageStat


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized_text(text: str) -> str:
    return " ".join(text.split())


def number_candidates(text: str) -> list[str]:
    """Keep standalone footer numbers as candidates, including Roman numerals."""
    candidates = []
    for line in text.splitlines():
        match = re.fullmatch(
            r"\s*(?:[-\u2013\u2014]\s*)?(?:第\s*)?"
            r"([0-9]+|[IVXLCDMivxlcdm]+)"
            r"(?:\s*页)?(?:\s*[-\u2013\u2014])?\s*", line
        )
        if match:
            candidates.append(match.group(1))
    return candidates


def footer_bounds(page, bitmap, height_pt: float) -> tuple[float, ...]:
    """Find the displayed bottom strip, including rotated/cropped PDF pages."""
    converter = bitmap.get_posconv(page)
    width, height = bitmap.width, bitmap.height
    strip_px = min(height, round(height_pt * height / page.get_height()))
    points = [converter.to_page(x, y)
              for x in (0, width) for y in (height - strip_px, height)]
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


def contact_sheets(pages: list[dict], output: Path) -> list[str]:
    """Make a four-by-two contact sheet for each consecutive eight pages."""
    paths = []
    tile_w, tile_h, gap, label_h = 300, 430, 16, 28
    for first in range(0, len(pages), 8):
        chunk = pages[first:first + 8]
        sheet = Image.new("RGB", (4 * (tile_w + gap) + gap,
                                  2 * (tile_h + label_h + gap) + gap), "#dddddd")
        draw = ImageDraw.Draw(sheet)
        for index, record in enumerate(chunk):
            x = gap + (index % 4) * (tile_w + gap)
            y = gap + (index // 4) * (tile_h + label_h + gap)
            draw.text((x, y + 4), f"Page {record['page']}", fill="black")
            with Image.open(record["png"]) as original:
                thumbnail = original.convert("RGB")
                thumbnail.thumbnail((tile_w, tile_h), Image.Resampling.LANCZOS)
                sheet.paste(thumbnail, (x + (tile_w - thumbnail.width) // 2,
                                         y + label_h))
        destination = output / f"contact-{first + 1:03d}-{first + len(chunk):03d}.png"
        sheet.save(destination)
        paths.append(str(destination.resolve()))
    return paths


def render_pdf(source: Path, output: Path, scale: float = 1.5,
               footer_height_pt: float = 70.0) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(str(source))
    pages = []
    try:
        for index in range(len(document)):
            page = document[index]
            textpage = bitmap = None
            try:
                bitmap = page.render(scale=scale)
                # Copy out of PDFium-owned storage before closing its bitmap.
                image = bitmap.to_pil().convert("RGB").copy()
                path = output / f"page-{index + 1:03d}.png"
                image.save(path)
                textpage = page.get_textpage()
                text = textpage.get_text_bounded()
                bounds = footer_bounds(page, bitmap, footer_height_pt)
                footer = textpage.get_text_bounded(
                    left=bounds[0], bottom=bounds[1], right=bounds[2], top=bounds[3])
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                pages.append({
                    "page": index + 1,
                    "size_pt": list(page.get_size()),
                    "bbox_pdf_coordinates": list(page.get_bbox()),
                    "rotation_degrees": page.get_rotation(),
                    "rendered_size_px": list(image.size),
                    "pixel_sha256_rgb": sha256(image.tobytes()),
                    "png": str(path.resolve()),
                    "text": text,
                    "text_sha256_utf8": sha256(text.encode("utf-8")),
                    "first_lines": lines[:3],
                    "last_lines": lines[-3:],
                    "footer": {
                        "height_pt": footer_height_pt,
                        "bounds_pdf_coordinates": list(bounds),
                        "text": footer,
                        "page_number_candidates": number_candidates(footer),
                    },
                })
            finally:
                if textpage is not None:
                    textpage.close()
                if bitmap is not None:
                    bitmap.close()
                page.close()
    finally:
        document.close()
    return {
        "pdf": str(source.resolve()),
        "sha256": sha256(source.read_bytes()),
        "page_count": len(pages),
        "pages": pages,
        "contact_sheets": contact_sheets(pages, output),
    }


def compare_page_images(before: dict, after: dict, output: Path,
                        scale: float) -> dict:
    with Image.open(before["png"]) as image_before, Image.open(after["png"]) as image_after:
        left = image_before.convert("RGB")
        right = image_after.convert("RGB")
    equal_canvas = left.size == right.size
    width, height = max(left.width, right.width), max(left.height, right.height)
    if not equal_canvas:
        # Record dimensions separately; padding only makes the differing area
        # inspectable. It must never make unequal-sized pages "identical".
        padded_left = Image.new("RGB", (width, height), "white")
        padded_right = Image.new("RGB", (width, height), "white")
        padded_left.paste(left, (0, 0))
        padded_right.paste(right, (0, 0))
        left, right = padded_left, padded_right
    difference = ImageChops.difference(left, right)
    channels = difference.split()
    magnitude = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    bbox = magnitude.getbbox()
    changed_pixels = sum(magnitude.histogram()[1:])
    difference_png = None
    if bbox is not None:
        mask = magnitude.point(lambda value: 255 if value else 0)
        visualization = Image.new("RGB", (width, height), "white")
        visualization.paste("#db2020", (0, 0, width, height), mask)
        destination = output / f"page-{before['page']:03d}-difference.png"
        visualization.save(destination)
        difference_png = str(destination.resolve())
    return {
        "rendered_dimensions_equal": equal_canvas,
        "pixels_identical": equal_canvas and bbox is None,
        "comparison_canvas_px": [width, height],
        "alignment": "top-left; no resizing; white padding only when dimensions differ",
        "changed_pixel_count": changed_pixels,
        "changed_pixel_fraction": changed_pixels / (width * height),
        "difference_bbox_px": list(bbox) if bbox else None,
        "difference_bbox_pt_top_left": [value / scale for value in bbox] if bbox else None,
        "bbox_right_bottom_exclusive": True,
        "max_channel_difference_0_255": max(hi for lo, hi in difference.getextrema()),
        "mean_absolute_channel_difference_0_255": sum(ImageStat.Stat(difference).mean) / 3,
        "difference_png": difference_png,
    }


def compare_documents(source: dict, exported: dict, output: Path,
                      scale: float) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    comparisons = []
    for index in range(max(source["page_count"], exported["page_count"])):
        before = source["pages"][index] if index < source["page_count"] else None
        after = exported["pages"][index] if index < exported["page_count"] else None
        if before is None or after is None:
            comparisons.append({"page": index + 1,
                                "status": "added_page" if before is None else "missing_page",
                                "source_page": before, "export_page": after})
            continue
        pixels = compare_page_images(before, after, output, scale)
        comparisons.append({
            "page": index + 1,
            "status": "identical_rendering" if pixels["pixels_identical"] else "changed_rendering",
            "size_pt_equal": before["size_pt"] == after["size_pt"],
            "rotation_equal": before["rotation_degrees"] == after["rotation_degrees"],
            "text_identical": before["text"] == after["text"],
            "text_whitespace_normalized_identical": normalized_text(before["text"]) == normalized_text(after["text"]),
            "footer_text_identical": before["footer"]["text"] == after["footer"]["text"],
            "footer_page_number_candidates_equal": before["footer"]["page_number_candidates"] == after["footer"]["page_number_candidates"],
            "source_footer": before["footer"],
            "export_footer": after["footer"],
            "source_first_lines": before["first_lines"],
            "export_first_lines": after["first_lines"],
            "source_last_lines": before["last_lines"],
            "export_last_lines": after["last_lines"],
            **pixels,
        })
    matched = [item for item in comparisons if "pixels_identical" in item]
    return {
        "page_count_equal": source["page_count"] == exported["page_count"],
        "matched_page_count": len(matched),
        "pixel_identical_pages": [item["page"] for item in matched if item["pixels_identical"]],
        "pixel_changed_pages": [item["page"] for item in matched if not item["pixels_identical"]],
        "page_size_changed_pages": [item["page"] for item in matched if not item["size_pt_equal"]],
        "text_changed_pages": [item["page"] for item in matched if not item["text_identical"]],
        "footer_text_changed_pages": [item["page"] for item in matched if not item["footer_text_identical"]],
        "footer_page_number_candidates_changed_pages": [item["page"] for item in matched if not item["footer_page_number_candidates_equal"]],
        "added_pages": [item["page"] for item in comparisons if item["status"] == "added_page"],
        "missing_pages": [item["page"] for item in comparisons if item["status"] == "missing_page"],
        "pages": comparisons,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--export", dest="exported", type=Path,
                        help="Omit to render and inventory only the source PDF.")
    parser.add_argument("--outdir", "--output", required=True, type=Path)
    parser.add_argument("--scale", type=float, default=1.5)
    args = parser.parse_args()
    if args.scale <= 0:
        parser.error("--scale must be greater than zero")
    for path in [args.source] + ([args.exported] if args.exported else []):
        if not path.is_file():
            parser.error(f"PDF not found: {path}")
    args.outdir.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": 1,
        "mode": "comparison" if args.exported else "source_preparation",
        "renderer": "pypdfium2 / PDFium",
        "scale": args.scale,
        "footer_height_pt": 70,
        "assessment": "Evidence only. Human review must distinguish intended edits from layout regressions.",
        "limitations": [
            "Pages are compared by page number, without reflow alignment.",
            "Pixel equality is exact at the recorded rendering scale, not proof of PDF byte equality.",
            "Text extraction may omit outlined or image-only text. Footer numbers are candidates, not authoritative labels.",
            "Difference boxes use top-left rendered-page coordinates; right and bottom bounds are exclusive.",
        ],
        "source": render_pdf(args.source, args.outdir / "source", args.scale),
    }
    if args.exported:
        result["export"] = render_pdf(args.exported, args.outdir / "export", args.scale)
        result["comparison"] = compare_documents(result["source"], result["export"],
                                                 args.outdir / "differences", args.scale)
    destination = args.outdir / "audit.json"
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {"audit": str(destination.resolve()), "source_pages": result["source"]["page_count"]}
    if "comparison" in result:
        summary.update({k: v for k, v in result["comparison"].items() if k != "pages"})
    else:
        summary["status"] = "Source rendered; awaiting exported PDF."
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
