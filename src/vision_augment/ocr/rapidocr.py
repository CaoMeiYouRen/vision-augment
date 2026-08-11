"""Local OCR via RapidOCR (ONNX-based, the lightweight default engine).

Only active when the ``ocr`` extra is installed; a missing engine surfaces as
a code-4 envelope with install guidance instead of a hard crash. PaddleOCR
(``ocr-full`` extra) is the documented upgrade path for harder Chinese text.

Note: the adapter targets the rapidocr-onnxruntime 1.x API
(``RapidOCR(lang=...).ocr(path)`` returning ``[box, text, score]`` lines) and
is pinned to ``>=1.4,<2`` in pyproject for that reason.
"""

from __future__ import annotations

from ..config import Settings
from ..envelope import DependencyMissingError, InternalError
from ..input import Source, ensure_local_file

NAME = "rapidocr"

_LANGUAGES = {"ch", "en", "japan", "korea", "latin"}
_engines: dict[str, object] = {}


def _get_engine(language: str):
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise DependencyMissingError(
            "rapidocr-onnxruntime is not installed; install the ocr extra: "
            "`uvx vision-augment[ocr]` or `pip install 'rapidocr-onnxruntime>=1.4,<2'`"
        ) from exc
    key = language if language in _LANGUAGES else "ch"
    if key not in _engines:
        # Engine init loads the ONNX models (~tens of MB); keep one per language.
        _engines[key] = RapidOCR(lang=key)
    return _engines[key]


def run(source: Source, language: str, settings: Settings) -> tuple[str, float]:
    """Return (text, mean-confidence)."""
    engine = _get_engine(language)
    path = ensure_local_file(source, settings.cache_dir)
    try:
        result, _elapsed = engine(str(path))
    except Exception as exc:
        raise InternalError(f"rapidocr failed: {exc}") from exc

    if not result:
        return "", 0.0
    lines: list[str] = []
    scores: list[float] = []
    for box, text, score in result:
        lines.append(text)
        scores.append(float(score))
    confidence = sum(scores) / len(scores) if scores else 0.0
    return "\n".join(lines), confidence
