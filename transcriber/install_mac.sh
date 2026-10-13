#!/bin/bash
# Mac 설치 스크립트: 가상환경 생성, 라이브러리 설치, 자동 실행(launchd) 등록.
# 사용법: 터미널에서  bash install_mac.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.secondbrain-transcriber"
VENV="$APP_DIR/venv"
PLIST="$HOME/Library/LaunchAgents/com.secondbrain.transcriber.plist"
PY="${PYTHON:-python3}"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg 가 없습니다. 먼저 터미널에서 다음을 실행하십시오:  brew install ffmpeg"
  exit 1
fi

mkdir -p "$APP_DIR/app"
# 프로그램을 고정 위치로 복사한다 (원래 폴더를 옮기거나 지워도 계속 동작하도록).
rm -rf "$APP_DIR/app/secondbrain_tx"
cp -R "$HERE/secondbrain_tx" "$APP_DIR/app/secondbrain_tx"

"$PY" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$HERE/requirements.txt"
if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  "$VENV/bin/pip" install --quiet -r "$HERE/requirements-mac.txt"
fi

[ -f "$APP_DIR/config.yaml" ] || cp "$HERE/config.example.yaml" "$APP_DIR/config.yaml"
[ -f "$APP_DIR/glossary.txt" ] || cp "$HERE/glossary.example.txt" "$APP_DIR/glossary.txt"
[ -f "$APP_DIR/corrections.tsv" ] || cp "$HERE/corrections.example.tsv" "$APP_DIR/corrections.tsv"

mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__PYTHON__|$VENV/bin/python|g" \
    -e "s|__WORKDIR__|$APP_DIR/app|g" \
    -e "s|__LOGDIR__|$APP_DIR|g" \
    "$HERE/launchd/com.secondbrain.transcriber.plist.template" > "$PLIST"

echo
echo "설치가 끝났습니다. 아직 자동 실행은 켜지 않았습니다."
echo "1) 설정 파일을 여십시오:  open -e \"$APP_DIR/config.yaml\""
echo "   inbox 와 vault 경로를 내 환경에 맞게 고치십시오."
echo "2) 점검:  cd \"$APP_DIR/app\" && \"$VENV/bin/python\" -m secondbrain_tx doctor --deep"
echo "3) 문제가 없으면 자동 실행 켜기:"
echo "   launchctl bootstrap gui/\$(id -u) \"$PLIST\""
echo "   끄기:  launchctl bootout gui/\$(id -u) \"$PLIST\""
