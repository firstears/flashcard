from __future__ import annotations

import argparse
import logging
import logging.handlers
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path

from . import __version__, autoconfig
from .config import Config, ConfigError, load_config
from .pipeline import drain, ingest, process_file
from .state import State, file_sha256
from .stt import SttError, pick_engine
from .watcher import InboxScanner

log = logging.getLogger("secondbrain_tx")


def setup_logging(cfg: Config) -> None:
    cfg.state_path.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger("secondbrain_tx")
    root.setLevel(logging.INFO)
    file_handler = logging.handlers.RotatingFileHandler(
        cfg.state_path / "transcriber.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    stream = logging.StreamHandler(sys.stdout)
    for handler in (file_handler, stream):
        handler.setFormatter(fmt)
        root.addHandler(handler)


def _engine_factory(cfg: Config):
    return lambda: pick_engine(cfg.engine, cfg.model)


def cmd_run(cfg: Config, once: bool) -> int:
    state = State(cfg.state_path / "state.db")
    scanner = InboxScanner(cfg.inbox_path, cfg.stable_seconds)
    stop = {"flag": False}

    def _stop(_sig, _frm):
        stop["flag"] = True
        log.info("종료 요청을 받았습니다. 현재 작업이 끝나면 멈춥니다.")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    log.info("시작 v%s | 받은편지함: %s | 보관함: %s", __version__, cfg.inbox_path, cfg.vault_path)
    if not cfg.inbox_path.is_dir():
        log.warning("받은편지함 폴더가 없습니다. 폴더가 생길 때까지 기다립니다: %s", cfg.inbox_path)
    while not stop["flag"]:
        try:
            ingest(cfg, state, scanner)
            drain(cfg, state, _engine_factory(cfg))
        except Exception as exc:  # noqa: BLE001
            log.error("예상하지 못한 오류(계속 실행합니다): %s", exc)
        if once:
            # 안정 확인 대기 때문에 한 번만 훑으면 새 파일을 놓친다: 대기 후 한 번 더.
            if not stop["flag"] and cfg.stable_seconds > 0:
                time.sleep(cfg.stable_seconds + 1)
                ingest(cfg, state, scanner)
                drain(cfg, state, _engine_factory(cfg))
            break
        for _ in range(int(max(1, cfg.poll_seconds))):
            if stop["flag"]:
                break
            time.sleep(1)
    state.close()
    return 0


def cmd_transcribe(cfg: Config, file: Path) -> int:
    """폴더 감시 없이 파일 하나를 바로 전사한다 (첫 시험용)."""
    if not file.exists():
        print(f"파일을 찾을 수 없습니다: {file}")
        return 2
    engine = pick_engine(cfg.engine, cfg.model)
    sha = file_sha256(file)
    rel = process_file(cfg, engine, file, sha)
    print(f"완료: {cfg.vault_path / rel}")
    return 0


def cmd_status(cfg: Config) -> int:
    state = State(cfg.state_path / "state.db")
    counts = state.counts()
    print("작업 현황:", ", ".join(f"{k} {v}건" for k, v in counts.items()) or "아직 없음")
    for row in state.recent(10):
        extra = f" | 오류: {row['error']}" if row["error"] else ""
        print(f"- [{row['status']}] {Path(row['path']).name} (시도 {row['attempts']}회){extra}")
    state.close()
    return 0


def cmd_retry(cfg: Config) -> int:
    state = State(cfg.state_path / "state.db")
    print(f"실패한 작업 {state.retry_failed()}건을 다시 대기열에 넣었습니다.")
    state.close()
    return 0


def cmd_autoconfig(cfg_path: Path) -> int:
    """Google Drive 폴더와 Obsidian 보관함을 찾아 설정 파일에 기록한다."""
    if not cfg_path.exists():
        print(f"설정 파일이 없습니다: {cfg_path}")
        return 2
    home = Path.home()
    inbox_list = autoconfig.find_inbox_candidates(home)
    vault_list = autoconfig.find_vault_candidates(home)
    inbox = inbox_list[0] if inbox_list else None
    vault = vault_list[0] if vault_list else None

    if inbox:
        print(f"[찾음] 받은편지함(Google Drive): {inbox}")
        for other in inbox_list[1:]:
            print(f"       다른 후보: {other}")
    else:
        print("[못 찾음] Google Drive 의 '전사받는곳' 또는 'Second Brain_test' 폴더")
        print("          Mac 에 Google Drive 데스크톱 앱을 설치하고 로그인했는지 확인하십시오.")
    if vault:
        print(f"[찾음] Obsidian 보관함: {vault}")
        for other in vault_list[1:]:
            print(f"       다른 후보: {other}")
    else:
        print("[못 찾음] Obsidian 보관함: 기본 위치 ~/Documents/SecondBrain 을 새로 만들어 씁니다.")
    autoconfig.update_config(cfg_path, inbox, vault)
    print(f"설정 파일에 기록했습니다: {cfg_path}")
    return 0


def cmd_doctor(cfg: Config, deep: bool) -> int:
    problems = 0

    def report(ok: bool, text: str, hint: str = "") -> None:
        nonlocal problems
        print(("[정상]    " if ok else "[확인필요] ") + text)
        if not ok:
            problems += 1
            if hint:
                print(f"           -> {hint}")

    report(sys.version_info >= (3, 10), f"파이썬 {sys.version.split()[0]}", "파이썬 3.10 이상이 필요합니다.")
    for tool in ("ffmpeg", "ffprobe"):
        report(shutil.which(tool) is not None, f"{tool} 설치", "터미널에서 'brew install ffmpeg' 실행")
    import importlib.util

    from .stt import is_apple_silicon

    if is_apple_silicon():
        has_mlx = importlib.util.find_spec("mlx_whisper") is not None
        report(has_mlx, "mlx-whisper (Apple 칩 가속)", "pip install -r requirements-mac.txt")
    else:
        has_faster = importlib.util.find_spec("faster_whisper") is not None
        report(has_faster, "faster-whisper (CPU) — Apple 칩이 아니므로 이 엔진을 씁니다", "pip install -r requirements.txt")
    report(
        cfg.inbox_path.is_dir(),
        f"받은편지함 폴더: {cfg.inbox_path}",
        "폴더가 없거나 경로가 다릅니다. config.yaml 의 inbox 를 확인하고, Google Drive 폴더는 '미러링'으로 설정하십시오.",
    )
    vault_ok = False
    try:
        cfg.vault_path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cfg.vault_path, prefix=".tx-check-"):
            vault_ok = True
    except OSError:
        pass
    report(
        vault_ok,
        f"Obsidian 보관함 쓰기: {cfg.vault_path}",
        "경로를 확인하십시오. 폴더가 iCloud/문서 안이면 터미널에 '전체 디스크 접근'을 허용해야 할 수 있습니다.",
    )
    print(f"[참고]    용어 사전: {'있음' if cfg.glossary_path.exists() else '없음'} ({cfg.glossary_path})")
    if deep:
        print("모델 점검 중... 처음 한 번은 모델(약 1.5GB)을 내려받느라 몇 분 걸립니다.")
        try:
            engine = pick_engine(cfg.engine, cfg.model)
            with tempfile.TemporaryDirectory() as tmp:
                wav = Path(tmp) / "silence.wav"
                import subprocess

                subprocess.run(
                    ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                     "anullsrc=r=16000:cl=mono", "-t", "2", str(wav)],
                    check=True,
                )
                engine.transcribe(wav, cfg.language, "")
            report(True, f"전사 엔진 시험 통과 ({engine.name})")
        except Exception as exc:  # noqa: BLE001
            report(False, f"전사 엔진 시험 실패: {exc}")
    print("\n결과:", "모두 정상입니다." if problems == 0 else f"확인이 필요한 항목 {problems}개")
    return 0 if problems == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secondbrain_tx", description="로컬 녹음 전사 -> Obsidian")
    parser.add_argument("--config", help="설정 파일 경로 (기본: ~/.secondbrain-transcriber/config.yaml)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="폴더를 계속 감시하며 처리")
    sub.add_parser("once", help="현재 쌓인 파일만 처리하고 종료")
    p_tr = sub.add_parser("transcribe", help="파일 하나를 바로 전사 (시험용)")
    p_tr.add_argument("file", type=Path)
    sub.add_parser("status", help="작업 현황")
    sub.add_parser("retry", help="실패한 작업 다시 시도")
    sub.add_parser("autoconfig", help="Drive 폴더와 Obsidian 보관함을 자동으로 찾아 설정에 기록")
    p_doc = sub.add_parser("doctor", help="설치와 설정 점검")
    p_doc.add_argument("--deep", action="store_true", help="모델까지 실제로 시험 (처음엔 다운로드)")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(exc)
        return 2
    if args.cmd == "autoconfig":
        from .config import DEFAULT_CONFIG_PATH

        return cmd_autoconfig(Path(args.config).expanduser() if args.config else DEFAULT_CONFIG_PATH)
    if args.cmd != "doctor":
        setup_logging(cfg)
    try:
        if args.cmd == "run":
            return cmd_run(cfg, once=False)
        if args.cmd == "once":
            return cmd_run(cfg, once=True)
        if args.cmd == "transcribe":
            return cmd_transcribe(cfg, args.file)
        if args.cmd == "status":
            return cmd_status(cfg)
        if args.cmd == "retry":
            return cmd_retry(cfg)
        return cmd_doctor(cfg, args.deep)
    except SttError as exc:
        print(f"전사 엔진 오류: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
