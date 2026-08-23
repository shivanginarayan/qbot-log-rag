import sys
import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import chat_ui  # noqa: E402


class PublicChatPrivacyTest(unittest.TestCase):
    def test_public_page_has_no_developer_controls(self):
        self.assertNotIn(
            "Download Excel",
            chat_ui.PAGE,
        )
        self.assertNotIn(
            "/chat_history.xlsx",
            chat_ui.PAGE,
        )
        self.assertNotIn(
            'id="audience"',
            chat_ui.PAGE,
        )


if __name__ == "__main__":
    unittest.main()
