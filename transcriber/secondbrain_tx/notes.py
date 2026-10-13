from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .config import Config

_RECORD_TS = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ _T-]?(\d{2})(\d{2})(\d{2})")
_TYPE_TAG = re.compile(r"^\s*(?:\[(수업|회의|설교|논문)\]|(수업|회의|설교|논문)[_ -])\s*")
_BAD_CHARS = re.compile(r'[\\/:*?"<>|#^\[\]]')


def recorded_at(path: Path) -> datetime:
    """파일 이름의 날짜+시각(예: 2026-10-13 223939.mp3)을 녹음 시각으로 쓴다. 없으면 수정 시각."""
    m = _RECORD_TS.search(path.name)
    if m:
        try:
            return datetime(*(int(g) for g in m.groups()))
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def recording_type(stem: str) -> str:
    m = _TYPE_TAG.match(stem)
    return (m.group(1) or m.group(2)) if m else "미분류"


def clean_title(stem: str) -> str:
    """파일 이름에서 날짜시각과 유형 표시를 뺀 나머지. 없으면 빈 문자열."""
    text = _TYPE_TAG.sub("", stem)
    text = _RECORD_TS.sub("", text)
    text = unicodedata.normalize("NFC", _BAD_CHARS.sub("", text)).strip(" _-.")
    return text


def hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_transcript_note(
    cfg: Config,
    src: Path,
    sha: str,
    rec: datetime,
    duration: float,
    paragraphs: list[tuple[float, str]],
    engine_name: str,
    model: str,
) -> tuple[Path, str]:
    """전사 노트를 보관함에 저장한다. 반환: (보관함 기준 상대 경로, 제목)."""
    stem = unicodedata.normalize("NFC", src.stem)
    rtype = recording_type(stem)
    extra = clean_title(stem)
    title = extra or f"녹음 {rec:%Y-%m-%d %H:%M}"
    name = f"{rec:%Y-%m-%d_%H%M%S}" + (f"_{extra}" if extra else "")
    rel = Path(cfg.transcript_dir) / f"{rec:%Y}" / f"{name}.md"
    full = cfg.vault_path / rel
    if full.exists() and f"sha: {sha[:8]}" not in full.read_text(encoding="utf-8"):
        rel = rel.with_name(f"{rel.stem}_{sha[:6]}.md")
        full = cfg.vault_path / rel

    body = "\n\n".join(f"[{hms(t)}] {text}" for t, text in paragraphs) or "(인식된 음성이 없습니다)"
    text = (
        "---\n"
        f"created: {rec:%Y-%m-%dT%H:%M:%S}\n"
        f"source: \"{src.name}\"\n"
        f"type: {rtype}\n"
        f"duration: \"{hms(duration)}\"\n"
        f"engine: {engine_name}\n"
        f"model: \"{model}\"\n"
        f"sha: {sha[:8]}\n"
        "tags: [전사]\n"
        "---\n"
        f"# {title}\n\n"
        "## 전사 원문\n\n"
        f"{body}\n"
    )
    _atomic_write(full, text)
    return rel, title


def append_daily(
    cfg: Config,
    rec: datetime,
    title: str,
    note_rel: Path,
    duration: float,
    paragraphs: list[tuple[float, str]],
    sha: str,
) -> Path:
    """녹음한 날짜의 데일리 노트(YYYY-MM-DD_LifeLog.md) 아래에 덧붙인다. 덮어쓰지 않는다."""
    daily = cfg.vault_path / cfg.daily_dir / f"{rec:%Y-%m-%d}_LifeLog.md"
    marker = f"<!-- tx:{sha[:8]} -->"
    daily.parent.mkdir(parents=True, exist_ok=True)
    if daily.exists() and marker in daily.read_text(encoding="utf-8"):
        return daily  # 이미 기록됨 (중복 방지)

    preview = paragraphs[0][1][:200] if paragraphs else "(인식된 음성이 없습니다)"
    link = note_rel.with_suffix("").as_posix()
    block = (
        f"\n### {rec:%H:%M} · {title}\n"
        f"- 길이 {hms(duration)} · [[{link}]]\n"
        f"> {preview}\n"
        f"{marker}\n"
    )
    if not daily.exists():
        header = f"---\ncreated: {rec:%Y-%m-%d}\ntags: [LifeLog]\n---\n# {rec:%Y-%m-%d} LifeLog\n"
        with open(daily, "x", encoding="utf-8") as fh:
            fh.write(header)
    with open(daily, "a", encoding="utf-8") as fh:
        fh.write(block)
    return daily
