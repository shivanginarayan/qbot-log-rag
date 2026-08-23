import json
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chat_history import ExcelChatLogger  # noqa: E402


class ExcelChatLoggerTest(unittest.TestCase):
    def test_append_writes_jsonl_and_valid_xlsx(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / "history.xlsx"
            logger = ExcelChatLogger(workbook)

            logger.append(
                {
                    "user_name": "Shivangi",
                    "question": "Why didn't it move?",
                    "llm_response": "No movement command was recorded.",
                    "model": "test-model",
                    "status": "ok",
                }
            )
            logger.append(
                {
                    "user_name": "A & B",
                    "question": "What happened <now>?",
                    "llm_response": "The logs are incomplete.",
                    "status": "no_evidence",
                }
            )

            self.assertTrue(workbook.exists())
            self.assertTrue(logger.jsonl_path.exists())
            self.assertEqual(
                stat.S_IMODE(
                    workbook.stat().st_mode
                ),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE(
                    logger.jsonl_path
                    .stat().st_mode
                ),
                0o600,
            )

            with logger.jsonl_path.open(
                encoding="utf-8"
            ) as stream:
                records = [
                    json.loads(line)
                    for line in stream
                ]

            self.assertEqual(len(records), 2)
            self.assertEqual(
                records[0]["user_name"],
                "Shivangi",
            )

            with zipfile.ZipFile(workbook) as archive:
                self.assertIsNone(archive.testzip())
                sheet = archive.read(
                    "xl/worksheets/sheet1.xml"
                )

            root = ElementTree.fromstring(sheet)
            namespace = {
                "x": (
                    "http://schemas.openxmlformats.org/"
                    "spreadsheetml/2006/main"
                )
            }
            rows = root.findall(
                ".//x:sheetData/x:row",
                namespace,
            )

            self.assertEqual(len(rows), 3)
            all_text = " ".join(
                element.text or ""
                for element in root.findall(
                    ".//x:t",
                    namespace,
                )
            )
            self.assertIn("A & B", all_text)
            self.assertIn(
                "What happened <now>?",
                all_text,
            )


if __name__ == "__main__":
    unittest.main()
