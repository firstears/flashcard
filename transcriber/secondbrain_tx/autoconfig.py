from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

# 받은편지함으로 쓸 Google Drive 폴더 이름 (앞쪽이 우선)
INBOX_NAMES = ("전사받는곳", "Second Brain_test")

_SKIP_DIRS = {"Library", "node_modules", "Applications", "Pictures", "Movies", "Music"}


def _nfc(text: str) -> str:
    # macOS 는 한글 파일 이름을 자모 분리(NFD)로 돌려줄 수 있어 정규화해서 비교한다.
    return unicodedata.normalize("NFC", text)


def _subdirs(path: Path) -> list[Path]:
    try:
        return [p for p in path.iterdir() if p.is_dir()]
    except OSError:
        return []


def find_inbox_candidates(home: Path) -> list[Path]:
    """Google Drive 데스크톱 앱이 만든 폴더 안에서 받은편지함 후보를 찾는다."""
    wanted = {_nfc(n): i for i, n in enumerate(INBOX_NAMES)}
    found: list[tuple[int, Path]] = []
    base = home / "Library" / "CloudStorage"
    for account in _subdirs(base):
        if not account.name.startswith("GoogleDrive-"):
            continue
        for drive in _subdirs(account):  # "내 드라이브" / "My Drive"
            for first in _subdirs(drive):
                if _nfc(first.name) in wanted:
                    found.append((wanted[_nfc(first.name)], first))
                for second in _subdirs(first):  # 한 단계 더 깊은 폴더까지
                    if _nfc(second.name) in wanted:
                        found.append((wanted[_nfc(second.name)] + 10, second))
    return [p for _, p in sorted(found, key=lambda x: (x[0], str(x[1])))]


def find_vault_candidates(home: Path, max_depth: int = 3) -> list[Path]:
    """.obsidian 폴더가 있는 곳 = Obsidian 보관함. 최근에 쓴 것이 앞에 온다."""
    roots = [
        home / "Documents",
        home / "Desktop",
        home / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents",
        home,
    ]
    seen: set[Path] = set()
    vaults: list[tuple[float, Path]] = []

    def walk(path: Path, depth: int) -> None:
        if path in seen or depth > max_depth:
            return
        seen.add(path)
        marker = path / ".obsidian"
        if marker.is_dir():
            try:
                vaults.append((marker.stat().st_mtime, path))
            except OSError:
                pass
            return
        for sub in _subdirs(path):
            if sub.name.startswith(".") or sub.name in _SKIP_DIRS:
                continue
            walk(sub, depth + 1)

    for root in roots:
        walk(root, 0 if root != home else max_depth - 1)
    vaults.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in vaults]


def update_config(cfg_path: Path, inbox: Path | None, vault: Path | None) -> None:
    """설정 파일의 inbox, vault 줄만 바꾸고 나머지(주석 포함)는 그대로 둔다."""
    text = cfg_path.read_text(encoding="utf-8")

    def _set(key: str, value: Path, src: str) -> str:
        line = f"{key}: {json.dumps(str(value), ensure_ascii=False)}"
        pattern = re.compile(rf"^{key}:.*$", re.MULTILINE)
        if pattern.search(src):
            return pattern.sub(lambda _m: line, src, count=1)
        return src + f"\n{line}\n"

    if inbox is not None:
        text = _set("inbox", inbox, text)
    if vault is not None:
        text = _set("vault", vault, text)
    cfg_path.write_text(text, encoding="utf-8")
