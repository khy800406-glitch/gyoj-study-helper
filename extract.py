"""학생 교재 PDF에서 텍스트를 추출한다. 스캔본은 OCR을 쓴다."""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from dataclasses import dataclass

import pypdfium2 as pdfium


ProgressFn = Callable[[int, int, str], None]


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


def _ocr_pages(file_bytes: bytes, on_progress: ProgressFn | None) -> list[str]:
    import pytesseract

    pdf = pdfium.PdfDocument(file_bytes)
    try:
        total = len(pdf)
        pages: list[str] = []
        for index in range(total):
            if on_progress:
                on_progress(index + 1, total, "스캔 글자 인식")
            page = pdf[index]
            bitmap = page.render(scale=1.8)
            image = bitmap.to_pil()
            raw = pytesseract.image_to_string(image, lang="kor+eng") or ""
            bitmap.close()
            page.close()
            pages.append(_clean_page_text(raw))
        return pages
    finally:
        pdf.close()


def extract_pdf(file_bytes: bytes, on_progress: ProgressFn | None = None) -> ExtractResult:
    if not file_bytes:
        raise ValueError("빈 파일입니다.")

    used_ocr = False
    try:
        pages = _extract_embedded(file_bytes, on_progress)
    except Exception as exc:
        raise ValueError(f"PDF를 열지 못했습니다: {exc}") from exc

    joined = "\n\n".join(page for page in pages if page).strip()
    if len(re.sub(r"\s+", "", joined)) < 80:
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
