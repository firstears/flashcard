# 로컬 녹음 전사 → Obsidian (Mac용)

세컨드브레인 노트(젠스파크)로 녹음한 음성을 **내 Mac에서 무료로 글자로 바꾸고**,
Obsidian 보관함에 노트로 저장합니다. 녹음 날짜의 일일 노트(`YYYY-MM-DD_LifeLog.md`)에는 덮어쓰지 않고 덧붙입니다.

## 전체 흐름

```
세컨드브레인 노트로 녹음 → 젠스파크 앱에 자동 저장
→ (사용자) 앱에서 메모 열기 → 오른쪽 위 다운로드 아이콘 → 오디오 → MP3 → 내보내기
→ 공유 목록에서 Google Drive 의 "전사받는곳" 폴더 선택
→ Mac 의 Google Drive 가 자동 동기화
→ 이 프로그램이 전사 → Obsidian 에 저장
```

## 먼저 할 일 (젠스파크 앱, 1분)

1. 세컨드브레인 노트 설정에서 **"자동 변환"을 끕니다.**
   켜져 있으면 모든 녹음이 월 300분 무료 한도를 자동으로 소모합니다.
2. 앱의 "전사" 버튼은 누르지 않습니다. (짧은 중요 메모에 한해 무료 한도 안에서 쓰는 것은 괜찮습니다.)

## Google Drive 준비 (최초 1회)

1. Google Drive 에 **"전사받는곳"** 폴더를 만듭니다.
2. Mac 의 Google Drive 데스크톱 앱에서 이 폴더를 **"미러링"(오프라인 사용 가능)** 으로 설정합니다.
   (기본값인 "스트리밍"은 파일을 필요할 때만 내려받아 프로그램이 읽기 불안정합니다.)
3. 폰에서 내보낼 때 공유 목록에 이 폴더가 보이도록, 폰의 Drive 앱에서 폴더에 한 번 파일을 올려 둡니다.

## 설치 (Mac, 최초 1회)

터미널을 열고 아래를 순서대로 실행합니다.

```bash
brew install ffmpeg          # 이미 있으면 생략
cd transcriber               # 이 폴더로 이동
bash install_mac.sh
```

끝나면 안내문이 나옵니다. 안내대로:

1. `open -e ~/.secondbrain-transcriber/config.yaml` 로 설정 파일을 열어 **inbox** 와 **vault** 경로를 고칩니다.
2. 점검: `cd ~/.secondbrain-transcriber/app && ~/.secondbrain-transcriber/venv/bin/python -m secondbrain_tx doctor --deep`
   - 처음 한 번은 전사 모델(약 1.5GB)을 내려받습니다.
   - `[확인필요]` 줄이 있으면 그 아래 안내를 따릅니다. 결과 화면을 저에게 보여 주셔도 됩니다.
3. 시험: MP3 하나로 직접 전사해 봅니다.
   `~/.secondbrain-transcriber/venv/bin/python -m secondbrain_tx transcribe ~/Downloads/시험.mp3`
4. 문제가 없으면 자동 실행을 켭니다. (Mac 을 켜면 항상 백그라운드로 동작)
   `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.secondbrain.transcriber.plist`

> Drive 나 Obsidian 폴더 접근 허가 창이 뜨면 **허용**을 누릅니다. 그래도 읽기 실패가 나오면
> 시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한에 터미널을 추가합니다.

## 평소 사용

- 녹음 → 앱에서 MP3 내보내기 → Drive "전사받는곳" 선택. 이게 전부입니다.
- 파일 이름에 `[수업]`, `[회의]`, `[설교]`, `[논문]` 을 앞에 붙이면 노트의 `type` 에 기록됩니다.
- 처리된 파일은 "전사받는곳/_done" 으로 옮겨집니다. 같은 파일을 또 올려도 중복 처리하지 않습니다.
- 현황: `python -m secondbrain_tx status` / 실패 재시도: `python -m secondbrain_tx retry`
- 로그: `~/.secondbrain-transcriber/transcriber.log`

## 정확도 높이기

- `~/.secondbrain-transcriber/glossary.txt` 에 자주 틀리는 전문 용어, 인명, 지명을 한 줄에 하나씩 적습니다.
- `~/.secondbrain-transcriber/corrections.tsv` 에 `틀린말<탭>올바른말` 을 적으면 결과에서 자동으로 고칩니다.

## 결과물

- `보관함/전사/2026/2026-10-13_223939_제목.md` : 시각이 붙은 전사 원문 (`[00:12:30] ...`)
- `보관함/Daily/2026-10-13_LifeLog.md` : 그날 일일 노트에 `### 22:39 · 제목` 블록이 덧붙음

## 아직 포함되지 않은 것

요약, 마인드맵, 액션 아이템, 용도별(수업/설교/논문) 정리, Notion 연동은 다음 단계입니다.
이 단계는 "무료 전사 + 안전한 저장"까지입니다.

## 개발자용

```bash
pip install -r requirements.txt pytest
pytest
```
