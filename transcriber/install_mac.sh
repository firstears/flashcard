#!/bin/bash
# Mac 원클릭 설치기: 설치 -> 폴더 자동 탐지 -> 점검 -> 시험 전사 -> 자동 실행 등록.
# 사용법: 터미널에서 이 폴더로 이동한 뒤  bash install_mac.sh
# (macOS 기본 bash 3.2 에서도 동작하도록 단순하게 작성)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.secondbrain-transcriber"
VENV="$APP_DIR/venv"
PLIST="$HOME/Library/LaunchAgents/com.secondbrain.transcriber.plist"

say() { printf '\n== %s\n' "$1"; }

if [ ! -d "$HERE/secondbrain_tx" ]; then
  echo "secondbrain_tx 폴더가 보이지 않습니다. install_mac.sh 가 들어 있는 transcriber 폴더에서 실행하십시오."
  exit 1
fi

say "1/6 Homebrew 확인"
if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$b" ]; then eval "$("$b" shellenv)"; break; fi
  done
fi
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew 가 없습니다. https://brew.sh 의 설치 명령을 먼저 실행한 뒤, 이 스크립트를 다시 실행하십시오."
  exit 1
fi

say "2/6 ffmpeg 와 파이썬 설치 (이미 있으면 건너뜀)"
brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
PY="$(brew --prefix python@3.12)/bin/python3.12"
if [ ! -x "$PY" ]; then
  echo "python3.12 를 찾을 수 없습니다: $PY"
  exit 1
fi

say "3/6 프로그램 복사와 라이브러리 설치 (몇 분 걸립니다)"
mkdir -p "$APP_DIR/app"
rm -rf "$APP_DIR/app/secondbrain_tx"
cp -R "$HERE/secondbrain_tx" "$APP_DIR/app/secondbrain_tx"
find "$APP_DIR/app" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$HERE/requirements.txt"
if [ "$(uname -m)" = "arm64" ]; then
  "$VENV/bin/pip" install --quiet -r "$HERE/requirements-mac.txt"
fi

say "4/6 설정: Google Drive 폴더와 Obsidian 보관함을 자동으로 찾습니다"
[ -f "$APP_DIR/config.yaml" ] || cp "$HERE/config.example.yaml" "$APP_DIR/config.yaml"
[ -f "$APP_DIR/glossary.txt" ] || cp "$HERE/glossary.example.txt" "$APP_DIR/glossary.txt"
[ -f "$APP_DIR/corrections.tsv" ] || cp "$HERE/corrections.example.tsv" "$APP_DIR/corrections.tsv"
cd "$APP_DIR/app"
"$VENV/bin/python" -m secondbrain_tx autoconfig || true

say "5/6 점검과 시험 전사 (처음 한 번은 모델 약 1.5GB 를 내려받아 시간이 걸립니다)"
if ! "$VENV/bin/python" -m secondbrain_tx doctor --deep; then
  echo
  echo "[확인필요] 위 점검 결과를 그대로 복사해서 Claude 에게 보여 주십시오. 고쳐 드리겠습니다."
  exit 1
fi
echo
echo "받은편지함에 있는 파일을 한 번 처리해 봅니다..."
"$VENV/bin/python" -m secondbrain_tx once || true
"$VENV/bin/python" -m secondbrain_tx status || true

say "6/6 자동 실행 등록"
mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__PYTHON__|$VENV/bin/python|g" \
    -e "s|__WORKDIR__|$APP_DIR/app|g" \
    -e "s|__LOGDIR__|$APP_DIR|g" \
    "$HERE/launchd/com.secondbrain.transcriber.plist.template" > "$PLIST"
ans="n"
read -r -p "Mac 을 켤 때마다 자동으로 감시하도록 켤까요? [y/N] " ans || ans="n"
if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "자동 실행을 켰습니다. 끄려면:  launchctl bootout gui/\$(id -u) \"$PLIST\""
else
  echo "나중에 켜려면:  launchctl bootstrap gui/\$(id -u) \"$PLIST\""
fi

echo
echo "완료되었습니다. 로그: $APP_DIR/transcriber.log"
echo "설정 파일: $APP_DIR/config.yaml  (open -e 로 열 수 있습니다)"
