"""브라우저에서 한국어로 교재를 읽어 준다."""

from __future__ import annotations

import json

import streamlit as st


def render_player(text: str, label: str) -> None:
    if not text.strip():
        return
    payload = json.dumps(text, ensure_ascii=False)
    title = json.dumps(label or "읽어주기", ensure_ascii=False)
    st.iframe(
        f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }}
  .bar {{
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    padding: 8px 4px;
  }}
  button {{
    border: 1px solid #ccc; background: #fff; border-radius: 8px;
    padding: 6px 12px; cursor: pointer;
  }}
  button:hover {{ background: #f3f3f3; }}
  .label {{ color: #444; font-size: 13px; }}
  #status {{ color: #666; font-size: 12px; }}
</style>
</head>
<body>
  <div class="bar">
    <span class="label" id="title"></span>
    <button id="play">읽기</button>
    <button id="pause">일시정지</button>
    <button id="stop">정지</button>
    <label class="label">속도
      <input id="rate" type="range" min="0.7" max="1.3" step="0.05" value="0.95" />
    </label>
    <span id="status">대기</span>
  </div>
<script>
const text = {payload};
const title = {title};
document.getElementById("title").textContent = title;

function chunks(src) {{
  const lines = src.replace(/\\r/g, "").split(/\\n+/);
  const out = [];
  let buf = "";
  for (const line of lines) {{
    const piece = line.trim();
    if (!piece) continue;
    if ((buf + " " + piece).length > 360) {{
      if (buf) out.push(buf);
      if (piece.length > 360) {{
        for (let i = 0; i < piece.length; i += 360) out.push(piece.slice(i, i + 360));
        buf = "";
      }} else {{
        buf = piece;
      }}
    }} else {{
      buf = buf ? buf + " " + piece : piece;
    }}
  }}
  if (buf) out.push(buf);
  return out.length ? out : [src];
}}

function koVoice() {{
  const voices = window.speechSynthesis.getVoices();
  return voices.find(v => v.lang && v.lang.toLowerCase().startsWith("ko")) || null;
}}

let queue = [];
let idx = 0;
let paused = false;

function speakNext() {{
  if (paused) return;
  if (idx >= queue.length) {{
    document.getElementById("status").textContent = "끝";
    return;
  }}
  const u = new SpeechSynthesisUtterance(queue[idx]);
  const voice = koVoice();
  if (voice) u.voice = voice;
  u.lang = "ko-KR";
  u.rate = parseFloat(document.getElementById("rate").value);
  u.onend = () => {{ idx += 1; speakNext(); }};
  u.onerror = () => {{ idx += 1; speakNext(); }};
  document.getElementById("status").textContent = "읽는 중 " + (idx + 1) + "/" + queue.length;
  window.speechSynthesis.speak(u);
}}

document.getElementById("play").onclick = () => {{
  window.speechSynthesis.cancel();
  paused = false;
  queue = chunks(text);
  idx = 0;
  const start = () => speakNext();
  if (window.speechSynthesis.getVoices().length === 0) {{
    window.speechSynthesis.onvoiceschanged = start;
  }}
  start();
}};
document.getElementById("pause").onclick = () => {{
  if (window.speechSynthesis.speaking && !window.speechSynthesis.paused) {{
    paused = true;
    window.speechSynthesis.pause();
    document.getElementById("status").textContent = "일시정지";
  }} else if (window.speechSynthesis.paused) {{
    paused = false;
    window.speechSynthesis.resume();
    document.getElementById("status").textContent = "읽는 중";
  }}
}};
document.getElementById("stop").onclick = () => {{
  paused = true;
  window.speechSynthesis.cancel();
  document.getElementById("status").textContent = "정지";
}};
</script>
</body>
</html>
""",
        height=72,
        width="stretch",
    )
