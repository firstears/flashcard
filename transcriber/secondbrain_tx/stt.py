from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    start: float
    end: float
    text: str


class SttError(Exception):
    pass


MLX_DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
FASTER_DEFAULT_MODEL = "large-v3-turbo"


class MlxEngine:
    """Apple Silicon(M 시리즈)의 GPU로 전사한다."""

    name = "mlx"

    def __init__(self, model: str = "auto"):
        try:
            import mlx_whisper  # noqa: F401
        except ImportError as exc:
            raise SttError("mlx-whisper 가 설치되어 있지 않습니다. (pip install mlx-whisper)") from exc
        self.model = MLX_DEFAULT_MODEL if model == "auto" else model

    def transcribe(self, wav: Path, language: str, prompt: str) -> list[Segment]:
        import mlx_whisper

        result = mlx_whisper.transcribe(
            str(wav),
            path_or_hf_repo=self.model,
            language=language or None,
            initial_prompt=prompt or None,
            condition_on_previous_text=False,
            verbose=None,
        )
        return [
            Segment(float(s["start"]), float(s["end"]), s["text"].strip())
            for s in result.get("segments", [])
            if s["text"].strip()
        ]


class FasterEngine:
    """CPU 또는 NVIDIA GPU 용 (faster-whisper). Intel Mac, Windows, Linux 에서 쓴다."""

    name = "faster"

    def __init__(self, model: str = "auto"):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise SttError("faster-whisper 가 설치되어 있지 않습니다. (pip install faster-whisper)") from exc
        self.model_name = FASTER_DEFAULT_MODEL if model == "auto" else model
        self._model = WhisperModel(self.model_name, device="auto", compute_type="auto")

    def transcribe(self, wav: Path, language: str, prompt: str) -> list[Segment]:
        segments, _info = self._model.transcribe(
            str(wav),
            language=language or None,
            initial_prompt=prompt or None,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        return [Segment(float(s.start), float(s.end), s.text.strip()) for s in segments if s.text.strip()]


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def pick_engine(engine: str = "auto", model: str = "auto"):
    if engine == "mlx":
        return MlxEngine(model)
    if engine == "faster":
        return FasterEngine(model)
    if is_apple_silicon():
        try:
            return MlxEngine(model)
        except SttError:
            pass  # mlx-whisper 가 없으면 faster-whisper 로 대체
    return FasterEngine(model)
