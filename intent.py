"""공부 도우미 말 의도: 읽어주기 / 요약 / 요약 읽어주기."""

from __future__ import annotations

import re

Intent = str  # "read" | "read_summary" | "summarize" | "quiz"

_GENERIC = {
    "요약",
    "요약해",
    "요약해줘",
    "요약해주세요",
    "핵심",
    "핵심만",
    "핵심요약",
    "핵심 요약",
    "정리",
    "정리해",
    "정리해줘",
    "포인트",
    "중요포인트",
    "중요 포인트",
    "중요한내용",
    "중요한 내용",
    "읽어",
    "읽어줘",
    "읽어주세요",
    "읽어주기",
    "낭독",
    "들려줘",
    "요약읽어줘",
    "요약 읽어줘",
    "전체요약",
    "전체 요약",
    "전부요약",
    "전부 요약",
    "전체정리",
    "전체 정리",
    "퀴즈",
    "퀴즈만들어줘",
    "퀴즈 만들어줘",
    "시험지",
    "시험지뽑아줘",
    "시험지 뽑아줘",
}


def classify(message: str) -> Intent:
    compact = re.sub(r"\s+", "", message)
    wants_quiz = any(
        w in compact for w in ("퀴즈", "시험지", "시험문제", "문제내", "문제만들")
    )
    wants_read = any(w in compact for w in ("읽어", "낭독", "들려"))
    wants_sum = any(
        w in compact for w in ("요약", "핵심", "포인트", "정리", "중요내용", "중요한내용")
    )
    if wants_quiz:
        return "quiz"
    if wants_read and wants_sum:
        return "read_summary"
    if wants_read:
        return "read"
    return "summarize"


def focus_question(message: str) -> str | None:
    compact = re.sub(r"\s+", "", message).strip()
    if compact in {re.sub(r"\s+", "", g) for g in _GENERIC}:
        return None
    return message.strip() or None
