"""학생 교재 PDF에서 텍스트를 페이지 단위로 추출한다."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect


# 한글 교재에서 글자가 붙어 보이도록 자간을 조금 넓게 잡는다.
_EXTRACT_KWARGS = {
    "x_tolerance": 1.5,
    "y_tolerance": 3,
}


@dataclass(frozen=True)
class ExtractResult:
    pages: list[str]
    text: str
    page_count: int
    char_count: int
    char_count_no_space: int


def _clean_page_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\ufeff", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf(file_bytes: bytes) -> ExtractResult:
    if not file_bytes:
        raise ValueError("빈 파일입니다.")

    pages: list[str] = []
    try:
        pdf_file = pdfplumber.open(io.BytesIO(file_bytes))
    except PDFPasswordIncorrect as exc:
        raise ValueError("암호가 걸린 PDF입니다. 암호를 해제한 뒤 다시 올려 주세요.") from exc

    with pdf_file as pdf:
        if not pdf.pages:
            raise ValueError("페이지가 없는 PDF입니다.")
        for page in pdf.pages:
            raw = page.extract_text(**_EXTRACT_KWARGS) or ""
            pages.append(_clean_page_text(raw))

    text = "\n\n".join(page for page in pages if page).strip()
    no_space = re.sub(r"\s+", "", text)
    return ExtractResult(
        pages=pages,
        text=text,
        page_count=len(pages),
        char_count=len(text),
        char_count_no_space=len(no_space),
    )
