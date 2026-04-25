"""
OCR a PDF, skipping pages that already have a text layer.
Usage: python ocr.py input.pdf [output.pdf]
Output defaults to input_OCR.pdf in the same folder.
"""

import sys
import subprocess
from pathlib import Path


def ocr_pdf(input_path: str, output_path: str | None = None) -> Path:
    input_file = Path(input_path)
    if not input_file.exists():
        raise FileNotFoundError(input_file)

    if output_path is None:
        output_file = input_file.with_stem(input_file.stem + "_OCR")
    else:
        output_file = Path(output_path)

    cmd = [
        sys.executable, "-m", "ocrmypdf",
        "--skip-text",        # skip pages that already have text
        "--optimize", "1",    # light compression, no quality loss
        "--output-type", "pdf",
        str(input_file),
        str(output_file),
    ]

    print(f"Input:  {input_file} ({input_file.stat().st_size / 1_000_000:.1f} MB)")
    print(f"Output: {output_file}")
    print("Running OCR (this takes a minute for a 76-page file)...\n")

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        size = output_file.stat().st_size / 1_000_000
        print(f"\nDone. Output: {output_file} ({size:.1f} MB)")
    else:
        print(f"\nOCR failed (exit code {result.returncode})")

    return output_file


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ocr.py input.pdf [output.pdf]")
        sys.exit(1)
    ocr_pdf(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
