#!/usr/bin/env python3
"""Export QBot SQLite data to a local, developer-owned Excel workbook."""

import argparse
import io
import os
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape


REPO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DIR = REPO_DIR / "runtime_logs"
DEFAULT_OUTPUT_DIR = Path.home() / "qbot_exports"


def column_name(index):
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def clean_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    text = "".join(
        character
        for character in text
        if character in "\t\n\r"
        or 0x20 <= ord(character) <= 0xD7FF
        or 0xE000 <= ord(character) <= 0xFFFD
    )
    return text[:32767]


def cell(reference, value, header=False):
    return (
        '<c r="{}"{} t="inlineStr"><is><t xml:space="preserve">{}</t>'
        '</is></c>'
    ).format(reference, ' s="1"' if header else "", escape(clean_value(value)))


def read_tables(runtime_dir):
    tables = {}
    databases = sorted(Path(runtime_dir).glob("session_*/robot.db"))
    for database in databases:
        session_id = database.parent.name.replace("session_", "", 1)
        connection = None
        try:
            connection = sqlite3.connect(
                "file:{}?mode=ro".format(database), uri=True, timeout=5
            )
            names = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            for (table_name,) in names:
                quoted_name = '"{}"'.format(table_name.replace('"', '""'))
                cursor = connection.execute("SELECT * FROM {}".format(quoted_name))
                table = tables.setdefault(table_name, {"columns": [], "rows": []})
                columns = [description[0] for description in cursor.description]
                for column in columns:
                    if column not in table["columns"]:
                        table["columns"].append(column)
                for row in cursor:
                    table["rows"].append(
                        (session_id, dict(zip(columns, row)))
                    )
        except (OSError, sqlite3.Error) as error:
            print("Skipping {}: {}".format(database, error))
        finally:
            if connection is not None:
                connection.close()
    return tables


def unique_sheet_name(table_name, used_names):
    base = table_name[:31] or "export"
    name = base
    suffix = 2
    while name in used_names:
        ending = "_{}".format(suffix)
        name = base[: 31 - len(ending)] + ending
        suffix += 1
    used_names.add(name)
    return name


def sheet_xml(rows):
    rendered_rows = []
    for row_number, row in enumerate(rows, start=1):
        rendered_rows.append(
            '<row r="{}">{}</row>'.format(
                row_number,
                "".join(
                    cell(
                        column_name(column_number) + str(row_number),
                        value,
                        header=row_number == 1,
                    )
                    for column_number, value in enumerate(row, start=1)
                ),
            )
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        '<sheetData>{}</sheetData></worksheet>'
    ).format("".join(rendered_rows))


def write_workbook(tables, output):
    sheets = []
    used_names = set()
    for table_name, table in tables.items():
        columns = ["_database_session_id"] + table["columns"]
        rows = [columns]
        for session_id, values in table["rows"]:
            rows.append([session_id] + [values.get(column, "") for column in table["columns"]])
        sheets.append((unique_sheet_name(table_name, used_names), sheet_xml(rows)))

    if not sheets:
        sheets = [("export", sheet_xml([["message"], ["No readable database tables found."]]))]

    workbook_sheets = "".join(
        '<sheet name="{}" sheetId="{}" r:id="rId{}"/>'.format(
            escape(name), index, index
        )
        for index, (name, _xml) in enumerate(sheets, start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>{}</sheets></workbook>'
    ).format(workbook_sheets)
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{}'
        '</Relationships>'
    ).format("".join(
        '<Relationship Id="rId{}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet{}.xml"/>'.format(index, index)
        for index in range(1, len(sheets) + 1)
    ))
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>{}'
        '</Types>'
    ).format("".join(
        '<Override PartName="/xl/worksheets/sheet{}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'.format(index)
        for index in range(1, len(sheets) + 1)
    ))
    root_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_relationships)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        for index, (_name, xml) in enumerate(sheets, start=1):
            archive.writestr("xl/worksheets/sheet{}.xml".format(index), xml)


def main():
    parser = argparse.ArgumentParser(
        description="Export all QBot session database tables to a local XLSX file."
    )
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    output = args.output or DEFAULT_OUTPUT_DIR / (
        "qbot_database_export_{}.xlsx".format(
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
    )
    output = output.expanduser().resolve()
    try:
        output.relative_to(REPO_DIR)
    except ValueError:
        pass
    else:
        parser.error("--output must be outside the Git repository")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output.parent, 0o700)
    temporary = io.BytesIO()
    write_workbook(read_tables(args.runtime_dir), temporary)
    output.write_bytes(temporary.getvalue())
    os.chmod(output, 0o600)
    print("Created private Excel export: {}".format(output))


if __name__ == "__main__":
    main()
