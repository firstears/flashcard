from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from secondbrain_tx import audio, notes, postprocess
from secondbrain_tx.config import Config
from secondbrain_tx.pipeline import drain, ingest
from secondbrain_tx.state import State
from secondbrain_tx.stt import Segment
from secondbrain_tx.watcher import InboxScanner, is_candidate

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 필요")


class FakeEngine:
    name = "fake"
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def transcribe(self, wav, language, prompt):
        self.calls += 1
        return [Segment(0.0, 1.0, "안녕하세요"), Segment(1.2, 2.0, "테스트입니다")]


def make_cfg(tmp_path: Path) -> Config:
    return Config(
        inbox=str(tmp_path / "inbox"),
        vault=str(tmp_path / "vault"),
        state_dir=str(tmp_path / "state"),
        stable_seconds=0,
        chunk_minutes=1,
    )


def make_audio(path: Path, tone: int = 40, gap: int = 3, repeat: int = 3) -> None:
    """tone 초 소리 + gap 초 무음을 repeat 번 이어 붙인 오디오를 만든다."""
    tmp = path.parent.parent / "work"  # 받은편지함 밖에 보조 파일을 둔다
    tmp.mkdir(exist_ok=True)
    tone_f, sil_f = tmp / "tone.wav", tmp / "sil.wav"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={tone}", str(tone_f)], check=True)
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
         f"anullsrc=r=44100:cl=mono", "-t", str(gap), str(sil_f)], check=True)
    inputs: list[str] = []
    for _ in range(repeat):
        inputs += ["-i", str(tone_f), "-i", str(sil_f)]
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", *inputs, "-filter_complex",
         f"concat=n={repeat * 2}:v=0:a=1", "-c:a", "libmp3lame", str(path)], check=True)


# ---------- 순수 로직 ----------

def test_recorded_at_and_type(tmp_path):
    f = tmp_path / "2026-10-13 223939.mp3"
    f.write_bytes(b"x")
    rec = notes.recorded_at(f)
    assert (rec.year, rec.month, rec.day, rec.hour, rec.minute, rec.second) == (2026, 10, 13, 22, 39, 39)
    assert notes.recording_type("[설교] 2026-10-13 223939 시편1편") == "설교"
    assert notes.recording_type("수업_2026-10-13 223939") == "수업"
    assert notes.recording_type("2026-10-13 223939") == "미분류"
    assert notes.clean_title("[설교] 2026-10-13 223939 시편1편") == "시편1편"
    assert notes.clean_title("2026-10-13 223939") == ""


def test_plan_chunks_snaps_to_silence():
    assert audio.plan_chunks(50, [], 60) == [(0.0, 50)]
    assert audio.plan_chunks(100, [(48, 52)], 50) == [(0.0, 50.0), (50.0, 100)]
    # 무음이 없으면 정해진 길이에서 자른다
    assert audio.plan_chunks(200, [], 60)[0] == (0.0, 60.0)
    # 구간은 빈틈없이 이어져야 한다
    chunks = audio.plan_chunks(500, [(58, 62), (118, 124)], 60)
    assert chunks[0][0] == 0.0 and chunks[-1][1] == 500
    assert all(a[1] == b[0] for a, b in zip(chunks, chunks[1:]))


def test_drop_repeats_and_paragraphs():
    segs = [Segment(i, i + 1, "같은 문장") for i in range(5)] + [Segment(6, 7, "다른 문장")]
    kept = postprocess.drop_repeats(segs)
    assert [s.text for s in kept] == ["같은 문장", "같은 문장", "다른 문장"]
    paras = postprocess.group_paragraphs(
        [Segment(0, 1, "가"), Segment(1.5, 2, "나"), Segment(10, 11, "다")]
    )
    assert paras == [(0, "가 나"), (10, "다")]


def test_glossary_and_corrections(tmp_path):
    g = tmp_path / "g.txt"
    g.write_text("# 주석\n칼뱅\n\n아우구스티누스\n", encoding="utf-8")
    assert postprocess.load_glossary_prompt(g) == "칼뱅, 아우구스티누스"
    g.write_text("\n".join("가" * 100 for _ in range(10)), encoding="utf-8")
    assert len(postprocess.load_glossary_prompt(g)) <= postprocess.PROMPT_MAX_CHARS
    c = tmp_path / "c.tsv"
    c.write_text("# x\n깔빈\t칼뱅\n", encoding="utf-8")
    pairs = postprocess.load_corrections(c)
    out = postprocess.apply_corrections([Segment(0, 1, "깔빈은")], pairs)
    assert out[0].text == "칼뱅은"


def test_is_candidate():
    assert is_candidate("a.mp3") and is_candidate("회의.M4A")
    assert not is_candidate("a.mp3.crdownload")
    assert not is_candidate(".hidden.mp3")
    assert not is_candidate("note.txt")


def test_scanner_waits_until_stable(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    now = {"t": 0.0}
    sc = InboxScanner(inbox, stable_seconds=15, clock=lambda: now["t"])
    f = inbox / "a.mp3"
    f.write_bytes(b"1234")
    assert sc.scan() == []  # 처음 본 파일
    now["t"] = 10
    assert sc.scan() == []  # 아직 15초 안 됨
    f.write_bytes(b"12345678")  # 전송 중 (크기 변화)
    now["t"] = 20
    assert sc.scan() == []  # 크기가 바뀌어 다시 대기
    now["t"] = 40
    assert sc.scan() == [f]
    sc.mark_handled(f)
    now["t"] = 60
    assert sc.scan() == []  # 처리한 파일은 다시 안 나옴
    (inbox / "_done").mkdir()
    (inbox / "_done" / "b.mp3").write_bytes(b"zz")
    now["t"] = 100
    assert sc.scan() == []  # _done 폴더는 무시


def test_state_dedupe_and_crash_recovery(tmp_path):
    db = tmp_path / "s.db"
    st = State(db)
    assert st.add("abc", Path("/x/a.mp3")) is True
    assert st.add("abc", Path("/y/copy.mp3")) is False
    st.start("abc")
    st.close()
    st2 = State(db)  # 비정상 종료 후 재시작
    assert st2.get("abc")["status"] == "queued"
    assert st2.next_queued(3)["sha256"] == "abc"


def test_append_daily_is_idempotent_and_never_overwrites(tmp_path):
    cfg = make_cfg(tmp_path)
    rec = notes.datetime(2026, 10, 13, 22, 39, 39)
    daily = cfg.vault_path / cfg.daily_dir / "2026-10-13_LifeLog.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 내가 쓴 내용\n", encoding="utf-8")
    paras = [(0.0, "첫 문단")]
    notes.append_daily(cfg, rec, "제목", Path("전사/2026/a.md"), 5, paras, "aaaaaaaa11")
    notes.append_daily(cfg, rec, "제목", Path("전사/2026/a.md"), 5, paras, "aaaaaaaa11")
    notes.append_daily(cfg, rec, "둘째", Path("전사/2026/b.md"), 7, paras, "bbbbbbbb22")
    text = daily.read_text(encoding="utf-8")
    assert text.startswith("# 내가 쓴 내용")
    assert text.count("<!-- tx:aaaaaaaa -->") == 1
    assert text.count("<!-- tx:bbbbbbbb -->") == 1
    assert "[[전사/2026/a]]" in text


# ---------- ffmpeg 가 필요한 통합 시험 ----------

@needs_ffmpeg
def test_end_to_end_chunking_and_notes(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.inbox_path.mkdir(parents=True)
    src = cfg.inbox_path / "[수업] 2026-10-13 223939 교회사.mp3"
    make_audio(src, tone=40, gap=3, repeat=3)  # 약 129초 -> 1분 단위로 나뉨
    (cfg.state_path).mkdir(parents=True)
    (cfg.state_path / "glossary.txt").write_text("칼뱅\n", encoding="utf-8")

    state = State(cfg.state_path / "state.db")
    scanner = InboxScanner(cfg.inbox_path, 0)
    ingest(cfg, state, scanner)
    assert ingest(cfg, state, scanner) == 1
    engine = FakeEngine()
    assert drain(cfg, state, lambda: engine) == 1
    assert engine.calls == 3  # 무음 구간에서 3개로 분할

    notes_dir = cfg.vault_path / "전사" / "2026"
    note = next(notes_dir.glob("*.md")).read_text(encoding="utf-8")
    assert "type: 수업" in note and "# 교회사" in note and "engine: fake" in note
    stamps = [int(h) * 3600 + int(m) * 60 + int(s) for h, m, s in re.findall(r"\[(\d\d):(\d\d):(\d\d)\]", note)]
    assert len(stamps) == 3 and stamps == sorted(stamps) and stamps[1] > 30
    daily = (cfg.vault_path / "Daily" / "2026-10-13_LifeLog.md").read_text(encoding="utf-8")
    assert "22:39 · 교회사" in daily

    # 처리한 파일은 _done 으로 이동하고, 같은 파일이 다시 와도 중복 처리하지 않는다
    assert not src.exists()
    assert any((cfg.inbox_path / "_done").rglob("*.mp3"))
    again = cfg.inbox_path / "복사본.mp3"
    shutil.copy(next((cfg.inbox_path / "_done").rglob("*.mp3")), again)
    ingest(cfg, state, scanner)
    ingest(cfg, state, scanner)
    assert drain(cfg, state, lambda: engine) == 0
    assert engine.calls == 3
    assert not again.exists()


@needs_ffmpeg
def test_failure_retries_then_marks_failed(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.inbox_path.mkdir(parents=True)
    bad = cfg.inbox_path / "깨진파일.mp3"
    bad.write_bytes(b"this is not audio" * 50)
    state = State(cfg.state_path / "state.db")
    scanner = InboxScanner(cfg.inbox_path, 0)
    ingest(cfg, state, scanner)
    ingest(cfg, state, scanner)
    assert drain(cfg, state, lambda: FakeEngine()) == 0
    row = state.recent(1)[0]
    assert row["status"] == "failed" and row["attempts"] == cfg.max_attempts
    assert "길이" in row["error"] or "오디오" in row["error"]
    assert state.retry_failed() == 1


# ---------- 긴 무음 건너뛰기, 녹음 시각 결정 ----------

def make_pattern(path: Path, pattern: list[tuple[str, int]], creation_time: str | None = None) -> None:
    """pattern: [("t", 초), ("s", 초), ...]  t=소리, s=무음."""
    work = path.parent.parent / "work"
    work.mkdir(exist_ok=True)
    inputs: list[str] = []
    for i, (kind, sec) in enumerate(pattern):
        src = (f"sine=frequency=440:duration={sec}" if kind == "t"
               else f"anullsrc=r=44100:cl=mono:d={sec}")
        inputs += ["-f", "lavfi", "-t", str(sec), "-i", src]
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", *inputs, "-filter_complex",
           f"concat=n={len(pattern)}:v=0:a=1", "-c:a", "libmp3lame"]
    if creation_time:
        cmd += ["-metadata", f"creation_time={creation_time}"]
    subprocess.run([*cmd, str(path)], check=True)


def test_plan_speech_chunks_skips_long_silence():
    # 46분 중 앞 30분은 무음, 말은 약 2분: 말이 있는 구간만 남는다
    silences = [(0.0, 1850.0), (1900.0, 1901.0), (1960.0, float("inf"))]
    chunks = audio.plan_speech_chunks(2778.0, silences, 1200.0)
    assert len(chunks) == 1
    start, end = chunks[0]
    assert 1849 <= start <= 1850 and 1960 <= end <= 1961
    # 전부 무음이면 처리할 구간이 없다
    assert audio.plan_speech_chunks(100.0, [(0.0, float("inf"))], 60.0) == []
    # 말이 두 덩어리면 두 구간
    two = audio.plan_speech_chunks(300.0, [(0.0, 50.0), (80.0, 200.0), (230.0, float("inf"))], 600.0)
    assert len(two) == 2


def test_recorded_at_priority(tmp_path):
    f = tmp_path / "AI 비서 일정 브리핑.mp3"
    f.write_bytes(b"x")
    tag = notes.datetime(2026, 10, 14, 8, 19, 0)
    assert notes.recorded_at(f, tag) == tag  # 이름에 시각이 없으면 메타데이터
    named = tmp_path / "2026-10-13 223939.mp3"
    named.write_bytes(b"x")
    assert notes.recorded_at(named, tag).day == 13  # 이름의 시각이 우선
    assert notes.recorded_at(f, None).year >= 2026  # 둘 다 없으면 수정 시각


@needs_ffmpeg
def test_probe_creation_time_reads_metadata(tmp_path):
    (tmp_path / "inbox").mkdir()
    f = tmp_path / "inbox" / "제목만있는파일.mp3"
    make_pattern(f, [("t", 2)], creation_time="2026-10-14T08:19:00Z")
    got = audio.probe_creation_time(f)
    expected = notes.datetime.fromisoformat("2026-10-14T08:19:00+00:00").astimezone().replace(tzinfo=None)
    assert got == expected


@needs_ffmpeg
def test_long_silence_is_skipped_and_title_used(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.inbox_path.mkdir(parents=True)
    src = cfg.inbox_path / "AI 비서 일정 브리핑.mp3"  # 이름에 날짜가 없는 젠스파크식 제목
    make_pattern(src, [("s", 60), ("t", 20), ("s", 60), ("t", 10)], creation_time="2026-10-14T08:19:00Z")
    state = State(cfg.state_path / "state.db")
    scanner = InboxScanner(cfg.inbox_path, 0)
    ingest(cfg, state, scanner)
    ingest(cfg, state, scanner)
    engine = FakeEngine()
    assert drain(cfg, state, lambda: engine) == 1
    assert engine.calls == 2  # 소리가 있는 두 덩어리만 전사
    note_path = next((cfg.vault_path / "전사").rglob("*.md"))
    note = note_path.read_text(encoding="utf-8")
    assert "# AI 비서 일정 브리핑" in note
    assert "speech_analyzed" in note
    stamps = re.findall(r"\[(\d\d):(\d\d):(\d\d)\]", note)
    assert int(stamps[0][1]) * 60 + int(stamps[0][2]) >= 59  # 첫 말은 약 60초 지점


# ---------- 자동 설정 ----------

def test_autoconfig_finds_drive_folder_and_vault(tmp_path, monkeypatch):
    import unicodedata
    from secondbrain_tx import autoconfig
    from secondbrain_tx.config import load_config

    home = tmp_path / "home"
    drive = home / "Library" / "CloudStorage" / "GoogleDrive-a@b.com" / "내 드라이브"
    # macOS 가 돌려줄 수 있는 자모 분리(NFD) 한글 이름으로 만든다
    (drive / unicodedata.normalize("NFD", "전사받는곳")).mkdir(parents=True)
    (drive / "Second Brain_test").mkdir()
    old = home / "Documents" / "오래된볼트" / ".obsidian"
    old.mkdir(parents=True)
    new = home / "Documents" / "작업" / "SecondBrain" / ".obsidian"
    new.mkdir(parents=True)
    import os, time
    os.utime(old, (time.time() - 99999, time.time() - 99999))

    inbox = autoconfig.find_inbox_candidates(home)
    assert [unicodedata.normalize("NFC", p.name) for p in inbox] == ["전사받는곳", "Second Brain_test"]
    vaults = autoconfig.find_vault_candidates(home)
    assert vaults[0].name == "SecondBrain" and len(vaults) == 2  # 최근 것이 앞

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        (Path(__file__).parent.parent / "config.example.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    autoconfig.update_config(cfg_file, inbox[0], vaults[0])
    cfg = load_config(cfg_file)
    assert Path(cfg.inbox) == inbox[0] and Path(cfg.vault) == vaults[0]
    assert cfg.language == "ko"  # 다른 설정은 그대로
    assert "# 복사해서" in cfg_file.read_text(encoding="utf-8")  # 주석 보존


def test_autoconfig_without_matches_changes_nothing(tmp_path):
    from secondbrain_tx import autoconfig

    home = tmp_path / "empty"
    home.mkdir()
    assert autoconfig.find_inbox_candidates(home) == []
    assert autoconfig.find_vault_candidates(home) == []
