from __future__ import annotations

import re
import subprocess
from pathlib import Path


class AudioError(Exception):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except FileNotFoundError as exc:
        raise AudioError(
            f"{cmd[0]} 을(를) 찾을 수 없습니다. 터미널에서 'brew install ffmpeg' 를 실행하십시오."
        ) from exc


def probe_duration(path: Path) -> float:
    res = _run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ]
    )
    try:
        return float(res.stdout.strip())
    except ValueError as exc:
        raise AudioError(f"오디오 길이를 읽을 수 없습니다 (손상되었거나 지원하지 않는 파일): {path.name}") from exc


_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def detect_silences(path: Path, noise_db: int = -35, min_len: float = 0.6) -> list[tuple[float, float]]:
    res = _run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-vn",
            "-af", f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-",
        ]
    )
    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in res.stderr.splitlines():
        m = _SIL_START.search(line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = _SIL_END.search(line)
        if m and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    return silences


def plan_chunks(
    duration: float,
    silences: list[tuple[float, float]],
    target: float,
    window: float = 90.0,
) -> list[tuple[float, float]]:
    """target 초 단위로 나누되, 가능하면 무음 구간 한가운데에서 자른다 (단어 잘림 방지)."""
    if duration <= target * 1.25:
        return [(0.0, duration)]
    mids = [(s + e) / 2 for s, e in silences]
    chunks: list[tuple[float, float]] = []
    cursor = 0.0
    while duration - cursor > target * 1.25:
        ideal = cursor + target
        near = [m for m in mids if abs(m - ideal) <= window and m > cursor + target / 2]
        cut = min(near, key=lambda m: abs(m - ideal)) if near else ideal
        chunks.append((cursor, cut))
        cursor = cut
    chunks.append((cursor, duration))
    return chunks


def extract_wav(src: Path, start: float, end: float, out: Path) -> None:
    res = _run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{start:.3f}",
            "-t", f"{end - start:.3f}", "-i", str(src), "-vn",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out),
        ]
    )
    if res.returncode != 0 or not out.exists():
        raise AudioError(f"오디오 변환 실패: {res.stderr.strip()[:300]}")
