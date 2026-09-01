import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_DIR = Path(__file__).resolve().parents[1]
SESSION_CHAT_UI_DIR = REPO_DIR / "session_chat_ui"
if str(SESSION_CHAT_UI_DIR) not in sys.path:
    sys.path.insert(0, str(SESSION_CHAT_UI_DIR))

import server  # noqa: E402


class ChatSystemReadinessTest(unittest.TestCase):
    def test_rosout_system_is_ready_when_session_has_rosout_data(self):
        app = server.ChatApplication(
            locator=None,
            store=None,
            runner=None,
        )
        with tempfile.TemporaryDirectory() as directory:
            bag_dir = Path(directory) / "rosout"
            bag_dir.mkdir(parents=True, exist_ok=True)
            comparison_script = Path(directory) / "run_comparison.sh"
            comparison_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            with mock.patch.object(
                server,
                "rosout_index_path",
                return_value=Path(directory) / "missing_index.json",
            ), mock.patch.object(
                server,
                "rosout_bag_dir",
                return_value=bag_dir,
            ), mock.patch.object(
                server,
                "COMPARISON_SCRIPT",
                comparison_script,
            ):
                state, detail, progress = app._system_state(
                    "rosout",
                    {"session_id": "abc123", "database": "ignored.db"},
                    True,
                    True,
                )

        self.assertEqual(state, "ready")
        self.assertEqual(detail, "")
        self.assertIsNone(progress)


if __name__ == "__main__":
    unittest.main()
