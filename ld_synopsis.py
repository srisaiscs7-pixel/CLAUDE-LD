"""Read the uploaded synopsis (PDF, Word or text)."""
from __future__ import annotations

import io


def read_text(name: str, data: bytes) -> str:
    n = name.lower()
    if n.endswith(".pdf"):
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages).strip()
        except Exception:
            return ""
    if n.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts).strip()
    return data.decode("utf-8", errors="ignore").strip()


def needs_ocr(text: str) -> bool:
    """A scanned PDF has little or no text layer; Gemini can read the pages instead."""
    return len(text.split()) < 80
