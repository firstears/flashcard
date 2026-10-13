from __future__ import annotations

import unicodedata
from pathlib import Path

from .stt import Segment

# Whisper 의 initial_prompt 는 약 224 토큰까지만 유효하므로 글자 수를 제한한다.
PROMPT_MAX_CHARS = 350


def load_glossary_prompt(path: Path) -> str:
    """glossary.txt (한 줄에 용어 하나, # 로 시작하면 주석) -> 전사용 힌트 문장."""
    if not path.exists():
        return ""
    terms: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = unicodedata.normalize("NFC", line.strip())
        if line and not line.startswith("#"):
            terms.append(line)
    prompt = ""
    for term in terms:
        candidate = f"{prompt}, {term}" if prompt else term
        if len(candidate) > PROMPT_MAX_CHARS:
            break
        prompt = candidate
    return prompt


def load_corrections(path: Path) -> list[tuple[str, str]]:
    """corrections.tsv (틀린말<TAB>올바른말) -> 목록."""
    if not path.exists():
        return []
    pairs: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#") or "\t" not in line:
            continue
        wrong, right = line.split("\t", 1)
        wrong, right = unicodedata.normalize("NFC", wrong.strip()), right.strip()
        if wrong:
            pairs.append((wrong, right))
    return pairs


def apply_corrections(segments: list[Segment], pairs: list[tuple[str, str]]) -> list[Segment]:
    if not pairs:
        return segments
    out = []
    for seg in segments:
        text = seg.text
        for wrong, right in pairs:
            text = text.replace(wrong, right)
        out.append(Segment(seg.start, seg.end, text))
    return out


def drop_repeats(segments: list[Segment], max_repeat: int = 2) -> list[Segment]:
    """같은 문장이 3번 이상 연속되면 뒤쪽을 버린다 (Whisper 의 반복 환각 방지)."""
    out: list[Segment] = []
    run = 0
    last = None
    for seg in segments:
        norm = "".join(seg.text.split())
        if norm == last:
            run += 1
        else:
            run, last = 1, norm
        if run <= max_repeat:
            out.append(seg)
    return out


def group_paragraphs(
    segments: list[Segment], gap: float = 2.0, max_chars: int = 350
) -> list[tuple[float, str]]:
    """문장 조각을 문단으로 묶는다. 반환: (문단 시작 시각, 문단 텍스트)."""
    paras: list[tuple[float, str]] = []
    cur_start = 0.0
    cur_text = ""
    prev_end = None
    for seg in segments:
        new_para = prev_end is not None and (seg.start - prev_end > gap or len(cur_text) > max_chars)
        if new_para and cur_text:
            paras.append((cur_start, cur_text.strip()))
            cur_text = ""
        if not cur_text:
            cur_start = seg.start
        cur_text += (" " if cur_text else "") + seg.text
        prev_end = seg.end
    if cur_text.strip():
        paras.append((cur_start, cur_text.strip()))
    return paras
