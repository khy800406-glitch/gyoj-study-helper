"""교재 읽어주기: 실제 음성 파일 재생 + 브라우저 읽기."""

from __future__ import annotations

import io
import json
import re
from html import escape

import streamlit as st


_MAX_CHARS = 1_800


def _clip(text: str) -> str:
    clip = re.sub(r"\s+", " ", text).strip()
    if len(clip) <= _MAX_CHARS:
        return clip
    head = clip[:_MAX_CHARS]
    cut = max(head.rfind(". "), head.rfind("다. "), head.rfind("요. "), head.rfind(" "))
    return head[: cut + 1].strip() if cut > 400 else head


@st.cache_data(show_spinner=False, ttl=3600, max_entries=16)
def make_speech(text: str) -> bytes:
    from gtts import gTTS

    clip = _clip(text)
    if not clip:
        raise ValueError("읽을 글이 없습니다.")
    buf = io.BytesIO()
    gTTS(text=clip, lang="ko").write_to_fp(buf)
    audio = buf.getvalue()
    if len(audio) < 200:
        raise RuntimeError("음성 파일을 만들지 못했습니다.")
    return audio


def render_player(text: str, label: str, audio: bytes | None) -> None:
    if not text.strip():
        return
    st.caption(label)
    if audio:
        st.audio(audio, format="audio/mp3", autoplay=False)
        if len(text) > _MAX_CHARS:
            st.caption("앞에서부터 읽습니다. 아래 추출된 텍스트에서 나머지를 볼 수 있습니다.")
        return
    st.info("재생 막대가 아래에 있습니다. 재생 버튼을 누르세요.")

    payload = json.dumps(_clip(text), ensure_ascii=False)
    st.html(
        f"""
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-family:sans-serif;">
  <span>{escape(label or "읽어주기")}</span>
  <button id="play">읽기</button>
  <button id="pause">일시정지</button>
  <button id="stop">정지</button>
  <span id="status">대기</span>
</div>
<script>
const text = {payload};
function speak() {{
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "ko-KR";
  const v = window.speechSynthesis.getVoices().find(x => (x.lang||"").toLowerCase().startsWith("ko"));
  if (v) u.voice = v;
  u.onend = () => document.getElementById("status").textContent = "끝";
  document.getElementById("status").textContent = "읽는 중";
  window.speechSynthesis.speak(u);
}}
document.getElementById("play").onclick = speak;
document.getElementById("pause").onclick = () => {{
  if (window.speechSynthesis.paused) {{ window.speechSynthesis.resume(); }}
  else {{ window.speechSynthesis.pause(); }}
}};
document.getElementById("stop").onclick = () => {{
  window.speechSynthesis.cancel();
  document.getElementById("status").textContent = "정지";
}};
</script>
""",
        unsafe_allow_javascript=True,
    )
