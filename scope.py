"""교재 텍스트에서 단원/장 범위를 찾고, 긴 글을 2,000~3,000자 청크로 나눈다."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


CHUNK_MIN = 2_000
CHUNK_MAX = 3_000
CHUNK_TARGET = 2_500
CHUNK_OVERLAP = 120

_MAJOR = ("단원", "장", "과")
_MINOR = ("절", "소단원")
_FULL_REQUEST = re.compile(r"전체\s*요약|전부\s*요약|다\s*요약|전체\s*내용|전체\s*정리")

_ROMAN = {
    "Ⅰ": 1,
    "Ⅱ": 2,
    "Ⅲ": 3,
    "Ⅳ": 4,
    "Ⅴ": 5,
    "Ⅵ": 6,
    "Ⅶ": 7,
    "Ⅷ": 8,
    "Ⅸ": 9,
    "Ⅹ": 10,
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
}

_NUM = r"(?P<num>\d{1,2}|[IVXⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+)"
_KIND = r"(?P<kind>단원|장|과|절|소단원)"

HEADING_RE = re.compile(
    rf"(?m)^[ \t]*(?:제\s*)?{_NUM}\s*{_KIND}\s*[.．:：)\-]?\s*(?P<title>[^\n]{{0,80}})"
    rf"|^[ \t]*(?P<kind2>단원|장|과|절|소단원)\s*(?P<num2>\d{{1,2}})\s*[.．:：-]?\s*(?P<title2>[^\n]{{0,80}})"
)

QUERY_RE = re.compile(
    rf"(?:제\s*)?{_NUM}\s*{_KIND}"
    rf"(?:\s*(?:부터|~|～|-|－|내지)\s*(?:제\s*)?(?P<num_b>\d{{1,2}}|[IVXⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+)\s*(?P<kind_b>단원|장|과|절|소단원))?"
    rf"|(?P<kind3>단원|장|과|절|소단원)\s*(?P<num3>\d{{1,2}})"
)

KEYWORD_RE = re.compile(
    r"제?\s*(?P<num>\d{1,2})\s*(?P<kind>단원|장|과|절|소단원)"
    r"|(?P<kind2>단원|장|과|절|소단원)\s*(?P<num2>\d{1,2})"
)


@dataclass(frozen=True)
class Heading:
    start: int
    num: int
    kind: str
    title: str
    major: bool


@dataclass(frozen=True)
class UnitSpan:
    num: int
    kind: str
    title: str
    start: int
    end: int
    text: str
    subs: list["UnitSpan"] = field(default_factory=list)


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class TextScope:
    text: str
    label: str
    found: bool
    start: int = 0
    end: int = 0
    chunk_ready: bool = True


@dataclass(frozen=True)
class UnitRequest:
    start_num: int
    end_num: int
    kind: str  # 단원|장|과|절|소단원|any


def parse_num(raw: str | None) -> int | None:
    if not raw:
        return None
    value = raw.strip()
    if value.isdigit():
        number = int(value)
        return number if 1 <= number <= 40 else None
    return _ROMAN.get(value) or _ROMAN.get(value.upper())


def parse_unit_request(question: str | None) -> UnitRequest | None:
    if not question or not question.strip():
        return None
    if _FULL_REQUEST.search(question) and not QUERY_RE.search(question):
        return None
    match = QUERY_RE.search(question)
    if not match:
        return None
    num = parse_num(match.group("num") or match.group("num3"))
    kind = match.group("kind") or match.group("kind3") or "any"
    if num is None:
        return None
    end_num = parse_num(match.group("num_b")) or num
    end_kind = match.group("kind_b") or kind
    if end_num < num:
        num, end_num = end_num, num
    return UnitRequest(start_num=num, end_num=end_num, kind=kind or end_kind or "any")


def _heading_from_match(match: re.Match[str]) -> Heading | None:
    num = parse_num(match.group("num") or match.group("num2"))
    kind = match.group("kind") or match.group("kind2")
    title = (match.group("title") or match.group("title2") or "").strip()
    title = re.sub(r"^[\s.．:：\-–—]+", "", title)
    if num is None or not kind:
        return None
    return Heading(
        start=match.start(),
        num=num,
        kind=kind,
        title=title,
        major=kind in _MAJOR,
    )


def find_headings(text: str) -> list[Heading]:
    found: list[Heading] = []
    for match in HEADING_RE.finditer(text):
        heading = _heading_from_match(match)
        if heading:
            found.append(heading)
    return found


def unit_spans(text: str) -> list[UnitSpan]:
    headings = find_headings(text)
    majors_raw = [h for h in headings if h.major]
    minors = [h for h in headings if not h.major]
    majors: list[Heading] = []
    for i, heading in enumerate(majors_raw):
        end = majors_raw[i + 1].start if i + 1 < len(majors_raw) else len(text)
        if end - heading.start < 80:
            continue
        majors.append(heading)
    if not majors:
        return []
    spans: list[UnitSpan] = []
    for i, heading in enumerate(majors):
        end = majors[i + 1].start if i + 1 < len(majors) else len(text)
        body = text[heading.start : end].strip()
        subs: list[UnitSpan] = []
        inner = [m for m in minors if heading.start <= m.start < end]
        for j, sub in enumerate(inner):
            sub_end = inner[j + 1].start if j + 1 < len(inner) else end
            subs.append(
                UnitSpan(
                    num=sub.num,
                    kind=sub.kind,
                    title=sub.title,
                    start=sub.start,
                    end=sub_end,
                    text=text[sub.start : sub_end].strip(),
                )
            )
        spans.append(
            UnitSpan(
                num=heading.num,
                kind=heading.kind,
                title=heading.title,
                start=heading.start,
                end=end,
                text=body,
                subs=subs,
            )
        )
    return spans


def _longest_span(candidates: list[tuple[int, int]]) -> tuple[int, int] | None:
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[1] - item[0])


def _keyword_hits(text: str, number: int, kind: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for match in KEYWORD_RE.finditer(text):
        num = parse_num(match.group("num") or match.group("num2"))
        hit_kind = match.group("kind") or match.group("kind2") or ""
        if num != number:
            continue
        if kind not in {"any", ""} and hit_kind != kind and not (
            kind in _MAJOR and hit_kind in _MAJOR
        ):
            continue
        hits.append((match.start(), hit_kind))
    return hits


def extract_scope(text: str, question: str | None) -> TextScope:
    request = parse_unit_request(question)
    if request is None:
        return TextScope(text=text, label="전체", found=True, start=0, end=len(text))

    kind = request.kind
    start_num = request.start_num
    end_num = request.end_num
    if start_num == end_num:
        if kind in _MINOR:
            label = f"{start_num}{kind}"
        else:
            label = f"{start_num}단원" if kind in {"any", "단원"} else f"{start_num}{kind}"
    else:
        unit = "단원" if kind in {"any", "단원"} else kind
        label = f"{start_num}~{end_num}{unit}"

    majors = [h for h in find_headings(text) if h.major]
    pool = majors
    if kind in _MINOR:
        pool = [h for h in find_headings(text) if not h.major] or majors

    preferred = [h for h in pool if start_num <= h.num <= end_num]
    if kind not in {"any", ""}:
        exact = [h for h in preferred if h.kind == kind]
        if exact:
            preferred = exact

    candidates: list[tuple[int, int]] = []
    starts = [h for h in preferred if h.num == start_num] or preferred
    in_range = set(range(start_num, end_num + 1))
    for heading in starts:
        following = [h for h in pool if h.start > heading.start and h.num > end_num]
        if not following:
            following = [
                h for h in pool if h.start > heading.start and h.num not in in_range
            ]
        end = following[0].start if following else len(text)
        if end > heading.start:
            candidates.append((heading.start, end))

    if not candidates:
        hits = _keyword_hits(text, start_num, kind if kind != "any" else "단원")
        if not hits and kind != "any":
            hits = _keyword_hits(text, start_num, "any")
        for start, _hit_kind in hits:
            nxt = None
            for match in KEYWORD_RE.finditer(text, start + 1):
                num = parse_num(match.group("num") or match.group("num2"))
                hit_kind = match.group("kind") or match.group("kind2") or ""
                if num is None:
                    continue
                if num > end_num and (hit_kind in _MAJOR or kind in _MINOR):
                    nxt = match.start()
                    break
            candidates.append((start, nxt if nxt is not None else len(text)))

    span = _longest_span(candidates)
    if span is None or span[1] - span[0] < 20:
        return TextScope(text="", label=label, found=False, start=0, end=0)

    start, end = span
    sliced = text[start:end].strip()
    if not sliced:
        return TextScope(text="", label=label, found=False, start=start, end=end)
    return TextScope(text=sliced, label=label, found=True, start=start, end=end)


def split_chunks(text: str) -> list[Chunk]:
    source = text.strip()
    if not source:
        return []
    if len(source) <= CHUNK_MAX:
        return [Chunk(index=1, start=0, end=len(source), text=source)]

    pieces: list[tuple[int, int]] = []
    start = 0
    n = len(source)
    while start < n:
        remain = n - start
        if remain <= CHUNK_MAX:
            pieces.append((start, n))
            break
        lo = start + CHUNK_MIN
        hi = min(n, start + CHUNK_MAX)
        region = source[lo:hi]
        cut = None
        for sep in ("\n\n", "\n", ". ", "? ", "! ", "다. ", "요. "):
            pos = region.rfind(sep)
            if pos != -1:
                cut = lo + pos + len(sep)
                break
        if cut is None or cut <= start:
            cut = min(n, start + CHUNK_TARGET)
        pieces.append((start, cut))
        next_start = cut
        if CHUNK_OVERLAP and cut < n:
            next_start = max(start + 1, cut - CHUNK_OVERLAP)
            back = source.rfind("\n", start, next_start)
            if back > start + CHUNK_MIN // 2:
                next_start = back + 1
        start = next_start

    if len(pieces) >= 2:
        last_s, last_e = pieces[-1]
        if last_e - last_s < 400:
            prev_s, _prev_e = pieces[-2]
            merged_len = last_e - prev_s
            if merged_len <= CHUNK_MAX + 500:
                pieces[-2] = (prev_s, last_e)
                pieces.pop()

    chunks: list[Chunk] = []
    for i, (s, e) in enumerate(pieces, start=1):
        body = source[s:e].strip()
        if body:
            chunks.append(Chunk(index=i, start=s, end=e, text=body))
    return chunks
