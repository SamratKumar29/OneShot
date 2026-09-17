import json
import tempfile
import unittest
from pathlib import Path

from OneShot import (
    build_tree,
    format_json,
    format_markdown,
    format_xml,
    get_token_counter,
    scan,
    summary_for,
)


class OneShotTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_bytes(b"print('<hello>')\n")
        (self.root / ".env").write_text("TOKEN=do-not-export\n", encoding="utf-8")
        (self.root / "image.bin").write_bytes(b"\x00\x01binary")
        (self.root / "src" / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (self.root / "src" / "ignored.txt").write_text("should not be included\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scan_keeps_sensitive_and_binary_paths_without_content(self):
        entries = scan(self.root)
        by_path = {entry.path: entry for entry in entries}

        self.assertEqual(by_path["src/main.py"].content, "print('<hello>')\n")
        self.assertEqual(by_path[".env"].reason, "sensitive")
        self.assertIsNone(by_path[".env"].content)
        self.assertEqual(by_path["image.bin"].reason, "binary")
        self.assertEqual(by_path["src/ignored.txt"].reason, "ignored")

    def test_formats_preserve_content_safely(self):
        entries = scan(self.root)
        counter = get_token_counter(disabled=True)
        for entry in entries:
            if not entry.skipped and not entry.is_directory:
                entry.tokens = counter(entry.content or "")
        summary = summary_for(entries, tokens_enabled=False)
        tree = build_tree(entries, self.root.name)

        document = format_json(tree, entries, summary)
        parsed = json.loads(document)
        included = next(item for item in parsed["files"] if item["path"] == "src/main.py")
        self.assertEqual(included["content"], "print('<hello>')\n")
        self.assertIn(".env (skipped: sensitive)", parsed["tree"])

        xml = format_xml(tree, entries, summary)
        self.assertIn("&lt;hello&gt;", xml)
        self.assertIn('path=".env"', xml)

    def test_single_file_path_is_supported(self):
        target = self.root / "src" / "main.py"
        entries = scan(target)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].path, "main.py")

    def test_large_structure_is_replaced_with_compact_overview(self):
        entries = [
            type("Entry", (), {"path": f"src/module_{index}/file.py", "content": "", "reason": None, "is_directory": False, "skipped": False})()
            for index in range(25)
        ]

        structure = build_tree(entries, "repo")

        self.assertLessEqual(len(structure.splitlines()), 20)
        self.assertIn("Detailed structure omitted", structure)
        self.assertIn("Total: 25 included files", structure)

    def test_markdown_summary_appears_before_structure_and_contents(self):
        entries = scan(self.root)
        summary = summary_for(entries, tokens_enabled=False)
        document = format_markdown(build_tree(entries, self.root.name), entries, summary)

        self.assertLess(document.index("## Summary"), document.index("## Structure Overview"))
        self.assertLess(document.index("## Structure Overview"), document.index("## File Contents"))


if __name__ == "__main__":
    unittest.main()
