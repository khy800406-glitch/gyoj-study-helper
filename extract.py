"""학생 교재 PDF에서 텍스트를 추출한다. 스캔본은 병렬 OCR을 쓴다."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import pypdfium2 as pdfium


ProgressFn = Callable[[int, int, str], None]

_OCR_SCALE = 1.2
_OCR_CONFIG = "--oem 1 --psm 6 -c tessedit_do_invert=0"
_OCR_LANG = "kor+eng"
_OCR_WORKERS = max(1, min(os.cpu_count() or 4, 16))


@dataclass(frozen=True)
class ExtractResult:
    pages: list[str]
    text: str
    page_count: int
    char_count: int
    char_count_no_space: int
    used_ocr: bool = False


def _clean_page_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\ufeff", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_embedded(file_bytes: bytes, on_progress: ProgressFn | None) -> list[str]:
    pdf = pdfium.PdfDocument(file_bytes)
    try:
        total = len(pdf)
        if total == 0:
            raise ValueError("페이지가 없는 PDF입니다.")
        pages: list[str] = []
        for index in range(total):
            if on_progress:
                on_progress(index + 1, total, "글자 추출")
            page = pdf[index]
            textpage = page.get_textpage()
            raw = textpage.get_text_bounded() or ""
            textpage.close()
            page.close()
            pages.append(_clean_page_text(raw))
        return pages
    finally:
        pdf.close()


def _is_mostly_scan(pages: list[str]) -> bool:
    sample = pages[:3] if len(pages) <= 3 else pages[:2] + pages[-1:]
    chars = sum(len(re.sub(r"\s+", "", p)) for p in sample)
    return chars < 40


def _ocr_one(image, lang: str, config: str) -> str:
    import pytesseract

    return pytesseract.image_to_string(image, lang=lang, config=config) or ""


def _ocr_pages(file_bytes: bytes, on_progress: ProgressFn | None) -> list[str]:
    pdf = pdfium.PdfDocument(file_bytes)
    try:
        total = len(pdf)
        images = []
        for index in range(total):
            if on_progress:
                on_progress(index + 1, total, "페이지 준비")
            page = pdf[index]
            bitmap = page.render(scale=_OCR_SCALE)
            images.append(bitmap.to_pil().convert("L"))
            bitmap.close()
            page.close()
    finally:
        pdf.close()

    pages = [""] * total
    done = 0
    workers = min(_OCR_WORKERS, max(1, total))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_ocr_one, images[i], _OCR_LANG, _OCR_CONFIG): i
            for i in range(total)
        }
        for future in as_completed(futures):
            index = futures[future]
            pages[index] = _clean_page_text(future.result())
            done += 1
            if on_progress:
                on_progress(done, total, "스캔 글자 인식")
    return pages


def extract_pdf(file_bytes: bytes, on_progress: ProgressFn | None = None) -> ExtractResult:
    if not file_bytes:
        raise ValueError("빈 파일입니다.")

    try:
        pages = _extract_embedded(file_bytes, on_progress)
    except Exception as exc:
        raise ValueError(f"PDF를 열지 못했습니다: {exc}") from exc

    used_ocr = False
    joined = "\n\n".join(page for page in pages if page).strip()
    if _is_mostly_scan(pages):
        try:
            pages = _ocr_pages(file_bytes, on_progress)
            used_ocr = True
            joined = "\n\n".join(page for page in pages if page).strip()
        except Exception as exc:
            raise ValueError(
                "사진으로 찍은 스캔 PDF라 글자를 읽으려면 OCR이 필요합니다. "
                f"지금은 인식에 실패했습니다: {exc}"
            ) from exc

    no_space = re.sub(r"\s+", "", joined)
    return ExtractResult(
        pages=pages,
        text=joined,
        page_count=len(pages),
        char_count=len(joined),
        char_count_no_space=len(no_space),
        used_ocr=used_ocr,
    )
