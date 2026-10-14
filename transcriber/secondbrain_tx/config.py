from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path("~/.secondbrain-transcriber/config.yaml").expanduser()


@dataclass
class Config:
    inbox: str = "~/Google Drive/전사받는곳"
    vault: str = "~/Documents/SecondBrain"
    daily_dir: str = "Daily"
    transcript_dir: str = "전사"
    state_dir: str = "~/.secondbrain-transcriber"
    language: str = "ko"
    engine: str = "auto"  # auto | mlx | faster
    model: str = "auto"
    glossary: str = ""  # 비우면 state_dir/glossary.txt
    corrections: str = ""  # 비우면 state_dir/corrections.tsv
    stable_seconds: float = 15
    poll_seconds: float = 10
    chunk_minutes: float = 20
    silence_db: float = -35  # 이보다 조용하면 무음으로 본다 (주변 소음이 크면 -30 등으로 조정)
    skip_silence_seconds: float = 8  # 이 시간 이상 이어지는 무음은 전사하지 않고 건너뜀
    after_done: str = "move"  # move | keep
    max_attempts: int = 3

    @staticmethod
    def _expand(value: str) -> Path:
        return Path(os.path.expanduser(value))

    @property
    def inbox_path(self) -> Path:
        return self._expand(self.inbox)

    @property
    def vault_path(self) -> Path:
        return self._expand(self.vault)

    @property
    def state_path(self) -> Path:
        return self._expand(self.state_dir)

    @property
    def glossary_path(self) -> Path:
        return self._expand(self.glossary) if self.glossary else self.state_path / "glossary.txt"

    @property
    def corrections_path(self) -> Path:
        return (
            self._expand(self.corrections)
            if self.corrections
            else self.state_path / "corrections.tsv"
        )


class ConfigError(Exception):
    pass


def load_config(path: str | Path | None = None) -> Config:
    cfg_path = Path(path).expanduser() if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        return Config()
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"설정 파일을 읽을 수 없습니다: {cfg_path}\n{exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"설정 파일 형식이 올바르지 않습니다: {cfg_path}")
    allowed = {f.name for f in fields(Config)}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(
            f"알 수 없는 설정 항목: {', '.join(unknown)}\n사용 가능한 항목: {', '.join(sorted(allowed))}"
        )
    cfg = Config(**data)
    if cfg.engine not in ("auto", "mlx", "faster"):
        raise ConfigError("engine 값은 auto, mlx, faster 중 하나여야 합니다.")
    if cfg.after_done not in ("move", "keep"):
        raise ConfigError("after_done 값은 move 또는 keep 이어야 합니다.")
    return cfg
