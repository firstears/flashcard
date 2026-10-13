from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

AUDIO_EXTS = {
    ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".amr", ".wma",
    ".mp4", ".mov", ".mkv", ".webm", ".3gp",
}
TEMP_SUFFIXES = (".tmp", ".part", ".crdownload", ".download", ".partial")
SKIP_DIRS = {"_done", "_failed"}


def is_candidate(name: str) -> bool:
    lower = name.lower()
    if name.startswith(".") or name.startswith("~"):
        return False
    if lower.endswith(TEMP_SUFFIXES):
        return False
    return os.path.splitext(lower)[1] in AUDIO_EXTS


class InboxScanner:
    """폴더를 주기적으로 훑어서, 크기와 수정시각이 일정 시간 변하지 않은 파일만 돌려준다.

    폴더 이벤트(watchdog) 대신 주기 검사를 쓰는 이유: Google Drive 같은 클라우드 폴더는
    이벤트가 누락되는 경우가 있어, 단순 검사가 더 안정적이다.
    """

    def __init__(
        self,
        inbox: Path,
        stable_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.inbox = inbox
        self.stable_seconds = stable_seconds
        self.clock = clock
        self._seen: dict[Path, tuple[int, float, float]] = {}
        self._handled: dict[Path, tuple[int, float]] = {}

    def mark_handled(self, path: Path) -> None:
        try:
            st = path.stat()
        except OSError:
            return
        self._handled[path] = (st.st_size, st.st_mtime)

    def scan(self) -> list[Path]:
        ready: list[Path] = []
        present: set[Path] = set()
        if not self.inbox.is_dir():
            return ready
        now = self.clock()
        for root, dirs, files in os.walk(self.inbox):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for name in files:
                if not is_candidate(name):
                    continue
                path = Path(root) / name
                try:
                    st = path.stat()
                except OSError:
                    continue
                present.add(path)
                if self._handled.get(path) == (st.st_size, st.st_mtime):
                    continue
                if st.st_size == 0:
                    continue
                prev = self._seen.get(path)
                if prev is None or prev[0] != st.st_size or prev[1] != st.st_mtime:
                    self._seen[path] = (st.st_size, st.st_mtime, now)
                    continue
                if now - prev[2] >= self.stable_seconds:
                    ready.append(path)
        for gone in set(self._seen) - present:
            del self._seen[gone]
        for gone in set(self._handled) - present:
            del self._handled[gone]
        return sorted(ready)
