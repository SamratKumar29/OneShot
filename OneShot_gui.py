"""Desktop interface for selecting and bundling project files."""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from OneShot import FileEntry, apply_manual_deselection, render_document, scan


def patterns_from_text(value: str) -> list[str]:
    return [part for part in value.replace(",", " ").split() if part]


class OneShotApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OneShot")
        self.geometry("980x700")
        self.minsize(760, 520)

        self.folder_var = tk.StringVar()
        self.include_var = tk.StringVar()
        self.ignore_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(Path.cwd() / "OneShot-output.md"))
        self.format_var = tk.StringVar(value="md")
        self.gitignore_var = tk.BooleanVar(value=True)
        self.tokens_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Choose a project folder to begin.")
        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.entries: list[FileEntry] = []
        self.checked: set[str] = set()
        self.item_paths: dict[str, str] = {}
        self.busy = False

        self._create_checkbox_images()
        self._build_ui()
        self.after(100, self._process_queue)

    def _create_checkbox_images(self) -> None:
        self.checkbox_images: dict[str, tk.PhotoImage] = {}
        for state in ("checked", "unchecked", "partial", "skipped"):
            image = tk.PhotoImage(width=16, height=16)
            image.put("#ffffff", to=(0, 0, 15, 15))
            border = "#7f8c8d" if state != "checked" else "#1565c0"
            image.put(border, to=(1, 1, 14, 14))
            if state == "checked":
                image.put("#1976d2", to=(2, 2, 13, 13))
                image.put("#ffffff", to=(4, 8, 5, 9))
                image.put("#ffffff", to=(5, 9, 6, 10))
                image.put("#ffffff", to=(6, 10, 7, 11))
                image.put("#ffffff", to=(7, 9, 8, 10))
                image.put("#ffffff", to=(8, 8, 9, 9))
                image.put("#ffffff", to=(9, 7, 10, 8))
                image.put("#ffffff", to=(10, 6, 11, 7))
            elif state == "partial":
                image.put("#64b5f6", to=(2, 2, 13, 13))
                image.put("#ffffff", to=(4, 7, 11, 9))
            elif state == "skipped":
                image.put("#e0e0e0", to=(2, 2, 13, 13))
                image.put("#9e9e9e", to=(4, 7, 11, 8))
            self.checkbox_images[state] = image

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        settings = ttk.Frame(self, padding=12)
        settings.grid(row=0, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)

        description = ttk.Label(
            settings,
            text="OneShot bundles selected project files into one Markdown, XML, or JSON document for LLM input.",
            wraplength=900,
        )
        description.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        ttk.Label(settings, text="Project folder").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(settings, textvariable=self.folder_var).grid(row=1, column=1, sticky="ew", pady=4)
        self.browse_button = ttk.Button(settings, text="Browse...", command=self._browse_folder)
        self.browse_button.grid(row=1, column=2, padx=(8, 0), pady=4)
        self.scan_button = ttk.Button(settings, text="Scan", command=self._start_scan)
        self.scan_button.grid(row=1, column=3, rowspan=2, sticky="nsew", padx=(8, 0), pady=4)

        ttk.Label(settings, text="Include patterns").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        include_entry = ttk.Entry(settings, textvariable=self.include_var)
        include_entry.grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)
        include_entry.bind("<Return>", lambda _event: self._start_scan())
        ttk.Label(settings, text="Example: CMakeLists*.txt or *.py").grid(row=3, column=1, columnspan=2, sticky="w")

        ttk.Label(settings, text="Ignore patterns").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=4)
        ignore_entry = ttk.Entry(settings, textvariable=self.ignore_var)
        ignore_entry.grid(row=4, column=1, columnspan=2, sticky="ew", pady=4)
        ignore_entry.bind("<Return>", lambda _event: self._start_scan())
        ttk.Checkbutton(settings, text="Respect .gitignore", variable=self.gitignore_var).grid(row=5, column=1, columnspan=2, sticky="w", pady=4)

        tree_frame = ttk.Frame(self, padding=(12, 0, 12, 8))
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_frame, columns=("path", "state"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Project files")
        self.tree.heading("path", text="Relative path")
        self.tree.heading("state", text="Status")
        self.tree.column("#0", width=280, anchor="w")
        self.tree.column("path", width=480, anchor="w")
        self.tree.column("state", width=150, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<ButtonRelease-1>", self._tree_click)

        actions = ttk.Frame(self, padding=(12, 0, 12, 12))
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="Select all", command=lambda: self._set_all(True)).grid(row=0, column=0, padx=(0, 6), pady=4)
        ttk.Button(actions, text="Deselect all", command=lambda: self._set_all(False)).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(actions, text="Format").grid(row=0, column=2, padx=(12, 6))
        self.format_combo = ttk.Combobox(actions, textvariable=self.format_var, values=("md", "xml", "json"), state="readonly", width=7)
        self.format_combo.grid(row=0, column=3)
        ttk.Checkbutton(actions, text="Count tokens", variable=self.tokens_var).grid(row=0, column=4, padx=12)

        ttk.Label(actions, text="Output").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(actions, textvariable=self.output_var).grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)
        self.save_button = ttk.Button(actions, text="Browse...", command=self._save_output)
        self.save_button.grid(row=1, column=4, padx=(8, 0), pady=4)
        self.generate_button = ttk.Button(actions, text="Generate", command=self._start_generate)
        self.generate_button.grid(row=2, column=0, columnspan=5, sticky="e", pady=(8, 0))

        self.progress = ttk.Progressbar(actions, mode="determinate")
        self.progress.grid(row=3, column=0, columnspan=5, sticky="ew", pady=(10, 4))
        ttk.Label(actions, textvariable=self.status_var).grid(row=4, column=0, columnspan=5, sticky="w")

    def _browse_folder(self) -> None:
        selected = filedialog.askdirectory(title="Choose a project folder")
        if selected:
            self.folder_var.set(selected)
            self._start_scan()

    def _save_output(self) -> None:
        extension = self.format_var.get()
        selected = filedialog.asksaveasfilename(
            title="Choose output file",
            defaultextension=f".{extension}",
            filetypes=[("Markdown", "*.md"), ("XML", "*.xml"), ("JSON", "*.json"), ("All files", "*.*")],
        )
        if selected:
            self.output_var.set(selected)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for widget in (self.browse_button, self.scan_button, self.save_button, self.generate_button):
            widget.configure(state=state)

    def _start_scan(self) -> None:
        if self.busy:
            return
        folder = Path(self.folder_var.get()).expanduser()
        if not folder.is_dir():
            messagebox.showerror("Invalid folder", "Choose an existing project folder.")
            return
        self._set_busy(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start(10)
        self.status_var.set("Scanning project structure...")
        threading.Thread(target=self._scan_worker, args=(folder,), daemon=True).start()

    def _scan_worker(self, folder: Path) -> None:
        try:
            include_patterns = patterns_from_text(self.include_var.get())
            entries = scan(
                folder,
                include_patterns,
                self.gitignore_var.get(),
                patterns_from_text(self.ignore_var.get()),
                read_content=False,
            )
            matched_files = sum(not entry.is_directory for entry in entries)
            self.queue.put(("scan", (entries, include_patterns, matched_files)))
        except Exception as error:
            self.queue.put(("error", str(error)))

    def _populate_tree(self, scan_result: tuple[list[FileEntry], list[str], int]) -> None:
        entries, include_patterns, matched_files = scan_result
        self.tree.delete(*self.tree.get_children())
        self.item_paths.clear()
        self.entries = entries
        self.checked = {entry.path for entry in entries if not entry.skipped and not entry.is_directory}
        root_name = Path(self.folder_var.get()).name or "Project"
        root_id = self.tree.insert("", "end", text=root_name, values=("", ""), open=True)
        self.item_paths[root_id] = ""
        nodes: dict[str, str] = {"": root_id}
        for entry in entries:
            parts = Path(entry.path).parts
            parent_key = ""
            for index, part in enumerate(parts):
                key = "/".join(parts[: index + 1])
                if key not in nodes:
                    is_leaf = index == len(parts) - 1
                    item_path = key
                    parent = nodes[parent_key]
                    item_id = self.tree.insert(parent, "end", text="", values=(item_path, ""), open=True)
                    nodes[key] = item_id
                    self.item_paths[item_id] = item_path
                parent_key = key
            self._refresh_item(nodes["/".join(parts)], entry)
        self._refresh_all()
        if include_patterns and matched_files == 0:
            self.status_var.set(f"No files matched: {', '.join(include_patterns)}")
            messagebox.showwarning("No matching files", f"No files matched: {', '.join(include_patterns)}")
        elif include_patterns:
            self.status_var.set(f"Matched {matched_files} files. Select or deselect files to include.")
        else:
            self.status_var.set(f"Found {matched_files} files. Select or deselect files to include.")

    def _descendant_files(self, path: str) -> list[str]:
        prefix = f"{path}/" if path else ""
        return [
            entry.path for entry in self.entries
            if not entry.is_directory and not entry.skipped
            and (not path or entry.path == path or entry.path.startswith(prefix))
        ]

    def _checkbox_state(self, path: str, entry: FileEntry | None) -> str:
        if entry is not None and entry.skipped:
            return "skipped"
        files = self._descendant_files(path)
        if not files or all(file_path in self.checked for file_path in files):
            return "checked"
        if any(file_path in self.checked for file_path in files):
            return "partial"
        return "unchecked"

    def _refresh_item(self, item_id: str, entry: FileEntry | None = None) -> None:
        path = self.item_paths.get(item_id, "")
        current = entry or next((item for item in self.entries if item.path == path), None)
        checkbox_state = self._checkbox_state(path, current)
        if current is None or current.is_directory:
            status = "folder"
        elif current.skipped:
            status = f"skipped: {current.reason}"
        elif path in self.checked:
            status = "included"
        else:
            status = "deselected"
        self.tree.item(
            item_id,
            image=self.checkbox_images[checkbox_state],
            text=Path(path).name if path else Path(self.folder_var.get()).name,
            values=(path, status),
        )

    def _tree_click(self, event: tk.Event) -> str | None:
        item_id = self.tree.identify_row(event.y)
        if not item_id or item_id not in self.item_paths:
            return None
        path = self.item_paths[item_id]
        entry = next((item for item in self.entries if item.path == path), None)
        if entry is not None and entry.skipped:
            return "break"
        descendants = self._descendant_files(path)
        new_value = not descendants or not all(file_path in self.checked for file_path in descendants)
        for descendant in descendants:
            if new_value:
                self.checked.add(descendant)
            else:
                self.checked.discard(descendant)
        self._refresh_all()
        return "break"

    def _refresh_all(self) -> None:
        for item_id in self.item_paths:
            path = self.item_paths[item_id]
            entry = next((item for item in self.entries if item.path == path), None)
            self._refresh_item(item_id, entry)

    def _set_all(self, selected: bool) -> None:
        self.checked = {entry.path for entry in self.entries if selected and not entry.skipped and not entry.is_directory}
        self._refresh_all()

    def _start_generate(self) -> None:
        if self.busy:
            return
        folder = Path(self.folder_var.get()).expanduser()
        output = Path(self.output_var.get()).expanduser()
        if not folder.is_dir():
            messagebox.showerror("Invalid folder", "Choose and scan an existing project folder first.")
            return
        if not output.name:
            messagebox.showerror("Invalid output", "Choose an output file.")
            return
        self._set_busy(True)
        self.progress.configure(mode="determinate", value=0, maximum=100)
        self.status_var.set("Reading selected files...")
        threading.Thread(target=self._generate_worker, args=(folder, output, set(self.checked)), daemon=True).start()

    def _generate_worker(self, folder: Path, output: Path, checked: set[str]) -> None:
        try:
            entries = scan(
                folder,
                patterns_from_text(self.include_var.get()),
                self.gitignore_var.get(),
                patterns_from_text(self.ignore_var.get()),
            )
            apply_manual_deselection(entries, {entry.path for entry in entries if not entry.is_directory and entry.path not in checked})
            document, summary = render_document(
                entries,
                folder.name,
                self.format_var.get(),
                tokens_enabled=self.tokens_var.get(),
                progress=lambda phase, current, total: self.queue.put(("progress", (phase, current, total))),
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(document, encoding="utf-8")
            self.queue.put(("generated", (output, summary)))
        except Exception as error:
            self.queue.put(("error", str(error)))

    def _process_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "scan":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self._populate_tree(payload)  # type: ignore[arg-type]
                    self._set_busy(False)
                elif kind == "progress":
                    phase, current, total = payload  # type: ignore[misc]
                    self.progress.configure(maximum=total or 1, value=current)
                    self.status_var.set(f"{phase} ({current}/{total or 0})")
                elif kind == "generated":
                    output, summary = payload  # type: ignore[misc]
                    self._set_busy(False)
                    self.status_var.set(f"Wrote {output} - {summary['files_included']} files, {summary['tokens']} tokens")
                    if messagebox.askyesno("OneShot", "Bundle created. Open its folder?"):
                        os.startfile(Path(output).parent)  # type: ignore[attr-defined]
                elif kind == "error":
                    self.progress.stop()
                    self._set_busy(False)
                    messagebox.showerror("OneShot", str(payload))
                    self.status_var.set("Operation failed.")
        except queue.Empty:
            pass
        self.after(100, self._process_queue)


if __name__ == "__main__":
    OneShotApp().mainloop()
