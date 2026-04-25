"""
Add sequential page numbers, top-centre, to every page of a PDF.
Usage: python pagenumber.py input.pdf [output.pdf]
Output defaults to input_paged.pdf in the same folder.
"""

import io
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas


def _number_overlay(page_num: int, width: float, height: float) -> bytes:
    """Single-page PDF containing just the page number centred at the top."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.setFont("Helvetica", 10)
    # 28 pt from top (~1 cm) sits in the margin without touching content
    c.drawCentredString(width / 2, height - 28, str(page_num))
    c.save()
    return buf.getvalue()


def add_page_numbers(input_path: str, output_path: str | None = None) -> Path:
    input_file = Path(input_path)
    if not input_file.exists():
        raise FileNotFoundError(input_file)

    if output_path is None:
        output_file = input_file.with_stem(input_file.stem + "_paged")
    else:
        output_file = Path(output_path)

    reader = PdfReader(str(input_file))
    writer = PdfWriter()

    print(f"Input:  {input_file} ({input_file.stat().st_size / 1_000_000:.1f} MB)")
    print(f"Output: {output_file}")
    print(f"Numbering {len(reader.pages)} pages...")

    for i, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        overlay_page = PdfReader(io.BytesIO(_number_overlay(i, width, height))).pages[0]
        page.merge_page(overlay_page)
        writer.add_page(page)

    with open(output_file, "wb") as f:
        writer.write(f)

    print(f"Done. Output: {output_file} ({output_file.stat().st_size / 1_000_000:.1f} MB)")
    return output_file


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pagenumber.py input.pdf [output.pdf]")
        sys.exit(1)
    add_page_numbers(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
