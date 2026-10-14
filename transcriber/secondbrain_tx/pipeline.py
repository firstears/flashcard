from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable

from . import audio, notes, postprocess
from .config import Config
from .state import State, file_sha256
from .stt import Segment
from .watcher import InboxScanner

log = logging.getLogger("secondbrain_tx")


def process_file(cfg: Config, engine, path: Path, sha: str) -> Path:
    """오디오 한 개를 전사해 노트로 저장한다. 반환: 전사 노트의 보관함 상대 경로."""
    rec = notes.recorded_at(path, audio.probe_creation_time(path))
    duration = audio.probe_duration(path)
    target = max(60.0, cfg.chunk_minutes * 60)
    # 2분 이하의 짧은 녹음은 통째로 처리하고, 긴 녹음은 긴 무음을 건너뛰고 말이 있는 구간만 전사한다.
    if duration > 120:
        silences = audio.detect_silences(path, cfg.silence_db)
        chunks = audio.plan_speech_chunks(duration, silences, target, cfg.skip_silence_seconds)
    else:
        chunks = [(0.0, duration)]
    active = sum(end - start for start, end in chunks)
    prompt = postprocess.load_glossary_prompt(cfg.glossary_path)
    corrections = postprocess.load_corrections(cfg.corrections_path)
    log.info(
        "전사 시작: %s (전체 %s, 말이 있는 구간 %s, %d개 구간)",
        path.name, notes.hms(duration), notes.hms(active), len(chunks),
    )

    segments: list[Segment] = []
    tmp_root = cfg.state_path / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tmp_root) as tmp:
        for i, (start, end) in enumerate(chunks, 1):
            wav = Path(tmp) / f"chunk{i}.wav"
            audio.extract_wav(path, start, end, wav)
            part = engine.transcribe(wav, cfg.language, prompt)
            segments += [Segment(s.start + start, s.end + start, s.text) for s in part]
            wav.unlink(missing_ok=True)
            log.info("  구간 %d/%d 완료", i, len(chunks))

    segments = postprocess.drop_repeats(segments)
    segments = postprocess.apply_corrections(segments, corrections)
    paragraphs = postprocess.group_paragraphs(segments)
    model = getattr(engine, "model", None) or getattr(engine, "model_name", "") or ""
    note_rel, title = notes.write_transcript_note(
        cfg, path, sha, rec, duration, paragraphs, engine.name, model, active
    )
    notes.append_daily(cfg, rec, title, note_rel, duration, paragraphs, sha)
    log.info("저장 완료: %s", note_rel)
    return note_rel


def _move_done(cfg: Config, path: Path) -> Path:
    dest_dir = cfg.inbox_path / "_done" / time.strftime("%Y-%m")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    n = 1
    while dest.exists():
        dest = dest_dir / f"{path.stem}_{n}{path.suffix}"
        n += 1
    shutil.move(str(path), str(dest))
    return dest


def ingest(cfg: Config, state: State, scanner: InboxScanner) -> int:
    """안정된 새 파일을 작업 목록에 등록한다. 반환: 새로 등록한 개수."""
    added = 0
    for path in scanner.scan():
        try:
            sha = file_sha256(path)
        except OSError as exc:
            log.warning("읽을 수 없음, 다음에 다시 시도: %s (%s)", path.name, exc)
            continue
        if state.add(sha, path):
            log.info("새 파일 등록: %s", path.name)
            added += 1
        else:
            row = state.get(sha)
            log.info("이미 처리했거나 대기 중인 파일(중복): %s [%s]", path.name, row["status"])
            if row["status"] == "done" and cfg.after_done == "move":
                try:
                    _move_done(cfg, path)
                    continue
                except OSError:
                    pass
        scanner.mark_handled(path)
    return added


def drain(cfg: Config, state: State, engine_factory: Callable[[], object]) -> int:
    """대기 중인 작업을 하나씩 순서대로 처리한다. 반환: 성공한 개수."""
    engine = None
    done = 0
    while True:
        job = state.next_queued(cfg.max_attempts)
        if job is None:
            return done
        sha, path = job["sha256"], Path(job["path"])
        state.start(sha)
        try:
            if not path.exists():
                raise FileNotFoundError(f"파일이 사라졌습니다: {path}")
            if engine is None:
                engine = engine_factory()
            note_rel = process_file(cfg, engine, path, sha)
            state.finish(sha, str(note_rel))
            done += 1
            if cfg.after_done == "move" and path.is_relative_to(cfg.inbox_path):
                state.update_path(sha, _move_done(cfg, path))
        except Exception as exc:  # noqa: BLE001 - 한 파일의 실패가 전체를 멈추면 안 된다
            log.error("처리 실패(%s): %s", path.name, exc)
            state.fail(sha, f"{type(exc).__name__}: {exc}", cfg.max_attempts)
