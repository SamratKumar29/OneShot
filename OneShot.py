"""Pack a local file or repository into an LLM-friendly single document."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import TextIOBase
from pathlib import Path
from typing import Callable, Iterable

try:
    import pathspec
except ImportError:
    pathspec = None


DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "__pycache__",
    ".venv", "venv", "env", "dist", "build", ".next", ".cache", ".pytest_cache",
    ".mypy_cache", ".tox", "coverage", "target",
}
DEFAULT_IGNORE_FILES = {
    ".ds_store", "thumbs.db", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "composer.lock", "poetry.lock",
}
BINARY_EXTENSIONS = {
    ".7z", ".a", ".avi", ".bin", ".bmp", ".class", ".dll", ".eot", ".exe", ".flac",
    ".gif", ".gz", ".ico", ".jpeg", ".jpg", ".m4a", ".mov", ".mp3", ".mp4", ".o",
    ".obj", ".ogg", ".pdf", ".png", ".pyc", ".rar", ".rig", ".so", ".tar", ".ttf",
    ".wav", ".webm", ".woff", ".woff2", ".xz", ".zip",
}
SENSITIVE_PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12", "id_rsa*", "id_dsa*",
    "credentials*.json", "secrets*", "secret.*", "salt.txt", "smek.txt", "smpk.txt", "*.secret",
)


class ProgressReporter:
    def __init__(self, enabled: bool | None = None, stream: TextIOBase | None = None):
        self.stream = stream or sys.stderr
        self.enabled = self.stream.isatty() if enabled is None else enabled
        self.last_length = 0

    def update(self, phase: str, current: int, total: int | None = None) -> None:
        if not self.enabled:
            return
        if total:
            percent = current * 100 // total
            bar_width = 20
            filled = percent * bar_width // 100
            bar = "#" * filled + "-" * (bar_width - filled)
            message = f"{phase}: [{bar}] {percent:3d}% ({current}/{total})"
        else:
            message = f"{phase}: {current} files"
        padding = max(0, self.last_length - len(message))
        self.stream.write(f"\r{message}{' ' * padding}")
        self.stream.flush()
        self.last_length = len(message)

    def finish(self, message: str) -> None:
        if not self.enabled:
            return
        padding = max(0, self.last_length - len(message))
        self.stream.write(f"\r{message}{' ' * padding}\n")
        self.stream.flush()
        self.last_length = 0


@dataclass
class FileEntry:
    path: str
    content: str | None = None
    reason: str | None = None
    is_directory: bool = False
    tokens: int = 0

    @property
    def skipped(self) -> bool:
        return self.reason is not None


class IgnoreMatcher:
    def __init__(self, root: Path, use_gitignore: bool = True, extra_patterns: Iterable[str] = ()):
        self.root = root
        self.rules: list[tuple[Path, object]] = []
        self.fallback_rules: list[tuple[Path, list[str]]] = []
        self.extra_patterns = [pattern for pattern in extra_patterns if pattern.strip()]
        self.use_gitignore = use_gitignore
        self._load_rules()

    def _add_rules(self, base: Path, lines: Iterable[str]) -> None:
        patterns = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
        if not patterns:
            return
        if pathspec is not None:
            spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
            self.rules.append((base, spec))
        else:
            self.fallback_rules.append((base, patterns))

    def _load_rules(self) -> None:
        if self.use_gitignore:
            for ignore_file in self.root.rglob(".gitignore"):
                if any(part in DEFAULT_IGNORE_DIRS for part in ignore_file.relative_to(self.root).parts):
                    continue
                self._add_rules(ignore_file.parent, ignore_file.read_text(encoding="utf-8", errors="replace").splitlines())
        repopack = self.root / ".repopackignore"
        if repopack.is_file():
            self._add_rules(self.root, repopack.read_text(encoding="utf-8", errors="replace").splitlines())
        self._add_rules(self.root, self.extra_patterns)

    def matches(self, path: Path) -> bool:
        if path.name in {".gitignore", ".repopackignore"}:
            return True
        relative = path.relative_to(self.root)
        if any(part in DEFAULT_IGNORE_DIRS for part in relative.parts[:-1] if path.is_file()):
            return True
        if path.is_dir() and path.name in DEFAULT_IGNORE_DIRS:
            return True
        if path.is_file() and (path.name.lower() in DEFAULT_IGNORE_FILES or path.suffix.lower() == ".pyc"):
            return True
        matched = False
        for base, spec in self.rules:
            try:
                candidate = path.relative_to(base).as_posix()
            except ValueError:
                continue
            if spec.match_file(candidate):
                matched = True
        for base, patterns in self.fallback_rules:
            try:
                candidate = path.relative_to(base).as_posix()
            except ValueError:
                continue
            for pattern in patterns:
                negated = pattern.startswith("!")
                expression = pattern[1:] if negated else pattern
                current = fnmatch.fnmatch(candidate, expression) or fnmatch.fnmatch(path.name, expression)
                if current:
                    matched = not negated
        return matched


def is_sensitive(path: Path) -> bool:
    name = path.name.lower()
    return any(fnmatch.fnmatch(name, pattern.lower()) for pattern in SENSITIVE_PATTERNS)


def classify_file(path: Path) -> tuple[str | None, str | None]:
    if is_sensitive(path):
        return None, "sensitive"
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return None, "binary"
    try:
        data = path.read_bytes()
    except OSError as error:
        return None, f"unreadable: {error.strerror or 'permission denied'}"
    if b"\x00" in data[:8192]:
        return None, "binary"
    return data.decode("utf-8", errors="replace"), None


def _relative(path: Path, root: Path) -> str:
    return path.name if path == root else path.relative_to(root).as_posix()


def scan(target: Path, include_globs: Iterable[str] = (), use_gitignore: bool = True,
         extra_patterns: Iterable[str] = (), progress: Callable[[int], None] | None = None) -> list[FileEntry]:
    target = target.resolve()
    root = target if target.is_dir() else target.parent
    matcher = IgnoreMatcher(root, use_gitignore, extra_patterns)
    includes = tuple(include_globs)
    entries: list[FileEntry] = []
    processed = 0

    def add_file(path: Path) -> None:
        nonlocal processed
        relative = _relative(path, root)
        if includes and not any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern) for pattern in includes):
            return
        content, reason = classify_file(path)
        entries.append(FileEntry(relative, content, reason))
        processed += 1
        if progress:
            progress(processed)

    if target.is_file():
        add_file(target)
        return entries
    if not target.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {target}")

    for current, directories, files in os.walk(target, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_directories = []
        for name in sorted(directories, key=str.lower):
            directory = current_path / name
            relative = _relative(directory, root)
            if matcher.matches(directory):
                entries.append(FileEntry(relative, reason="ignored", is_directory=True))
            else:
                kept_directories.append(name)
        directories[:] = kept_directories
        for name in sorted(files, key=str.lower):
            path = current_path / name
            relative = _relative(path, root)
            if matcher.matches(path):
                if not includes or any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern) for pattern in includes):
                    entries.append(FileEntry(relative, reason="ignored"))
                    processed += 1
                    if progress:
                        progress(processed)
            else:
                add_file(path)
    return sorted(entries, key=lambda entry: (entry.path.lower(), not entry.is_directory))


def get_token_counter(disabled: bool = False) -> Callable[[str], int]:
    if disabled:
        return lambda text: 0
    try:
        import tiktoken
        encoder = tiktoken.get_encoding("cl100k_base")
        return lambda text: len(encoder.encode(text))
    except ImportError:
        return lambda text: max(1, len(text) // 4) if text else 0


def _compact_structure(entries: list[FileEntry], root_name: str, max_lines: int) -> str:
    included = [entry for entry in entries if not entry.skipped and not entry.is_directory]
    skipped = [entry for entry in entries if entry.skipped and not entry.is_directory]
    top_level: dict[str, list[FileEntry]] = {}
    for entry in entries:
        top_level.setdefault(Path(entry.path).parts[0], []).append(entry)

    lines = [root_name, "(Detailed structure omitted because it exceeds the 20-line limit.)"]
    for name in sorted(top_level, key=str.lower):
        group = top_level[name]
        file_count = sum(not entry.is_directory for entry in group)
        directory_count = sum(entry.is_directory for entry in group)
        details = []
        if directory_count:
            details.append(f"{directory_count} directories")
        if file_count:
            details.append(f"{file_count} files")
        lines.append(f"- {name}/ ({', '.join(details)})")

    lines.append(f"Total: {len(included)} included files, {len(skipped)} skipped files")
    return "\n".join(lines[:max_lines])


def build_tree(entries: Iterable[FileEntry], root_name: str = ".", max_lines: int = 20) -> str:
    entries = list(entries)
    tree: dict[str, dict] = {}
    annotations: dict[tuple[str, ...], str] = {}
    for entry in entries:
        parts = tuple(Path(entry.path).parts)
        branch = tree
        for part in parts:
            branch = branch.setdefault(part, {})
        if entry.reason:
            annotations[parts] = f" (skipped: {entry.reason})"

    lines = [root_name]

    def render(branch: dict[str, dict], prefix: str, parent: tuple[str, ...]) -> None:
        children = list(branch.items())
        for index, (name, nested) in enumerate(children):
            last = index == len(children) - 1
            marker = "`-- " if last else "|-- "
            path = parent + (name,)
            lines.append(f"{prefix}{marker}{name}{annotations.get(path, '')}")
            if nested:
                render(nested, prefix + ("    " if last else "|   "), path)

    render(tree, "", ())
    if len(lines) > max_lines:
        return _compact_structure(entries, root_name, max_lines)
    return "\n".join(lines)


def language_for(path: str) -> str:
    extension = Path(path).suffix.lower().lstrip(".")
    return {"py": "python", "js": "javascript", "ts": "typescript", "c": "c", "h": "c"}.get(extension, extension)


def summary_for(entries: list[FileEntry], tokens_enabled: bool) -> dict[str, int]:
    included = [entry for entry in entries if not entry.skipped and not entry.is_directory]
    skipped = [entry for entry in entries if entry.skipped and not entry.is_directory]
    return {
        "files_scanned": len(included) + len(skipped),
        "files_included": len(included),
        "files_skipped": len(skipped),
        "tokens": sum(entry.tokens for entry in included) if tokens_enabled else 0,
    }


def format_markdown(tree: str, entries: list[FileEntry], summary: dict[str, int]) -> str:
    sections = [
        "# Repository Bundle",
        "",
        "## Summary",
        "",
        f"Included: {summary['files_included']} files",
        f"Skipped: {summary['files_skipped']} files",
        f"Tokens: {summary['tokens']}",
        "",
        "## Structure Overview",
        "",
        "```text",
        tree,
        "```",
        "",
        "## File Contents",
    ]
    for entry in entries:
        if entry.skipped or entry.is_directory:
            continue
        sections.extend(["", f"### `{entry.path}`", f"```{language_for(entry.path)}", entry.content or "", "```"])
    sections.append("")
    return "\n".join(sections)


def format_xml(tree: str, entries: list[FileEntry], summary: dict[str, int]) -> str:
    repository = ET.Element("repository")
    ET.SubElement(repository, "summary", {key: str(value) for key, value in summary.items()})
    ET.SubElement(repository, "tree").text = tree
    files = ET.SubElement(repository, "files")
    for entry in entries:
        if entry.is_directory:
            continue
        element = ET.SubElement(files, "file", path=entry.path, skipped=str(entry.skipped).lower())
        if entry.reason:
            element.set("reason", entry.reason)
        else:
            element.set("tokens", str(entry.tokens))
            element.text = entry.content or ""
    return ET.tostring(repository, encoding="unicode", short_empty_elements=False)


def format_json(tree: str, entries: list[FileEntry], summary: dict[str, int]) -> str:
    files = []
    for entry in entries:
        if entry.is_directory:
            continue
        files.append({"path": entry.path, "skipped": entry.skipped, "reason": entry.reason, "tokens": entry.tokens, "content": entry.content})
    return json.dumps({"summary": summary, "tree": tree, "files": files}, indent=2, ensure_ascii=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pack a local repository or file for LLM input.")
    parser.add_argument("--path", required=True, help="File or directory to pack")
    parser.add_argument("--format", choices=("md", "xml", "json"), default="md", help="Output format")
    parser.add_argument("--output", help="Output file path; defaults to OneShot-output.<format>")
    parser.add_argument("--include", action="append", default=[], help="Include glob; repeatable")
    parser.add_argument("--ignore", action="append", default=[], help="Additional ignore glob; repeatable")
    parser.add_argument("--no-gitignore", action="store_true", help="Do not read .gitignore files")
    parser.add_argument("--no-tokens", action="store_true", help="Disable token counting")
    parser.add_argument("--no-progress", action="store_true", help="Disable CLI progress reporting")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        print(f"error: input path does not exist: {target}", file=sys.stderr)
        return 2
    output = Path(args.output or f"OneShot-output.{args.format}").expanduser().resolve()
    try:
        if output == target or (target.is_dir() and target in output.parents):
            print("error: output must not be inside the input path", file=sys.stderr)
            return 2
        progress = ProgressReporter(enabled=None if not args.no_progress else False)
        entries = scan(
            target,
            args.include,
            not args.no_gitignore,
            args.ignore,
            progress=lambda current: progress.update("Scanning files", current),
        )
        progress.finish(f"Scanning complete: {len(entries)} files")
        counter = get_token_counter(args.no_tokens)
        files_to_process = [entry for entry in entries if not entry.skipped and not entry.is_directory]
        for current, entry in enumerate(files_to_process, start=1):
            entry.tokens = counter(entry.content or "")
            progress.update("Counting tokens", current, len(files_to_process))
        progress.finish("Token counting complete")
        summary = summary_for(entries, not args.no_tokens)
        tree = build_tree(entries, target.name if target.is_dir() else target.parent.name)
        if args.format == "md":
            document = format_markdown(tree, entries, summary)
        elif args.format == "xml":
            document = format_xml(tree, entries, summary)
        else:
            document = format_json(tree, entries, summary)
        progress.update("Writing output", 0, 1)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(document, encoding="utf-8")
        progress.finish("Writing output complete")
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Included {summary['files_included']} files; skipped {summary['files_skipped']}; tokens {summary['tokens']}")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
