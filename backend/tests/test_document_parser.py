import io
import zipfile

from app.features.knowledge_bases.services import file_service
from app.features.rag.services import document_parser


def _xlsx_bytes() -> bytes:
    files = {
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Summary" sheetId="1" r:id="rId1"/>
    <sheet name="Details" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>
""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>
""",
        "xl/sharedStrings.xml": """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <si><t>Vendor</t></si>
  <si><t>Teradyne</t></si>
  <si><t>Platform</t></si>
  <si><t>UltraFLEX</t></si>
  <si><t>Limit</t></si>
</sst>
""",
        "xl/worksheets/sheet1.xml": """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
    <row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row>
  </sheetData>
</worksheet>
""",
        "xl/worksheets/sheet2.xml": """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>4</v></c><c r="B1"><v>42</v></c></row>
    <row r="2"><c r="A2" t="inlineStr"><is><t>Inline note</t></is></c><c r="B2" t="b"><v>1</v></c></row>
  </sheetData>
</worksheet>
""",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


def test_parse_xlsx_extracts_each_worksheet() -> None:
    segments = document_parser.parse("xlsx", _xlsx_bytes())

    assert [segment.page_number for segment in segments] == [1, 2]
    assert segments[0].text == "Sheet: Summary\nVendor\tTeradyne\nPlatform\tUltraFLEX"
    assert segments[1].text == "Sheet: Details\nLimit\t42\nInline note\tTRUE"


def test_file_service_accepts_xlsx_ooxml_upload() -> None:
    data = _xlsx_bytes()

    assert file_service.validate_extension("workbook.xlsx") == "xlsx"
    file_service.validate_content("xlsx", data[:1024])
