# Building a Python GUI and Windows Installer

This guide explains how OneShot grew from a command-line Python script into a Windows desktop application with an installer. It is written as a practical tutorial so the same process can be reused for future projects.

The examples use OneShot, but the ideas apply to many small Python tools.

## 1. Start with a command-line core

A good GUI project starts with application logic that does not depend on the GUI.

OneShot's core responsibilities are in `OneShot.py`:

- Find files in a project
- Apply ignore rules
- Read text files safely
- Count tokens
- Build a tree representation
- Render Markdown, XML, or JSON

The command-line entry point is near the bottom of the file:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

The important design idea is that functions such as `scan()`, `build_tree()`, and `render_document()` can be called by both the CLI and the GUI.

### Why separate the core?

If file scanning is implemented directly inside button callbacks, the code becomes difficult to test and reuse. Keeping the core independent gives you:

- A CLI that still works
- A GUI that can call the same behavior
- Unit tests that do not need to open a window
- Fewer differences between command-line and GUI results

A useful rule is:

> The GUI should collect user choices and display results. The core should perform the actual work.

## 2. Create a basic tkinter window

`tkinter` is Python's standard GUI toolkit. It is a practical starting point because it is included with normal Windows Python installations and does not require a separate GUI runtime.

A minimal window looks like this:

```python
import tkinter as tk


window = tk.Tk()
window.title("My Tool")
window.geometry("500x300")

label = tk.Label(window, text="Hello")
label.pack(padx=20, pady=20)

window.mainloop()
```

The important parts are:

- `tk.Tk()` creates the application window.
- Widgets such as `Label`, `Button`, and `Entry` create controls.
- `pack()`, `grid()`, or `place()` positions widgets.
- `mainloop()` keeps the window open and processes user input.

OneShot uses `ttk`, tkinter's themed widget set, for controls such as buttons, entries, comboboxes, progress bars, and the tree view.

## 3. Use variables for control values

Tkinter variables connect widgets to Python state:

```python
folder_var = tk.StringVar()

folder_entry = ttk.Entry(window, textvariable=folder_var)
folder_entry.pack(fill="x")

folder_var.set("C:/Projects/example")
print(folder_var.get())
```

Common variable types are:

- `StringVar` for text
- `BooleanVar` for checkboxes
- `IntVar` for integers
- `DoubleVar` for decimal values

OneShot uses variables for the project folder, include patterns, ignore patterns, output path, format, and checkboxes.

## 4. Connect buttons to functions

A button calls a function through its `command` option:

```python
def choose_folder():
    print("The user clicked Browse")


button = ttk.Button(window, text="Browse...", command=choose_folder)
```

A callback should be short. It usually validates input, starts work, and updates the interface. The callback should not contain a large file-processing algorithm.

For example, the OneShot scan button calls `_start_scan()`. That method validates the folder and starts a worker thread. The worker calls `_scan_worker()` and sends its result back to the GUI.

## 5. Choose a layout manager

Tkinter has three layout managers:

- `pack()` is convenient for simple vertical or horizontal layouts.
- `grid()` is best for forms with rows and columns.
- `place()` positions widgets at exact coordinates and is rarely suitable for resizable applications.

OneShot uses `grid()` for its form and output controls:

```python
settings.columnconfigure(1, weight=1)

label.grid(row=0, column=0, sticky="w")
entry.grid(row=0, column=1, sticky="ew")
button.grid(row=0, column=2)
```

`columnconfigure(..., weight=1)` tells tkinter which column should grow when the window is resized. `sticky="ew"` makes an entry stretch horizontally.

Use frames to divide a window into logical regions:

- Settings at the top
- Main project tree in the middle
- Actions and status at the bottom

## 6. Browse for files and folders

Use tkinter's file dialogs instead of asking users to type paths:

```python
from tkinter import filedialog


def browse_folder():
    selected = filedialog.askdirectory(title="Choose a project folder")
    if selected:
        folder_var.set(selected)
```

For output files, use `asksaveasfilename()`:

```python
selected = filedialog.asksaveasfilename(
    defaultextension=".md",
    filetypes=[("Markdown", "*.md"), ("All files", "*.*")],
)
```

Always validate the result before starting work. A user can cancel a dialog, so the returned value may be empty.

## 7. Build a selectable project tree

`ttk.Treeview` displays hierarchical data:

```python
tree = ttk.Treeview(window, columns=("path", "status"), show="tree headings")
tree.heading("#0", text="Name")
tree.heading("path", text="Path")
tree.heading("status", text="Status")
```

Insert a row with a parent item ID:

```python
root_id = tree.insert("", "end", text="Project", open=True)
file_id = tree.insert(root_id, "end", text="main.py", values=("main.py", "included"))
```

For OneShot, each row stores a relative path in `item_paths`. When a row is clicked, the program:

1. Finds the row's relative path.
2. Finds all selectable files at or below that path.
3. Adds or removes those paths from the `checked` set.
4. Refreshes the checkbox image and status for every affected row.

This makes one implementation support both individual files and folders.

### Checkbox images

A standard `Treeview` does not provide native checkboxes in its rows. OneShot creates small `tk.PhotoImage` objects for:

- Checked
- Unchecked
- Partially selected
- Skipped

The image is placed in the tree row with the `image` option. The partial state is calculated from the child files:

- All selected: checked
- None selected: unchecked
- Some selected: partial

The important lesson is to keep the selection state in Python, not in the displayed text. The image is only a visual representation of `self.checked`.

## 8. Keep the GUI responsive with threads

File scanning and token counting can take a long time. If that work runs directly in a button callback, tkinter cannot redraw the window until the work finishes. The application appears frozen.

OneShot uses a worker thread:

```python
threading.Thread(
    target=self._scan_worker,
    args=(folder,),
    daemon=True,
).start()
```

The worker must not update tkinter widgets directly. Tkinter widgets should be changed only from the main GUI thread.

OneShot uses a `queue.Queue`:

```python
self.queue.put(("scan", entries))
```

The GUI checks the queue periodically:

```python
self.after(100, self._process_queue)
```

This pattern is safe and simple:

1. Main thread starts the worker.
2. Worker performs scanning or generation.
3. Worker puts a result or error in the queue.
4. Main thread reads the queue and updates widgets.

## 9. Handle errors at the user boundary

Core functions can raise useful Python exceptions. The GUI should catch them at the worker boundary and display a readable message:

```python
try:
    entries = scan(folder)
except Exception as error:
    self.queue.put(("error", str(error)))
```

Then the main thread can show:

```python
messagebox.showerror("OneShot", message)
```

Do not silently ignore errors. A user needs to know whether the path was invalid, a file could not be read, or the output could not be written.

## 10. Test the core separately from the GUI

GUI tests can be complicated because they require a display and user events. Test the file-processing core with ordinary unit tests first.

OneShot's tests create a temporary project:

```python
self.temp_dir = tempfile.TemporaryDirectory()
self.root = Path(self.temp_dir.name)
```

Then they test behavior such as:

- Sensitive files are not read
- Binary files are skipped
- Include patterns match nested files
- Manual deselection changes the summary
- Markdown, XML, and JSON preserve content
- The preview scan avoids reading file contents

Run the tests with:

```powershell
python -m unittest discover -s tests
```

A good development loop is:

1. Change one behavior.
2. Add or update a focused test.
3. Run the test suite.
4. Start the GUI and manually check the related workflow.

## 11. Package a Python GUI with PyInstaller

Python source files normally require Python and installed packages. PyInstaller bundles the application and its dependencies into an executable directory.

The project configuration is in `packaging/OneShot.spec`:

- `Analysis` identifies the entry script and imports.
- `PYZ` packages Python bytecode.
- `EXE` creates the Windows executable.
- `COLLECT` creates the onedir output directory.
- `console=False` prevents a terminal window from opening.
- `upx=False` avoids a compression technique that can increase antivirus false positives.

The GUI entry point is `OneShot_gui.py`, not `OneShot.py`, because the GUI is the application users launch.

Build the executable with:

```powershell
python -m pip install -r requirements.txt
python packaging/prepare_tiktoken_cache.py
pyinstaller --clean --noconfirm packaging/OneShot.spec
```

The result is placed in:

```text
dist/OneShot/OneShot.exe
```

## 12. Bundle runtime data

Some libraries need data files in addition to Python code. `tiktoken` needs tokenizer data for exact token counts.

The preparation script downloads that data once into `assets/tiktoken_cache`. The PyInstaller spec includes that directory in the application. The cache is ignored by Git because it is generated during the build.

This line in `OneShot.py` points tiktoken to the bundled location:

```python
os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(resource_root / "tiktoken_cache"))
```

For a packaged application, PyInstaller exposes bundled resources through `sys._MEIPASS`. The code supports both packaged execution and normal source execution.

## 13. Create a normal Windows installer

PyInstaller creates an application bundle, but it does not create a normal Windows installation experience by itself. Inno Setup creates an installer that can:

- Install under Program Files
- Create a Start Menu shortcut
- Offer a desktop shortcut
- Register an uninstaller
- Copy all files from the PyInstaller output directory

The configuration is `packaging/installer.iss`. The build script finds Inno Setup in PATH or common per-user/system installation locations.

Install Inno Setup on a development machine:

```powershell
winget install --id JRSoftware.InnoSetup -e
```

Build the installer:

```powershell
.\packaging\build.ps1
```

The result is:

```text
dist/installer/OneShot-Setup.exe
```

The build script performs the complete sequence:

1. Installs Python dependencies.
2. Prepares tokenizer data.
3. Builds the PyInstaller application.
4. Compiles the Inno Setup installer.

## 14. Understand antivirus warnings

Unsigned, locally built PyInstaller applications can trigger Microsoft Defender or company endpoint security software. This does not prove that the application is malicious, but it does mean the binary has not established publisher trust.

OneShot reduces common false-positive triggers by disabling UPX compression. However, a professional distributed application should eventually use:

- A code-signing certificate
- Reproducible release builds
- Virus scanning before publication
- An IT/security allow-list for company environments

Do not disable antivirus protection on an office-managed computer. Ask the organization's IT/security team to review or approve the installer.

## 15. Automate builds with GitHub Actions

GitHub Actions is a hosted automation system. A workflow is a YAML file, not a Dockerfile. It describes commands that GitHub runs on a temporary machine.

OneShot's workflow is:

```text
.github/workflows/build-installer.yml
```

The workflow does the following:

1. Checks out the repository.
2. Installs Python 3.12.
3. Installs Inno Setup on a Windows runner.
4. Runs `packaging/build.ps1`.
5. Uploads the installer as a workflow artifact.
6. For a version tag, creates a GitHub Release and attaches the installer.

The relevant trigger section is:

```yaml
on:
  push:
    tags:
      - "v*"
  workflow_dispatch:
```

`workflow_dispatch` enables a **Run workflow** button for manual testing. The tag trigger means a tag such as `v1.0.0` starts a release build.

The release command uses the built-in GitHub token:

```yaml
env:
  GH_TOKEN: ${{ github.token }}
```

The workflow needs permission to create releases:

```yaml
permissions:
  contents: write
```

### Use GitHub Actions on a personal GitHub account

For a personal GitHub repository:

1. Create or open the repository on GitHub.
2. Commit and push `.github/workflows/build-installer.yml`.
3. Open the repository's **Actions** tab.
4. Select **Build Windows Installer**.
5. Use **Run workflow** to test it on the `main` branch.
6. Open the completed run and download the `OneShot-Windows-Installer` artifact.
7. When ready to publish, create and push a version tag.

From PowerShell:

```powershell
git add .github/workflows/build-installer.yml
git commit -m "Add automated Windows installer releases"
git push origin main

git tag v1.0.0
git push origin v1.0.0
```

The tag starts a new run. If it succeeds, go to **Code > Releases** and open the new release. Users can download `OneShot-Setup.exe` directly without cloning the source repository.

A typical release URL is:

```text
https://github.com/<owner>/<repository>/releases/latest/download/OneShot-Setup.exe
```

Replace `<owner>` and `<repository>` with the actual GitHub repository values.

### Versioning future releases

For the next release, update the application version in `packaging/installer.iss`, commit the change, and create a new tag:

```powershell
git tag v1.1.0
git push origin v1.1.0
```

Use:

- `v1.0.0` for the first stable release
- `v1.1.0` for new backward-compatible features
- `v1.1.1` for fixes

Do not reuse a release tag. Create a new tag for every release.

## 16. A reusable project checklist

When turning another Python script into a desktop tool:

1. Move reusable behavior into ordinary Python functions.
2. Keep the CLI working.
3. Add a small tkinter window.
4. Add controls for inputs and outputs.
5. Validate paths and user input.
6. Move slow work to a worker thread.
7. Send worker results through a queue.
8. Add unit tests around the core behavior.
9. Build with PyInstaller.
10. Bundle required runtime data.
11. Create an Inno Setup installer.
12. Test the installed application on a clean machine.
13. Add a GitHub Actions workflow.
14. Publish installers through GitHub Releases.
15. Sign the installer before wider distribution.
