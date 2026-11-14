"""Optional local OCR for image-only pages. No remote model calls."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from shutil import which
from tempfile import TemporaryDirectory
from time import monotonic

MAX_OCR_PAGES = 20
SCANNED_MESSAGE = "Scanned PDF. Run OCR to make the original pages searchable."


class OcrInputError(ValueError):
    pass


def recognize_pages(data: bytes, pages: list[str]) -> list[str]:
    missing = [index for index, text in enumerate(pages) if not text.strip()]
    if not missing:
        return pages
    if len(missing) > MAX_OCR_PAGES:
        raise OcrInputError("OCR supports up to 20 image-only pages per PDF. Split the PDF and retry.")
    renderer = which(os.getenv("SOCRA_PDFTOPPM_BIN", "pdftoppm"))
    reader = which(os.getenv("SOCRA_TESSERACT_BIN", "tesseract"))
    if not renderer or not reader:
        raise OcrInputError("OCR is unavailable on this worker. Ask the administrator to install Poppler and Tesseract.")
    deadline = monotonic() + 130
    result = list(pages)
    with TemporaryDirectory(prefix="socra-ocr-") as tmp:
        source = Path(tmp, "source.pdf")
        source.write_bytes(data)
        for index in missing:
            page = str(index + 1)
            image = Path(tmp, "page.png")
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("OCR", 130)
            subprocess.run([renderer, "-f", page, "-l", page, "-scale-to", "1800", "-singlefile",
                            "-png", str(source), str(image.with_suffix(""))],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=min(remaining, 12), check=True)
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("OCR", 130)
            output = subprocess.run([reader, str(image), "stdout", "-l", os.getenv("SOCRA_OCR_LANGUAGES", "eng+fra")],
                                    capture_output=True, timeout=min(remaining, 15), check=True)
            result[index] = output.stdout.decode("utf-8", errors="replace").strip()
            image.unlink()
            if sum(map(len, result)) > 1_000_000:
                raise OcrInputError("OCR output exceeded the text limit. Split the PDF and retry.")
    if not any(text.strip() for text in result):
        raise OcrInputError("OCR found no readable text. Try a clearer scan.")
    return result
