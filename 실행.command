#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/streamlit ]]; then
  echo "먼저 설치.command 를 실행하세요."
  exit 1
fi

echo "브라우저에서 교재 PDF 추출 화면이 열립니다."
exec .venv/bin/streamlit run app.py --server.headless false
