"""학생 교재 PDF: 텍스트 추출, 읽어주기, 핵심 요약, 퀴즈."""

from __future__ import annotations

import hashlib
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from extract import extract_pdf
from intent import classify, focus_question
from quiz import grade_quiz, make_quiz
from summarize import summarize_textbook
from tts import make_speech, render_player

SAMPLE_PDF = Path(__file__).resolve().parent / "sample" / "sample.pdf"

NEED_PDF = "먼저 상단의 교재 PDF 파일을 업로드해 주세요!"

load_dotenv(Path(__file__).resolve().parent / ".env")

st.set_page_config(page_title="교재 공부 도우미", layout="wide")


def _secret_api_key() -> str:
    try:
        return str(st.secrets.get("XAI_API_KEY", "") or "")
    except Exception:
        return ""


def init_session() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("summary", None)
    st.session_state.setdefault("speak_text", "")
    st.session_state.setdefault("speak_label", "")
    st.session_state.setdefault("quiz", None)
    st.session_state.setdefault("quiz_grade", None)
    st.session_state.setdefault("quiz_nonce", 0)
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("file_id", None)
    st.session_state.setdefault("audio_bytes", None)
    if "api_key_input" not in st.session_state:
        st.session_state.api_key_input = _secret_api_key()


def reset_study_state() -> None:
    st.session_state.messages = []
    st.session_state.summary = None
    st.session_state.speak_text = ""
    st.session_state.speak_label = ""
    st.session_state.quiz = None
    st.session_state.quiz_grade = None
    st.session_state.quiz_nonce = 0
    st.session_state.audio_bytes = None


def has_textbook() -> bool:
    result = st.session_state.get("result")
    return bool(result is not None and getattr(result, "text", ""))


def load_textbook(file_bytes: bytes) -> None:
    file_id = hashlib.sha256(file_bytes).hexdigest()
    if st.session_state.file_id == file_id and has_textbook():
        return
    reset_study_state()
    st.session_state.file_id = file_id
    with st.spinner("텍스트를 추출하는 중입니다. 교재가 길면 조금 걸릴 수 있습니다."):
        st.session_state.result = extract_pdf(file_bytes)


def prepare_audio(text: str) -> bytes | None:
    try:
        with st.spinner("목소리를 만드는 중입니다."):
            return make_speech(text)
    except Exception as exc:
        st.warning(f"음성 파일을 만들지 못했습니다. 화면의 읽기 버튼을 눌러 주세요. ({exc})")
        return None


def run_summary(question: str | None) -> str:
    result = st.session_state.result
    with st.status(":shimmer[긴 글을 나눠 요약하는 중]", expanded=True) as status:
        def on_progress(done: int, total: int, stage: str) -> None:
            status.write(f"{stage}: {done}/{total}")
            status.update(label=f"{stage} ({done}/{total})")

        summary = summarize_textbook(
            result.text,
            question=question,
            api_key=st.session_state.api_key_input,
            on_progress=on_progress,
        )
        status.update(label="요약 완료", state="complete")
    st.session_state.summary = summary.text
    return summary.text


def handle_request(message: str) -> None:
    st.session_state.messages.append({"role": "user", "content": message})
    if not has_textbook():
        st.session_state.messages.append({"role": "assistant", "content": NEED_PDF})
        return

    result = st.session_state.result
    intent = classify(message)
    if intent == "read":
        st.session_state.speak_text = result.text
        st.session_state.speak_label = "교재 전체"
        st.session_state.audio_bytes = prepare_audio(result.text)
        reply = "아래에서 바로 재생됩니다. 재생이 안 되면 오디오의 재생 버튼을 누르세요."
    elif intent == "read_summary":
        text = st.session_state.summary or run_summary(focus_question(message))
        st.session_state.speak_text = text
        st.session_state.speak_label = "핵심 요약"
        st.session_state.audio_bytes = prepare_audio(text)
        reply = "요약 음성이 아래에 있습니다. 재생이 안 되면 오디오의 재생 버튼을 누르세요."
    elif intent == "quiz":
        with st.status(":shimmer[퀴즈를 만드는 중]", expanded=False) as status:
            quiz = make_quiz(
                result.text,
                summary=st.session_state.get("summary"),
                question=focus_question(message),
                api_key=st.session_state.api_key_input,
            )
            status.update(label="퀴즈 준비 완료", state="complete")
        st.session_state.quiz = quiz
        st.session_state.quiz_grade = None
        st.session_state.quiz_nonce = int(st.session_state.get("quiz_nonce") or 0) + 1
        how = "xAI가 출제" if quiz.source == "llm" else "본문 핵심 단어를 가려 출제"
        reply = (
            f"**{quiz.scope_label}** 범위로 객관식 3문항, 주관식 2문항을 {how}했습니다. "
            "아래에서 답을 고르거나 적은 뒤 **제출하기**를 누르세요."
        )
    else:
        run_summary(focus_question(message))
        reply = "요약을 아래 **요약본**에 저장해 두었습니다. 다른 기능을 써도 사라지지 않습니다."
    st.session_state.messages.append({"role": "assistant", "content": reply})


init_session()

st.title("교재 공부 도우미")
st.caption(
    "PDF를 올리면 텍스트를 추출합니다. 긴 교재는 2,000~3,000자씩 나눠 요약한 뒤 "
    "대단원/소단원으로 합칩니다. ‘3단원만 요약’, ‘퀴즈 만들어줘’처럼 말할 수 있습니다."
)

with st.sidebar:
    st.header("설정")
    st.text_input(
        "요약용 API 키 (선택)",
        type="password",
        key="api_key_input",
        help="있으면 교재 전체를 더 정확하게 요약합니다. 없으면 교재 문장에서 핵심을 골라 정리합니다. 환경 변수 XAI_API_KEY, .env, 또는 secrets 도 사용합니다.",
    )
    st.caption("키는 이 컴퓨터에서만 쓰이며, 입력값은 파일로 저장하지 않습니다.")

up_col, sample_col = st.columns([3, 1], vertical_alignment="bottom")
with up_col:
    uploaded = st.file_uploader("학생 교재 PDF 파일", type=["pdf"], key="textbook_pdf")
with sample_col:
    if SAMPLE_PDF.exists() and st.button("샘플 교재로 시험하기", width="stretch"):
        try:
            load_textbook(SAMPLE_PDF.read_bytes())
        except Exception as exc:
            st.session_state.result = None
            st.warning(f"PDF를 읽지 못했습니다: {exc}")
        else:
            st.rerun()

if uploaded is not None:
    try:
        load_textbook(uploaded.getvalue())
    except Exception as exc:
        st.session_state.result = None
        st.warning(f"PDF를 읽지 못했습니다: {exc}")

result = st.session_state.result

if not has_textbook():
    st.info(NEED_PDF)
elif result is not None:
    if not result.text:
        st.warning(
            "추출된 텍스트가 없습니다. 사진으로 찍은 스캔본이거나 이미지 PDF일 수 있습니다. "
            "글자가 선택되는 디지털 PDF인지 확인해 주세요."
        )
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("총 글자 수", f"{result.char_count:,}")
        col2.metric("공백 제외 글자 수", f"{result.char_count_no_space:,}")
        col3.metric("페이지 수", f"{result.page_count:,}")
        if uploaded is not None:
            st.download_button(
                label="추출 텍스트 저장 (.txt)",
                data=result.text.encode("utf-8"),
                file_name=f"{uploaded.name.rsplit('.', 1)[0]}_추출.txt",
                mime="text/plain; charset=utf-8",
            )

st.subheader("공부하기")
with st.container(horizontal=True):
    if st.button("전체 요약", icon=":material/summarize:", width="stretch"):
        handle_request("전체 요약")
        st.rerun()
    if st.button("퀴즈 만들기", icon=":material/quiz:", width="stretch"):
        handle_request("퀴즈 만들어줘")
        st.rerun()
    if st.button("교재 읽어주기", icon=":material/volume_up:", width="stretch"):
        handle_request("읽어줘")
        st.rerun()
    if st.button("요약 읽어주기", icon=":material/record_voice_over:", width="stretch"):
        handle_request("요약 읽어줘")
        st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input(
    "예: 전체 요약 / 3단원만 요약 / 퀴즈 만들어줘 / 시험지 뽑아줘 / 읽어줘",
    submit_mode="disable",
)
if prompt:
    handle_request(prompt)
    st.rerun()

if st.session_state.summary:
    with st.expander("요약본", expanded=True):
        st.markdown(st.session_state.summary)

quiz = st.session_state.quiz
if quiz:
    st.subheader("학습 퀴즈")
    st.caption(f"범위: {quiz.scope_label} · 객관식 3 · 주관식 2")
    grade = st.session_state.quiz_grade
    nonce = st.session_state.quiz_nonce
    if grade is None:
        with st.form("학습_퀴즈"):
            mc_answers: list[int | None] = []
            for i, question in enumerate(quiz.multiple_choice, start=1):
                st.markdown(f"**객관식 {i}.**")
                picked = st.radio(
                    question.prompt,
                    question.choices,
                    index=None,
                    key=f"quiz_mc_{nonce}_{i}",
                    persist_state="page",
                )
                if picked in question.choices:
                    mc_answers.append(question.choices.index(picked))
                else:
                    mc_answers.append(None)
            short_answers: list[str] = []
            for i, question in enumerate(quiz.short_answer, start=1):
                short_answers.append(
                    st.text_input(
                        f"주관식 {i}. {question.prompt}",
                        key=f"quiz_sa_{nonce}_{i}",
                        persist_state="page",
                    )
                )
            submitted = st.form_submit_button(
                "제출하기",
                type="primary",
                icon=":material/check:",
                width="stretch",
            )
        if submitted:
            st.session_state.quiz_grade = grade_quiz(quiz, mc_answers, short_answers)
            st.rerun()
    else:
        st.metric("점수", f"{grade.correct}/{grade.total}")
        if grade.correct == grade.total:
            st.success("전부 맞았어요. 핵심을 잘 기억하고 있네요.")
        elif grade.correct >= 3:
            st.info("잘했어요. 틀린 문항 해설만 다시 읽어 보세요.")
        else:
            st.warning("아직 헷갈리는 부분이 있어요. 해설을 보고 교재를 한 번 더 읽어 보세요.")
        for i, item in enumerate(grade.items, start=1):
            with st.container(border=True):
                if item.is_correct:
                    st.markdown(f"**{item.kind} {i}.** :green-badge[정답]")
                else:
                    st.markdown(f"**{item.kind} {i}.** :red-badge[오답]")
                st.markdown(item.prompt)
                st.markdown(f"내 답: {item.given}")
                if not item.is_correct:
                    st.markdown(f"정답: **{item.correct_answer}**")
                st.markdown(item.explanation)
        if st.button("새 퀴즈", icon=":material/refresh:"):
            handle_request("퀴즈 만들어줘")
            st.rerun()

if st.session_state.speak_text:
    st.subheader("읽어주기")
    render_player(
        st.session_state.speak_text,
        st.session_state.speak_label or "읽어주기",
        st.session_state.get("audio_bytes"),
    )

if has_textbook() and result is not None:
    with st.expander("추출된 텍스트", expanded=not st.session_state.messages):
        st.text_area(
            "전체 텍스트",
            value=result.text,
            height=360,
            label_visibility="collapsed",
        )
    with st.expander("페이지별 보기"):
        for index, page_text in enumerate(result.pages, start=1):
            st.markdown(f"**{index}쪽** · {len(page_text):,}자")
            st.text(page_text if page_text else "(이 페이지에서 글자를 찾지 못했습니다)")
