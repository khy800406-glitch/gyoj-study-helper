"""교재 전체 요약: 2,000~3,000자 Map 후 대단원/소단원 Reduce."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from scope import (
    Chunk,
    TextScope,
    extract_scope,
    split_chunks,
    unit_spans,
)


MODEL = "grok-4.6"
API_BASE = "https://api.x.ai/v1"
REDUCE_BATCH = 8

ProgressFn = Callable[[int, int, str], None]

_SENT_SPLIT = re.compile(r"(?<=[\.!?])\s+|\n{2,}")
_NOISE = re.compile(r"^[\d\s\-–—./()]+$")
_TOKEN = re.compile(r"[가-힣A-Za-z0-9]{2,}")
_CUE = (
    "중요",
    "핵심",
    "정의",
    "개념",
    "원리",
    "특징",
    "원인",
    "결과",
    "따라서",
    "즉",
    "정리",
    "요점",
    "목적",
    "방법",
    "차이",
    "비교",
    "예",
    "법칙",
    "공식",
)
_CONTINUE = ("즉", "따라서", "그러나", "하지만", "그리고", "또", "또한")
_DEFINE = re.compile(r"(은|는).+(이다|한다)\.?$")

_MAP_SYSTEM = (
    "당신은 학생 교재를 부분별로 정리하는 도우미입니다. "
    "지금 보는 글은 긴 교재를 2,000~3,000자씩 나눈 한 조각입니다. "
    "이 조각에만 근거하세요. 없는 내용을 만들지 마세요.\n\n"
    "형식:\n"
    "## 이 부분의 단원\n"
    "(단원/장/절 제목이 보이면 그대로, 없으면 '제목 없음')\n"
    "## 핵심\n"
    "(3~6문장)\n"
    "## 중요 포인트\n"
    "- (3~6개)"
)

_REDUCE_SYSTEM = (
    "당신은 교재 전체의 흐름을 꿰는 도우미입니다. "
    "아래는 각 조각을 요약한 Map 결과입니다. 중복을 없애고 Reduce 하세요. "
    "없는 단원을 지어내지 마세요. 초안에 단원 이름이 있으면 그것을 쓰세요. "
    "쉬운 한국어로, 아래 형식을 지키세요.\n\n"
    "## 전체 흐름\n"
    "(교재가 어떤 순서로 전개되는지 3~6문장)\n\n"
    "## 대단원 1. 제목\n"
    "(이 대단원의 핵심 2~5문장)\n"
    "### 소단원\n"
    "- 중요 포인트\n\n"
    "## 대단원 2. 제목\n"
    "...\n\n"
    "## 전체 중요 포인트\n"
    "1. (시험·이해에 필요한 포인트 5~12개)"
)

_SCOPE_REDUCE_SYSTEM = (
    "당신은 지정된 단원만 정리하는 도우미입니다. "
    "아래 Map 결과와 범위 밖 내용은 빼고, 해당 단원의 흐름만 Reduce 하세요. "
    "없는 내용을 만들지 마세요.\n\n"
    "## {label} 핵심\n"
    "(2~5문단)\n"
    "### 소단원\n"
    "- 중요 포인트\n\n"
    "## 중요 포인트\n"
    "1. (5~10개)"
)


@dataclass(frozen=True)
class MappedChunk:
    chunk: Chunk
    summary: str


@dataclass(frozen=True)
class Summary:
    text: str
    source: str  # "llm" | "extractive"
    chunk_count: int = 1
    scope_label: str = "전체"


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p and p.strip()]
    sentences: list[str] = []
    for part in parts:
        if _NOISE.fullmatch(part) or len(part) < 12:
            continue
        cleaned = re.sub(r"\s+", " ", part)
        if sentences and cleaned.startswith(_CONTINUE):
            sentences[-1] = sentences[-1] + " " + cleaned
            continue
        sentences.append(cleaned)
    return sentences


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def extractive_summary(text: str, question: str | None = None, limit: int = 10) -> str:
    sentences = _split_sentences(text)
    if not sentences:
        return text.strip()
    if len(sentences) <= 4:
        body = " ".join(sentences)
        points = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, start=1))
        return f"## 핵심 내용\n{body}\n\n## 중요 포인트\n{points}"

    df: dict[str, int] = {}
    sent_tokens: list[list[str]] = []
    for sent in sentences:
        toks = _tokens(sent)
        sent_tokens.append(toks)
        for tok in set(toks):
            df[tok] = df.get(tok, 0) + 1

    n = len(sentences)
    q_tokens = set(_tokens(question or ""))
    scores: list[float] = []
    for i, toks in enumerate(sent_tokens):
        if not toks:
            scores.append(0.0)
            continue
        tfidf = sum(1.0 / df.get(tok, 1) for tok in toks) / len(toks)
        cue = 0.35 if any(c in sentences[i] for c in _CUE) else 0.0
        define = 0.3 if _DEFINE.search(sentences[i]) else 0.0
        pos = 0.25 if i == 0 else (0.12 if i < max(3, n // 12) or i >= n - 2 else 0.0)
        overlap = 0.0
        if q_tokens:
            overlap = 0.5 * len(q_tokens.intersection(toks)) / len(q_tokens)
        length_pen = 0.0 if 20 <= len(sentences[i]) <= 180 else -0.1
        scores.append(tfidf + cue + define + pos + overlap + length_pen)

    k = min(limit, max(5, n // 8), n)
    ranked = sorted(range(n), key=lambda i: scores[i], reverse=True)[:k]
    chosen = [sentences[i] for i in sorted(ranked)]
    core = " ".join(chosen[: min(4, len(chosen))])
    points = "\n".join(f"{i}. {s}" for i, s in enumerate(chosen, start=1))
    return f"## 핵심 내용\n{core}\n\n## 중요 포인트\n{points}"


def _complete(api_key: str, user_content: str, system: str) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=API_BASE,
        timeout=httpx.Timeout(180.0),
    )
    response = client.responses.create(
        model=MODEL,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        store=False,
    )
    text = (getattr(response, "output_text", None) or "").strip()
    if text:
        return text
    raise RuntimeError("모델이 빈 답을 돌려줬습니다.")


def _header(scope: TextScope, chunk_count: int, source: str) -> str:
    how = "xAI로 Map-Reduce" if source == "llm" else "교재 문장에서 Map-Reduce"
    return (
        f"> 범위: **{scope.label}** · {chunk_count}개 부분"
        f"(각 2,000~3,000자)을 {how} 했습니다.\n"
    )


def _extractive_reduce(mapped: list[MappedChunk], scoped_text: str, scope: TextScope) -> str:
    units = unit_spans(scoped_text)
    lines: list[str] = []
    if scope.label == "전체":
        lines.append("## 전체 흐름")
        if units:
            flow = " → ".join(
                f"{u.num}{u.kind} {u.title}".strip() if u.title else f"{u.num}{u.kind}"
                for u in units
            )
            lines.append(f"이 교재는 {flow} 순서로 이어집니다.")
        else:
            lines.append("단원 제목이 분명하지 않아, 글을 순서대로 나눠 정리했습니다.")
        lines.append("")
        if units:
            for unit in units:
                title = unit.title or f"{unit.num}{unit.kind}"
                lines.append(f"## 대단원 {unit.num}. {title}")
                lines.append(extractive_summary(unit.text, limit=8))
                for sub in unit.subs:
                    sub_title = sub.title or f"{sub.num}{sub.kind}"
                    lines.append(f"### 소단원 {sub.num}. {sub_title}")
                    lines.append(extractive_summary(sub.text, limit=5))
                lines.append("")
        else:
            for item in mapped:
                lines.append(f"## 대단원 부분 {item.chunk.index}")
                lines.append(item.summary)
                lines.append("")
    else:
        lines.append(f"## {scope.label} 핵심")
        lines.append(extractive_summary(scoped_text, limit=10))
        if units:
            for unit in units:
                for sub in unit.subs:
                    sub_title = sub.title or f"{sub.num}{sub.kind}"
                    lines.append(f"### 소단원 {sub.num}. {sub_title}")
                    lines.append(extractive_summary(sub.text, limit=5))
        elif len(mapped) > 1:
            for item in mapped:
                lines.append(f"### 소단원 {item.chunk.index}")
                lines.append(item.summary)
    return "\n".join(lines).strip()


def _map_extractive(chunks: list[Chunk], question: str | None, on_progress: ProgressFn | None) -> list[MappedChunk]:
    mapped: list[MappedChunk] = []
    total = len(chunks)
    for chunk in chunks:
        if on_progress:
            on_progress(chunk.index, total + 1, "Map 부분 요약")
        mapped.append(
            MappedChunk(
                chunk=chunk,
                summary=extractive_summary(chunk.text, question=question, limit=6),
            )
        )
    return mapped


def _map_llm(
    chunks: list[Chunk],
    api_key: str,
    question: str | None,
    on_progress: ProgressFn | None,
) -> list[MappedChunk]:
    mapped: list[MappedChunk] = []
    total = len(chunks)
    extra = f"학생 요청: {question}\n" if question else ""
    for chunk in chunks:
        if on_progress:
            on_progress(chunk.index, total + 1, "Map 부분 요약")
        prompt = (
            f"{extra}이것은 {total}개 조각 중 {chunk.index}번째입니다.\n\n"
            f"{chunk.text}"
        )
        mapped.append(
            MappedChunk(chunk=chunk, summary=_complete(api_key, prompt, _MAP_SYSTEM))
        )
    return mapped


def _pack_map(mapped: list[MappedChunk]) -> str:
    blocks = []
    for item in mapped:
        blocks.append(f"[부분 {item.chunk.index}]\n{item.summary}")
    return "\n\n".join(blocks)


def _reduce_llm(
    mapped: list[MappedChunk],
    api_key: str,
    scope: TextScope,
    question: str | None,
    on_progress: ProgressFn | None,
) -> str:
    total = len(mapped) + 1
    if on_progress:
        on_progress(total, total, "Reduce 최종 정리")

    packed = _pack_map(mapped)
    if len(mapped) > REDUCE_BATCH:
        groups: list[str] = []
        for i in range(0, len(mapped), REDUCE_BATCH):
            batch = mapped[i : i + REDUCE_BATCH]
            groups.append(
                _complete(
                    api_key,
                    "아래 부분 요약들을 하나의 중간 초안으로 합치세요.\n\n" + _pack_map(batch),
                    _MAP_SYSTEM,
                )
            )
        packed = "\n\n".join(f"[중간 {i}]\n{g}" for i, g in enumerate(groups, start=1))

    if scope.label == "전체":
        system = _REDUCE_SYSTEM
        focus = "교재 전체 Map 결과입니다. 대단원/소단원으로 Reduce 하세요.\n\n"
    else:
        system = _SCOPE_REDUCE_SYSTEM.format(label=scope.label)
        focus = f"범위는 {scope.label} 입니다. 이 범위만 Reduce 하세요.\n\n"
    extra = f"학생 요청: {question}\n" if question else ""
    return _complete(api_key, extra + focus + packed, system)


def resolve_api_key(explicit: str | None = None) -> str | None:
    key = (explicit or "").strip() or os.environ.get("XAI_API_KEY", "").strip()
    return key or None


def summarize_textbook(
    text: str,
    question: str | None = None,
    api_key: str | None = None,
    on_progress: ProgressFn | None = None,
) -> Summary:
    scope = extract_scope(text, question)
    if not scope.found:
        message = (
            f"교재에서 **{scope.label}** 구간을 찾지 못했습니다. "
            "본문에 '3단원', '제 3장', '제3과' 같은 표기가 있는지 확인해 주세요."
        )
        return Summary(text=message, source="extractive", chunk_count=0, scope_label=scope.label)

    chunks = split_chunks(scope.text)
    key = resolve_api_key(api_key)
    if key:
        try:
            mapped = _map_llm(chunks, key, question, on_progress)
            body = _reduce_llm(mapped, key, scope, question, on_progress)
            return Summary(
                text=_header(scope, len(chunks), "llm") + "\n" + body,
                source="llm",
                chunk_count=len(chunks),
                scope_label=scope.label,
            )
        except Exception:
            mapped = _map_extractive(chunks, question, on_progress)
            body = _extractive_reduce(mapped, scope.text, scope)
            note = "API 요약에 실패해서, 교재 문장에서 Map-Reduce 했습니다.\n\n"
            return Summary(
                text=note + _header(scope, len(chunks), "extractive") + "\n" + body,
                source="extractive",
                chunk_count=len(chunks),
                scope_label=scope.label,
            )

    mapped = _map_extractive(chunks, question, on_progress)
    if on_progress:
        on_progress(len(chunks) + 1, len(chunks) + 1, "Reduce 최종 정리")
    body = _extractive_reduce(mapped, scope.text, scope)
    return Summary(
        text=_header(scope, len(chunks), "extractive") + "\n" + body,
        source="extractive",
        chunk_count=len(chunks),
        scope_label=scope.label,
    )
