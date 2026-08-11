"""Local document parsing via markitdown (docx/pdf/pptx/xlsx/html/md...).

markitdown is rule-based and deterministic (confidence 1.0). For hard layouts
(scanned PDFs, complex tables/formulas) the caller should route to
``task_type=ocr`` or the future PaddleOCR-VL / MinerU pipeline instead.
"""

from __future__ import annotations

from ..config import Settings
from ..envelope import DependencyMissingError, InternalError
from ..input import Source, ensure_local_file

NAME = "markitdown"


def run(source: Source, settings: Settings) -> tuple[str, float]:
    """Return (markdown text, confidence)."""
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise DependencyMissingError(
            "markitdown is not installed; install the document extra: "
            "`uvx vision-augment[document]` or `pip install 'markitdown[all]'`"
        ) from exc

    path = ensure_local_file(source, settings.cache_dir)
    try:
        text = MarkItDown().convert(str(path)).text_content
    except Exception as exc:
        raise InternalError(f"markitdown failed: {exc}") from exc
    return text, 1.0
