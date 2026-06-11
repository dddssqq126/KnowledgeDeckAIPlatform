"""Parse uploaded files into a list of (text, page_number) segments.

Per-format behavior:
  - txt / cs / md : one segment, page_number=None
  - pdf           : one segment per page, page_number=<1-based>
  - pptx          : one segment per slide, page_number=<slide index>
  - docx          : one segment, page_number=None (no native page concept)
  - xlsx          : one segment per worksheet, page_number=<sheet index>
"""
from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from docx import Document as DocxDocument
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


def _xml_text(element: ET.Element) -> str:
    return "".join(element.itertext())


def _parse_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        data = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(data)
    return [_xml_text(si) for si in root if si.tag.endswith("}si") or si.tag == "si"]


def _workbook_sheets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Return (sheet_name, worksheet_zip_path) pairs in workbook order."""
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_targets: dict[str, str] = {}
    for rel in rels:
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if not rel_id or not target:
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = posixpath.normpath(posixpath.join("xl", target))
        rel_targets[rel_id] = path

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.iter():
        if not sheet.tag.endswith("}sheet") and sheet.tag != "sheet":
            continue
        name = sheet.attrib.get("name") or "Sheet"
        rel_id = sheet.attrib.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        if rel_id and rel_id in rel_targets:
            sheets.append((name, rel_targets[rel_id]))
    return sheets


def _cell_value(
    cell: ET.Element, *, shared_strings: list[str]
) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        inline = next(
            (child for child in cell if child.tag.endswith("}is") or child.tag == "is"),
            None,
        )
        return _xml_text(inline).strip() if inline is not None else ""

    value_el = next(
        (child for child in cell if child.tag.endswith("}v") or child.tag == "v"),
        None,
    )
    if value_el is None or value_el.text is None:
        return ""
    raw = value_el.text.strip()
    if cell_type == "s":
        try:
            return shared_strings[int(raw)].strip()
        except (ValueError, IndexError):
            return raw
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw


def _parse_worksheet(
    zf: zipfile.ZipFile, path: str, *, name: str, shared_strings: list[str]
) -> str:
    root = ET.fromstring(zf.read(path))
    lines: list[str] = [f"Sheet: {name}"]
    for row in root.iter():
        if not row.tag.endswith("}row") and row.tag != "row":
            continue
        cells: list[str] = []
        for cell in row:
            if not cell.tag.endswith("}c") and cell.tag != "c":
                continue
            value = _cell_value(cell, shared_strings=shared_strings)
            if value:
                cells.append(value)
        if cells:
            lines.append("\t".join(cells))
    return "\n".join(lines) if len(lines) > 1 else ""


def _parse_xlsx(data: bytes) -> list[ParsedSegment]:
    """Extract workbook text as one segment per worksheet.

    Uses the XLSX OOXML files directly instead of an optional spreadsheet
    dependency. Cells in each row are joined by tabs so RAG keeps table shape
    while still embedding plain text.
    """
    out: list[ParsedSegment] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        shared_strings = _parse_shared_strings(zf)
        for i, (name, path) in enumerate(_workbook_sheets(zf), start=1):
            text = _parse_worksheet(
                zf, path, name=name, shared_strings=shared_strings
            )
            if text.strip():
                out.append(ParsedSegment(text=text, page_number=i))
    return out


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
    raise ValueError(f"unsupported extension: {extension}")
