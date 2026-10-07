# OneShot

OneShot packages a project folder or individual file into one document that is easy to provide to an LLM. The generated document contains:

- A compact project structure
- The contents of selected text files
- A summary of included files, skipped files, and token count

Output is available as Markdown, XML, or JSON. OneShot automatically protects common sensitive and binary files, respects repository `.gitignore` files, and ignores common dependency, build, cache, and version-control directories.

## Desktop application

The Windows installer creates a normal Start Menu application. After installation, launch **OneShot** from the Start Menu.

### Search file contents

Open the **Search** tab, choose a folder, enter a file name pattern such as `*.arxml`, then click **Scan**. Select or deselect files and folders in the tree before clicking **Generate**. Enter the line pattern to find; a `*` captures matching text. By default, results contain the captured value; enable **Include look-for text in results** to include the matched fragment. Choose Markdown (`md`), XML (`xml`), JSON (`json`), or plain text (`txt`), and select whether each result is ordered `path : match` or `match : path`. Searches use the same ignored-directory and `.gitignore` rules as project scans.

### Select a project

1. Click **Browse...** beside **Project folder** and choose a project directory.
2. Enter optional **Include patterns**, such as `CMakeLists*.txt` or `*.py`.
3. Click **Scan**, or press Enter while editing an include or ignore pattern.
4. Review the project tree.

The tree provides a checkbox for every selectable file and folder:

- Click a file to include or exclude only that file.
- Click a folder to include or exclude all selectable files inside it.
- A partially selected folder contains both included and excluded files.
- Automatically skipped files remain visible with a reason such as `sensitive`, `binary`, or `ignored`.

### Generate a bundle

1. Optionally enable **Respect .gitignore** and enter ignore patterns.
2. Select the output format: Markdown (`md`), XML (`xml`), or JSON (`json`).
3. Use **Browse...** beside **Output** to choose the destination file.
4. Leave **Count tokens** enabled for exact `cl100k_base` token counts.
5. Click **Generate**.

Include and ignore patterns are glob patterns. Separate multiple patterns with spaces or commas. For example, `CMakeLists*.txt` finds matching files in every scanned subfolder. If no files match, OneShot reports that clearly after scanning.

## Development setup

The project requires Python 3.10 or newer. Create or activate a virtual environment, then install the dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run the GUI directly during development:

```powershell
python OneShot_gui.py
```

Run the test suite:

```powershell
python -m unittest discover -s tests
```

## Command-line usage

The original command-line interface remains available:

```powershell
python OneShot.py --path C:\Projects\my-repo --format md --output repo.md
python OneShot.py --path C:\Projects\my-repo --format xml --output repo.xml
python OneShot.py --path C:\Projects\my-repo --format json --output repo.json
python OneShot.py --path C:\Projects\my-repo\src\main.py --format md
```

The default output is `OneShot-output.<format>` in the current directory. Useful options:

- `--include '*.py'` limits included files; repeat it for multiple patterns.
- `--ignore '*.log'` adds ignore patterns; repeat it as needed.
- `--no-gitignore` disables repository ignore files.
- `--no-tokens` disables token counting.
- `--no-progress` disables CLI progress reporting.

## Build the Windows installer

The installer build uses PyInstaller and Inno Setup. Install Inno Setup 6 from [jrsoftware.org](https://jrsoftware.org/isinfo.php), or with Windows Package Manager:

```powershell
winget install --id JRSoftware.InnoSetup -e
```

Then run the build script from the repository root:

```powershell
.\packaging\build.ps1
```

The script:

1. Installs the Python build dependencies.
2. Downloads the `cl100k_base` tokenizer data into the local build cache.
3. Builds the GUI with PyInstaller.
4. Builds the Windows installer with Inno Setup.

Generated files are placed in ignored directories:

- `dist/OneShot/` contains the unpacked application.
- `dist/installer/OneShot-Setup.exe` is the installable package.

The tokenizer cache and all build output are intentionally ignored by Git. The build machine needs internet access the first time the tokenizer cache is prepared. The resulting application can count tokens offline.

### Antivirus and managed devices

The generated binaries are unsigned. Microsoft Defender or an office-managed endpoint security product may quarantine locally built PyInstaller applications. If that happens, ask IT to review and approve the build or use an organization-approved code-signing certificate. Do not disable security controls on a managed device.

## Repository behavior

Sensitive files such as `.env`, private keys, and credential files are never included. Binary files are listed but their contents are omitted. Files skipped by automatic rules remain visible in the structure so the generated document shows what was excluded.
