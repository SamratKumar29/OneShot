# OneShot

`OneShot` packs a local file or directory into one compact document for LLM input. It emits a short directory tree first, followed immediately by included file contents with clear relative paths.

Sensitive files and binary files are listed in the tree but their contents are never included. Built-in ignores cover common dependency, build, cache, VCS, and generated directories. Repository `.gitignore` files and an optional root `.repopackignore` are also respected.

## Setup

The script runs with Python 3.10+ and has a fallback when optional dependencies are unavailable. For accurate token counts and full gitignore matching, install:

```powershell
python -m pip install -r requirements.txt
```

## Usage

```powershell
python OneShot.py --path C:\Projects\my-repo --format md --output repo.md
python OneShot.py --path C:\Projects\my-repo --format xml --output repo.xml
python OneShot.py --path C:\Projects\my-repo --format json --output repo.json
python OneShot.py --path C:\Projects\my-repo\src\main.py --format md
```

The default output is `OneShot-output.<format>` in the current directory. The input path may point anywhere on the machine.

Useful options:

- `--include '*.py'` limits included files; repeat it for more patterns.
- `--ignore '*.log'` adds an ignore pattern; repeat it as needed.
- `--no-gitignore` disables repository ignore files.
- `--no-tokens` disables token counting.
- `--no-progress` disables interactive CLI progress reporting.

Skipped paths remain visible in the structure with a reason such as `sensitive`, `binary`, or `ignored`.
