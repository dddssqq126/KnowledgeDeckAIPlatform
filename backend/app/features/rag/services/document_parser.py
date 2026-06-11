"""Parse uploaded files into a list of (text, page_number) segments.

Per-format behavior:
  - txt / cs / md : one segment, page_number=None
  - pdf           : one segment per page, page_number=<1-based>
  - pptx          : one segment per slide, page_number=<slide index>
  - docx          : one segment, page_number=None (no native page concept)
  - xlsx          : one segment per worksheet, page_number=<sheet index>
  - csv           : one segment, page_number=None
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, time
from dataclasses import dataclass

from docx import Document as DocxDocument
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader


@dataclass
class ParsedSegment:
    text: str
    page_number: int | None  # 1-based; None for non-paginated formats


def _parse_pdf(data: bytes) -> list[ParsedSegment]:
    reader = PdfReader(io.BytesIO(data))
    out: list[ParsedSegment] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            out.append(ParsedSegment(text=text, page_number=i))
    return out


def _parse_docx(data: bytes) -> list[ParsedSegment]:
    """Flatten paragraphs + table cells into a single segment.

    Word documents have no exposed page concept (page breaks are layout
    decisions made at render time), so we emit one segment for the whole
    file. Tables are joined with " | " between cells so chunks retain
    some readable structure.
    """
    doc = DocxDocument(io.BytesIO(data))
    parts: list[str] = []
    for para in doc.paragraphs:
        t = para.text.strip()
        if t:
            parts.append(t)
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    text = "\n".join(parts)
    return [ParsedSegment(text=text, page_number=None)] if text.strip() else []


def _parse_pptx(data: bytes) -> list[ParsedSegment]:
    """One segment per slide, page_number = slide index.

    Walks every shape on the slide that has a text frame; concatenates
    paragraph text with newlines. Speaker notes are intentionally excluded
    — they're authoring metadata, not deck content.
    """
    prs = Presentation(io.BytesIO(data))
    out: list[ParsedSegment] = []
    for i, slide in enumerate(prs.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                t = "".join(run.text for run in para.runs).strip()
                if t:
                    parts.append(t)
        text = "\n".join(parts)
        if text.strip():
            out.append(ParsedSegment(text=text, page_number=i))
    return out


_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp950", "big5")


def _format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value).strip()


def _join_non_empty_row(values: list[str]) -> str:
    last = -1
    for idx, value in enumerate(values):
        if value:
            last = idx
    if last < 0:
        return ""
    return "\t".join(values[: last + 1])


def _parse_xlsx(data: bytes) -> list[ParsedSegment]:
    """Extract workbook text as one segment per worksheet.

    Cells in each row are joined by tabs so RAG keeps table shape while still
    embedding plain text. Formula cells use cached values when present; if a
    workbook has no cached formula result, the formula text is used instead.
    """
    out: list[ParsedSegment] = []
    values_wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    formulas_wb = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    try:
        for i, values_ws in enumerate(values_wb.worksheets, start=1):
            formulas_ws = formulas_wb[values_ws.title]
            lines: list[str] = [f"Sheet: {values_ws.title}"]
            value_rows = values_ws.iter_rows()
            formula_rows = formulas_ws.iter_rows()
            for value_row, formula_row in zip(value_rows, formula_rows, strict=True):
                cells: list[str] = []
                for value_cell, formula_cell in zip(
                    value_row, formula_row, strict=True
                ):
                    value = value_cell.value
                    formula_value = formula_cell.value
                    if (
                        value is None
                        and isinstance(formula_value, str)
                        and formula_value.startswith("=")
                    ):
                        value = formula_value
                    cells.append(_format_cell(value))
                line = _join_non_empty_row(cells)
                if line:
                    lines.append(line)
            if len(lines) > 1:
                out.append(
                    ParsedSegment(text="\n".join(lines), page_number=i)
                )
    finally:
        values_wb.close()
        formulas_wb.close()
    return out


def _decode_csv(data: bytes) -> str:
    if b"\x00" in data[:1024]:
        raise ValueError("csv contains null byte")
    last_error: UnicodeDecodeError | None = None
    for encoding in _CSV_ENCODINGS:
        try:
            return data.decode(encoding, errors="strict")
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return ""


def _csv_dialect(text: str) -> csv.Dialect:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        return csv.excel


def _parse_csv(data: bytes) -> list[ParsedSegment]:
    text = _decode_csv(data)
    reader = csv.reader(io.StringIO(text), dialect=_csv_dialect(text))
    lines: list[str] = []
    for row in reader:
        line = _join_non_empty_row([_format_cell(cell) for cell in row])
        if line:
            lines.append(line)
    return [ParsedSegment(text="\n".join(lines), page_number=None)] if lines else []


# Plain-text-ish formats: decoded as UTF-8 into a single segment. Includes
# code formats — embedding them as raw source works well enough for RAG;
# we don't strip language-specific syntax (HTML tags / Python comments).
_TEXT_EXTENSIONS = ("txt", "cs", "md", "py", "html", "css")


def parse(extension: str, data: bytes) -> list[ParsedSegment]:
    if extension in _TEXT_EXTENSIONS:
        return [ParsedSegment(text=data.decode("utf-8", errors="replace"), page_number=None)]
    if extension == "pdf":
        return _parse_pdf(data)
    if extension == "docx":
        return _parse_docx(data)
    if extension == "pptx":
        return _parse_pptx(data)
    if extension == "xlsx":
        return _parse_xlsx(data)
    if extension == "csv":
        return _parse_csv(data)
    raise ValueError(f"unsupported extension: {extension}")
