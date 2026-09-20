"""교재 기반 학습 퀴즈 출제와 채점."""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field

from scope import extract_scope
from summarize import _complete, resolve_api_key


_SENT_SPLIT = re.compile(r"(?<=[\.!?])\s+|\n{2,}")
_TOKEN = re.compile(r"[가-힣A-Za-z0-9]{2,}")
_HANGUL = re.compile(r"^[가-힣]{2,8}$")
_ENDING = re.compile(r"(입니다|습니다|이다|한다|된다|했다|하는|있는|하세요)$")
_PARTICLE = re.compile(r"(에서|으로|부터|까지|이며|이고|은|는|이|가|을|를|의|에|로|와|과|도|만)$")
_STOP = {
    "그리고",
    "그러나",
    "하지만",
    "그래서",
    "따라서",
    "또는",
    "이것",
    "그것",
    "저것",
    "우리",
    "학생",
    "선생님",
    "교재",
    "내용",
    "다음",
    "이상",
    "이하",
    "각각",
    "모든",
    "여러",
    "대한",
    "통해",
    "위해",
    "따라",
    "경우",
    "때문",
    "문제",
    "단원",
    "과정",
    "학습",
    "있다",
    "없다",
    "한다",
    "이다",
    "된다",
    "했다",
    "하는",
    "있는",
    "같은",
    "다른",
    "이런",
    "저런",
    "어떤",
    "무엇",
    "하나",
    "중요",
    "핵심",
    "포인트",
    "부분",
    "전체",
    "흐름",
}
_GENERIC_DISTRACTORS = [
    "산소",
    "중력",
    "화산",
    "분수",
    "전류",
    "염색체",
    "기압",
    "밀도",
    "증발",
    "마찰",
]

_QUIZ_SYSTEM = (
    "당신은 학생 교재로 학습 점검을 내는 선생님입니다. "
    "주어진 교재(또는 요약)에만 근거하세요. 없는 사실을 만들지 마세요. "
    "쉬운 한국어로, JSON만 출력하세요.\n"
    "객관식 3문항(보기 4개)과 주관식 핵심 단어 맞추기 2문항을 냅니다.\n"
    "형식:\n"
    "{\n"
    '  "multiple_choice": [\n'
    "    {\n"
    '      "prompt": "질문",\n'
    '      "choices": ["보기1", "보기2", "보기3", "보기4"],\n'
    '      "answer_index": 0,\n'
    '      "explanation": "왜 그 답이 맞는지 친절히"\n'
    "    }\n"
    "  ],\n"
    '  "short_answer": [\n'
    "    {\n"
    '      "prompt": "빈칸에 핵심 단어를 쓰세요: ... ______ ...",\n'
    '      "answer": "정답",\n'
    '      "aliases": ["다른표기"],\n'
    '      "explanation": "친절한 해설"\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "answer_index는 0부터 3. 주관식 정답은 짧은 핵심 단어."
)


@dataclass
class ChoiceQuestion:
    prompt: str
    choices: list[str]
    answer_index: int
    explanation: str


@dataclass
class ShortQuestion:
    prompt: str
    answer: str
    aliases: list[str] = field(default_factory=list)
    explanation: str = ""


@dataclass
class Quiz:
    multiple_choice: list[ChoiceQuestion]
    short_answer: list[ShortQuestion]
    source: str
    scope_label: str = "전체"


@dataclass
class GradedItem:
    prompt: str
    given: str
    correct_answer: str
    is_correct: bool
    explanation: str
    kind: str  # "객관식" | "주관식"


@dataclass
class GradeResult:
    items: list[GradedItem]
    correct: int
    total: int


def _sentences(text: str) -> list[str]:
    parts = [re.sub(r"\s+", " ", p).strip() for p in _SENT_SPLIT.split(text)]
    return [p for p in parts if len(p) >= 12]


def _stem(token: str) -> str | None:
    if re.search(
        r"(하는|되는|만드는|있는|없는|일어나는|이용해|시킨다|쓴다|진다|해|히|며|시켜)$",
        token,
    ):
        return None
    if token.endswith("는") and re.search(r"(하|되|키|이|뀌|만드)$", token[:-1]):
        return None
    word = _ENDING.sub("", token)
    word = _PARTICLE.sub("", word)
    if not _HANGUL.fullmatch(word) or word in _STOP:
        return None
    return word


def _nouns(text: str) -> list[str]:
    counts: Counter[str] = Counter()
    for tok in _TOKEN.findall(text):
        stem = _stem(tok)
        if not stem:
            continue
        if not re.search(
            rf"{re.escape(stem)}(?:은|는|이|가|을|를|의|에|에서|이다|이란|\s|[.!?,]|$)",
            text,
        ):
            continue
        counts[stem] += 1
    ranked = [w for w, _n in counts.most_common(40) if 2 <= len(w) <= 8]
    return ranked


def _blank(sentence: str, noun: str) -> str:
    if noun in sentence:
        return sentence.replace(noun, "______", 1)
    return f"다음 빈칸에 들어갈 핵심 단어는 무엇일까요? ______ ({sentence[:40]})"


def _distractors(answer: str, nouns: list[str], need: int = 3) -> list[str]:
    pool = [n for n in nouns if n != answer]
    for extra in _GENERIC_DISTRACTORS:
        if extra != answer and extra not in pool:
            pool.append(extra)
    picked: list[str] = []
    for item in pool:
        if item not in picked:
            picked.append(item)
        if len(picked) >= need:
            break
    while len(picked) < need:
        picked.append(f"보기{len(picked) + 1}")
    return picked[:need]


def local_quiz(text: str, scope_label: str = "전체", seed: int | None = None) -> Quiz:
    rng = random.Random(seed)
    sentences = _sentences(text)
    nouns = _nouns(text)
    if not nouns:
        nouns = [tok for tok in _TOKEN.findall(text) if len(tok) >= 2][:8]
    if not nouns:
        raise ValueError("퀴즈를 만들 핵심 단어를 찾지 못했습니다.")
    if not sentences:
        sentences = [text.strip()[:120] or "교재의 핵심 단어를 고르세요."]

    mc: list[ChoiceQuestion] = []
    used_nouns: set[str] = set()
    for i in range(3):
        noun = nouns[i % len(nouns)]
        sent = next((s for s in sentences if noun in s), sentences[i % len(sentences)])
        choices = [noun] + _distractors(noun, nouns)
        rng.shuffle(choices)
        mc.append(
            ChoiceQuestion(
                prompt=f"빈칸에 알맞은 말은 무엇일까요?\n{_blank(sent, noun)}",
                choices=choices,
                answer_index=choices.index(noun),
                explanation=(
                    f"교재 문장에서 핵심 단어는 **{noun}** 입니다. "
                    f"원문: {sent}"
                ),
            )
        )
        used_nouns.add(noun)

    short: list[ShortQuestion] = []
    short_nouns = [n for n in nouns if n not in used_nouns] or nouns
    for i in range(2):
        noun = short_nouns[i % len(short_nouns)]
        sent = next((s for s in sentences if noun in s), sentences[-(i + 1)])
        short.append(
            ShortQuestion(
                prompt=f"빈칸에 들어갈 핵심 단어를 쓰세요.\n{_blank(sent, noun)}",
                answer=noun,
                aliases=[],
                explanation=f"빈칸의 핵심 단어는 **{noun}** 입니다. 교재에는 이렇게 나와 있습니다: {sent}",
            )
        )
    return Quiz(
        multiple_choice=mc,
        short_answer=short,
        source="local",
        scope_label=scope_label,
    )


def _parse_llm_quiz(raw: str, scope_label: str) -> Quiz:
    blob = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", blob, re.I)
    if fence:
        blob = fence.group(1).strip()
    start, end = blob.find("{"), blob.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("퀴즈 JSON을 찾지 못했습니다.")
    data = json.loads(blob[start : end + 1])
    mc_raw = data.get("multiple_choice") or []
    sa_raw = data.get("short_answer") or []
    if len(mc_raw) < 3 or len(sa_raw) < 2:
        raise ValueError("문항 수가 부족합니다.")
    mc: list[ChoiceQuestion] = []
    for item in mc_raw[:3]:
        choices = [str(c).strip() for c in item.get("choices") or []]
        if len(choices) != 4:
            raise ValueError("객관식 보기가 4개가 아닙니다.")
        idx = int(item.get("answer_index", 0))
        if idx < 0 or idx > 3:
            raise ValueError("정답 번호가 잘못되었습니다.")
        mc.append(
            ChoiceQuestion(
                prompt=str(item.get("prompt") or "").strip(),
                choices=choices,
                answer_index=idx,
                explanation=str(item.get("explanation") or "").strip()
                or "교재 내용을 다시 읽어 보세요.",
            )
        )
    short: list[ShortQuestion] = []
    for item in sa_raw[:2]:
        answer = str(item.get("answer") or "").strip()
        if not answer:
            raise ValueError("주관식 정답이 없습니다.")
        aliases = [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()]
        short.append(
            ShortQuestion(
                prompt=str(item.get("prompt") or "").strip(),
                answer=answer,
                aliases=aliases,
                explanation=str(item.get("explanation") or "").strip()
                or f"정답은 **{answer}** 입니다.",
            )
        )
    return Quiz(
        multiple_choice=mc,
        short_answer=short,
        source="llm",
        scope_label=scope_label,
    )


def _source_text(full_text: str, summary: str | None, question: str | None) -> tuple[str, str]:
    scope = extract_scope(full_text, question)
    if not scope.found:
        return full_text, "전체"
    base = scope.text
    if summary and len(summary) > 80 and scope.label == "전체":
        combined = summary.strip() + "\n\n" + base
        return combined[:16_000], scope.label
    return base[:16_000], scope.label


def make_quiz(
    full_text: str,
    summary: str | None = None,
    question: str | None = None,
    api_key: str | None = None,
    seed: int | None = None,
) -> Quiz:
    text, label = _source_text(full_text, summary, question)
    key = resolve_api_key(api_key)
    if key:
        try:
            raw = _complete(
                key,
                f"범위: {label}\n아래 교재로 퀴즈를 만드세요.\n\n{text}",
                _QUIZ_SYSTEM,
            )
            return _parse_llm_quiz(raw, label)
        except Exception:
            quiz = local_quiz(text, scope_label=label, seed=seed)
            quiz.source = "local"
            return quiz
    return local_quiz(text, scope_label=label, seed=seed)


def _norm(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[\"'`.,!?()\[\]~·…\-–—]", "", text)


def _short_match(given: str, answer: str, aliases: list[str]) -> bool:
    got = _norm(given)
    if not got:
        return False
    candidates = [_norm(answer), *(_norm(a) for a in aliases if a)]
    if got in candidates:
        return True
    for cand in candidates:
        if not cand:
            continue
        if cand in got or got in cand:
            if min(len(cand), len(got)) >= 2 and abs(len(cand) - len(got)) <= 2:
                return True
    return False


def grade_quiz(
    quiz: Quiz,
    mc_answers: list[int | None],
    short_answers: list[str],
) -> GradeResult:
    items: list[GradedItem] = []
    for i, question in enumerate(quiz.multiple_choice):
        picked = mc_answers[i] if i < len(mc_answers) else None
        given = (
            question.choices[picked]
            if picked is not None and 0 <= picked < len(question.choices)
            else "(응답 없음)"
        )
        ok = picked == question.answer_index
        items.append(
            GradedItem(
                prompt=question.prompt,
                given=given,
                correct_answer=question.choices[question.answer_index],
                is_correct=ok,
                explanation=question.explanation,
                kind="객관식",
            )
        )
    for i, question in enumerate(quiz.short_answer):
        given = short_answers[i] if i < len(short_answers) else ""
        ok = _short_match(given, question.answer, question.aliases)
        items.append(
            GradedItem(
                prompt=question.prompt,
                given=given.strip() or "(응답 없음)",
                correct_answer=question.answer,
                is_correct=ok,
                explanation=question.explanation,
                kind="주관식",
            )
        )
    correct = sum(1 for item in items if item.is_correct)
    return GradeResult(items=items, correct=correct, total=len(items))
