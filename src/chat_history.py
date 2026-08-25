#!/usr/bin/env python3

"""Durable chat logging with a dependency-free Excel export."""

import json
import os
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape


COLUMNS = [
    "timestamp_utc",
    "user_name",
    "question",
    "llm_response",
    "model",
    "audience",
    "map",
    "status",
    "used_llm",
    "packet_count",
    "response_time_ms",
    "error",
    "request_id",
]


def utc_timestamp():
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _column_name(index):
    result = ""

    while index:
        index, remainder = divmod(
            index - 1,
            26,
        )
        result = (
            chr(65 + remainder)
            + result
        )

    return result


def _clean_xml_text(value):
    if value is None:
        return ""

    if isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)

    # XML 1.0 rejects most control characters. Excel also limits cells to
    # 32,767 characters.
    text = "".join(
        character
        for character in text
        if (
            character in "\t\n\r"
            or 0x20 <= ord(character) <= 0xD7FF
            or 0xE000 <= ord(character) <= 0xFFFD
        )
    )

    return text[:32767]


def _cell(reference, value, style_id):
    content = escape(
        _clean_xml_text(value),
        {
            '"': "&quot;",
            "'": "&apos;",
        },
    )

    return (
        '<c r="{}" s="{}" t="inlineStr">'
        '<is><t xml:space="preserve">{}</t></is>'
        "</c>"
    ).format(
        reference,
        style_id,
        content,
    )


class ExcelChatLogger:
    """Append records and rebuild a valid .xlsx workbook atomically."""

    def __init__(self, xlsx_path):
        self.xlsx_path = Path(
            xlsx_path
        ).resolve()
        self.jsonl_path = (
            self.xlsx_path
            .with_suffix(".jsonl")
        )
        self._lock = threading.Lock()

        parent_existed = (
            self.xlsx_path.parent.exists()
        )
        self.xlsx_path.parent.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        if not parent_existed:
            os.chmod(
                self.xlsx_path.parent,
                0o700,
            )

    def append(self, record):
        stored = {
            column: record.get(
                column,
                "",
            )
            for column in COLUMNS
        }

        if not stored["timestamp_utc"]:
            stored["timestamp_utc"] = (
                utc_timestamp()
            )

        if not stored["request_id"]:
            stored["request_id"] = (
                uuid.uuid4().hex
            )

        with self._lock:
            with self.jsonl_path.open(
                "a",
                encoding="utf-8",
            ) as stream:
                os.chmod(
                    self.jsonl_path,
                    0o600,
                )
                stream.write(
                    json.dumps(
                        stored,
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                stream.flush()
                os.fsync(
                    stream.fileno()
                )

            records = self._load_records()
            self._write_workbook(
                records
            )

        return stored

    def _load_records(self):
        records = []

        if not self.jsonl_path.exists():
            return records

        with self.jsonl_path.open(
            "r",
            encoding="utf-8",
        ) as stream:
            for line in stream:
                try:
                    record = json.loads(
                        line
                    )
                except json.JSONDecodeError:
                    continue

                if isinstance(record, dict):
                    records.append(
                        record
                    )

        return records

    def _sheet_xml(self, records):
        rows = []
        header_cells = []

        for column_index, column in enumerate(
            COLUMNS,
            start=1,
        ):
            reference = (
                _column_name(column_index)
                + "1"
            )
            header_cells.append(
                _cell(
                    reference,
                    column,
                    1,
                )
            )

        rows.append(
            '<row r="1" ht="24" customHeight="1">'
            + "".join(header_cells)
            + "</row>"
        )

        for row_index, record in enumerate(
            records,
            start=2,
        ):
            cells = []

            for column_index, column in enumerate(
                COLUMNS,
                start=1,
            ):
                reference = (
                    _column_name(column_index)
                    + str(row_index)
                )
                cells.append(
                    _cell(
                        reference,
                        record.get(
                            column,
                            "",
                        ),
                        2,
                    )
                )

            rows.append(
                '<row r="{}">{}</row>'.format(
                    row_index,
                    "".join(cells),
                )
            )

        last_column = _column_name(
            len(COLUMNS)
        )
        last_row = max(
            len(records) + 1,
            1,
        )

        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <cols>
    <col min="1" max="1" width="22" customWidth="1"/>
    <col min="2" max="2" width="22" customWidth="1"/>
    <col min="3" max="3" width="55" customWidth="1"/>
    <col min="4" max="4" width="90" customWidth="1"/>
    <col min="5" max="13" width="20" customWidth="1"/>
  </cols>
  <sheetData>{rows}</sheetData>
  <autoFilter ref="A1:{last_column}{last_row}"/>
</worksheet>
""".format(
            rows="".join(rows),
            last_column=last_column,
            last_row=last_row,
        )

    def _write_workbook(self, records):
        file_descriptor, temporary_name = (
            tempfile.mkstemp(
                prefix=(
                    "."
                    + self.xlsx_path.name
                    + "."
                ),
                suffix=".tmp",
                dir=str(
                    self.xlsx_path.parent
                ),
            )
        )
        os.close(file_descriptor)

        try:
            with zipfile.ZipFile(
                temporary_name,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as workbook:
                workbook.writestr(
                    "[Content_Types].xml",
                    _CONTENT_TYPES,
                )
                workbook.writestr(
                    "_rels/.rels",
                    _ROOT_RELATIONSHIPS,
                )
                workbook.writestr(
                    "docProps/app.xml",
                    _APP_PROPERTIES,
                )
                workbook.writestr(
                    "xl/workbook.xml",
                    _WORKBOOK,
                )
                workbook.writestr(
                    "xl/_rels/workbook.xml.rels",
                    _WORKBOOK_RELATIONSHIPS,
                )
                workbook.writestr(
                    "xl/styles.xml",
                    _STYLES,
                )
                workbook.writestr(
                    "xl/worksheets/sheet1.xml",
                    self._sheet_xml(
                        records
                    ),
                )

            os.replace(
                temporary_name,
                self.xlsx_path,
            )
            os.chmod(
                self.xlsx_path,
                0o600,
            )
        finally:
            if os.path.exists(
                temporary_name
            ):
                os.unlink(
                    temporary_name
                )


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""


_ROOT_RELATIONSHIPS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""


_APP_PROPERTIES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>QBot Log RAG</Application>
</Properties>
"""


_WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Chat History" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""


_WORKBOOK_RELATIONSHIPS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
"""


_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF215A6D"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="3">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>
"""
