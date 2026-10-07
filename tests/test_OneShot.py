import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from io import StringIO
from pathlib import Path

from OneShot import (
    ProgressReporter,
    apply_manual_deselection,
    build_tree,
    format_json,
    format_markdown,
    format_xml,
    get_token_counter,
    scan,
    render_document,
    render_search_results,
    search_file_lines,
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

    def test_preview_scan_does_not_read_file_content(self):
        entries = scan(self.root, read_content=False)
        by_path = {entry.path: entry for entry in entries}

        self.assertIsNone(by_path["src/main.py"].content)
        self.assertIsNone(by_path["src/main.py"].reason)
        self.assertEqual(by_path[".env"].reason, "sensitive")

    def test_include_pattern_matches_same_filename_in_nested_folders(self):
        (self.root / "CMakeLists.txt").write_text("root", encoding="utf-8")
        (self.root / "src" / "CMakeLists.txt").write_text("nested", encoding="utf-8")
        (self.root / "src" / "other.txt").write_text("exclude", encoding="utf-8")

        entries = scan(self.root, include_globs=["CMakeLists.txt"], read_content=False)

        self.assertEqual({entry.path for entry in entries}, {"CMakeLists.txt", "src/CMakeLists.txt"})

    def test_search_file_lines_captures_wildcard_and_can_include_pattern_text(self):
        (self.root / "src" / "version.arxml").write_text(
            "<AUTOSAR schemaLocation='http://autosar.org/schema/r4.0 AUTOSAR_00051.xsd'>\n",
            encoding="utf-8",
        )
        (self.root / "src" / "second.arxml").write_text(
            "<AUTOSAR schemaLocation='http://autosar.org/schema/r4.0 AUTOSAR_00052.xsd'>\n",
            encoding="utf-8",
        )
        (self.root / "src" / "double-quoted.arxml").write_text(
            '<AUTOSAR schemaLocation="http://autosar.org/schema/r4.0 AUTOSAR_00053.xsd">\n',
            encoding="utf-8",
        )

        results = search_file_lines(self.root, "*.arxml", "schemaLocation='*'")
        full_results = search_file_lines(self.root, "*.arxml", "schemaLocation='*'", True)
        selected_results = search_file_lines(
            self.root,
            "*.arxml",
            "schemaLocation='*'",
            selected_paths={"src/second.arxml"},
        )

        self.assertEqual(
            results,
            [
                ("src/double-quoted.arxml", "http://autosar.org/schema/r4.0 AUTOSAR_00053.xsd"),
                ("src/second.arxml", "http://autosar.org/schema/r4.0 AUTOSAR_00052.xsd"),
                ("src/version.arxml", "http://autosar.org/schema/r4.0 AUTOSAR_00051.xsd"),
            ],
        )
        self.assertEqual(
            full_results,
            [
                ("src/double-quoted.arxml", 'schemaLocation="http://autosar.org/schema/r4.0 AUTOSAR_00053.xsd"'),
                ("src/second.arxml", "schemaLocation='http://autosar.org/schema/r4.0 AUTOSAR_00052.xsd'"),
                ("src/version.arxml", "schemaLocation='http://autosar.org/schema/r4.0 AUTOSAR_00051.xsd'"),
            ],
        )
        self.assertEqual(selected_results, [("src/second.arxml", "http://autosar.org/schema/r4.0 AUTOSAR_00052.xsd")])

    def test_search_result_formats_support_both_orders(self):
        results = [("src/version.arxml", "AUTOSAR_00051.xsd")]

        text = render_search_results(results, "txt", "match_path")
        markdown = render_search_results(results, "md", "match_path")
        json_result = json.loads(render_search_results(results, "json", "match_path"))
        xml_result = ET.fromstring(render_search_results(results, "xml", "match_path"))

        self.assertEqual(text, "AUTOSAR_00051.xsd : src/version.arxml\n")
        self.assertIn("| Match | Path |", markdown)
        self.assertEqual(list(json_result["results"][0]), ["match", "path"])
        self.assertEqual([child.tag for child in xml_result.find("result")], ["match", "path"])

    def test_manual_deselection_skips_only_selected_included_files(self):
        entries = scan(self.root)
        apply_manual_deselection(entries, {"src/main.py", ".env"})
        by_path = {entry.path: entry for entry in entries}

        self.assertEqual(by_path["src/main.py"].reason, "deselected")
        self.assertIsNone(by_path["src/main.py"].content)
        self.assertEqual(by_path[".env"].reason, "sensitive")

    def test_render_document_returns_summary_and_document(self):
        entries = scan(self.root)
        document, summary = render_document(entries, self.root.name, "json", tokens_enabled=False)
        parsed = json.loads(document)

        self.assertEqual(summary, parsed["summary"])
        self.assertEqual(summary["files_included"], 1)
        self.assertEqual(summary["files_skipped"], 4)

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

    def test_progress_reporter_shows_scanning_and_percentage_updates(self):
        stream = StringIO()
        progress = ProgressReporter(enabled=True, stream=stream)

        progress.update("Scanning files", 3)
        progress.update("Counting tokens", 1, 4)
        progress.finish("Complete")

        output = stream.getvalue()
        self.assertIn("Scanning files: 3 files", output)
        self.assertIn("Counting tokens: [#####---------------]  25% (1/4)", output)
        self.assertTrue(output.rstrip().endswith("Complete"))


if __name__ == "__main__":
    unittest.main()
