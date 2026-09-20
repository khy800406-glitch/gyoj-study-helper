#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=""
if [[ -x /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 ]]; then
  PYTHON=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3
else
  PYTHON="$(command -v python3 || true)"
fi

if [[ -z "$PYTHON" ]]; then
  echo "Python 3가 없습니다. https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행하세요."
  exit 1
fi

echo "Python: $PYTHON ($("$PYTHON" --version))"
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo
echo "설치가 끝났습니다. 실행.command 를 더블클릭하세요."
