# Asset Lint

A linter for 3D asset folders that runs headless. Put the rules in `assetlint.toml`
and run it from the terminal, in CI or as a pre-commit hook. It does for asset
folders what ESLint does for code.

> Pre-alpha: not yet on PyPI. The GitHub Action and pre-commit hook below install
> it straight from this repository.

## The app

```sh
pip install "assetlint[app]"
assetlint app            # or: assetlint app path/to/assets
```

Opens Asset Lint in its own window: pick a folder, see every problem grouped by
file, filter by rule or severity, and change the rules (or start from an Unreal,
Unity or Godot preset) without editing any files by hand. It uses the same
`assetlint.toml` as the command line and CI, so all three agree.

Some problems have a **Fix…** button: rename a badly named file, correct
backslashes or the wrong case in a mesh's texture paths, or move a duplicate to
the trash. Each fix shows every change before it's made, and renaming or
trashing a file also updates the `.gltf`, `.glb`, `.obj` and `.mtl` files that
point at it, plus a Unity `.meta` file next to it. Engine files that point at
assets by path (scenes, Godot `.import`, Unreal `.uasset`) aren't updated.

The window uses the web view your OS already has (Edge WebView2 on Windows,
WebKit on macOS), so it stays small. Without the `app` extra, or with
`--browser`, the same screens open in your browser instead.

## Rules

| Rule         | Checks                                                                 | Default |
| ------------ | ---------------------------------------------------------------------- | ------- |
| `formats`    | Allowed file types; no empty, corrupt or misnamed files (a JPEG saved as `.png`) | error |
| `size`       | File size under a limit, overall or per type                           | error, no limit set |
| `naming`     | File names match a pattern, with a prefix per type (`SM_`, `T_`)       | error |
| `duplicates` | No two files with the same content (BLAKE2b hash), whatever their names | warn |
| `triangles`  | Triangle budget for glTF/GLB and OBJ meshes                            | error, no budget set |
| `textures`   | Power-of-two sizes and a maximum width/height (PNG, JPEG, TGA, TIFF, PSD) | warn |
| `references` | Textures, buffers and `.mtl` files a mesh points at exist, with relative paths whose case matches on Linux | error |

Meshes and images are read from their headers and JSON only, with no Blender
and no pixel decoding, so a check stays fast on large folders. A file that can't
be read is reported once, by `formats`.

## Try it

```sh
uv run assetlint check samples/bad
```

```
SM_Chair.obj
  error  references  references 'textures/t_chair_d.png' (in 'SM_Chair.mtl'), but it's 'textures/T_Chair_D.png' on disk; the case must match on Linux

SM_Dense.obj
  error  triangles   600 triangles, over the budget of 500

T_Fake_D.png
  error  formats     it's a JPEG image with a .png extension
  ...
Found 17 problems (17 errors, 0 warnings) in 17 files.
```

The command exits with 0 when there are no errors, 1 when a rule reports an error,
and 2 when the config is invalid. Warnings never fail the run.

## Config

`assetlint check <folder>` uses the nearest `assetlint.toml` in that folder or one
of its parents, or `--config <file>`. With no config it uses the defaults: every
rule is on, but budgets (size, triangles, texture size) stay off until you set them.

```toml
# Start from an engine's conventions: "unreal", "unity" or "godot". Optional;
# anything set below wins over the preset.
preset = "unreal"

# Only these file types are checked (the defaults cover common mesh and texture formats).
extensions = [".glb", ".gltf", ".obj", ".png", ".jpg", ".tga"]

# Paths to skip. Paths are relative to this file's folder, `*` matches across
# folders, and a pattern ending in `/` matches everything in that folder.
exclude = ["build/", "*_backup.*"]

# Every rule takes severity = "error", "warn" or "off".

[rules.formats]
allowed = [".glb", ".png", ".jpg"]   # default: any checked type

[rules.size]
max = "50MB"                         # KB/MB/GB are powers of 1000, KiB/MiB/GiB of 1024
max_by_type = { ".png" = "8MB" }

[rules.naming]
pattern = "[A-Za-z0-9_\\-]+"        # the whole file name, without its extension, must match
prefixes = { ".glb" = "SM_", ".png" = "T_" }

[rules.duplicates]
severity = "warn"

[rules.triangles]
max = 20000                          # per file; each mesh counted once

[rules.textures]
power_of_two = true
max_size = 4096                      # largest width or height, in pixels

[rules.references]
severity = "error"
```

Unknown keys are reported as errors, so a typo can't switch a rule off without you noticing.

### Per-folder overrides

Give some folders different settings with `[[overrides]]`. Each one applies on top
of `[rules]` to the paths it matches, and when several match, the last one wins.
Only the keys you set change; tables such as `prefixes` merge key by key.

```toml
[rules.triangles]
max = 5000

[[overrides]]
paths = ["characters/"]
rules.triangles.max = 50000

[[overrides]]
paths = ["legacy/"]
rules.naming.severity = "off"
```

## Output

`--format` picks the report and `--output FILE` writes it to a file instead of the terminal.

| Format   | For |
| -------- | --- |
| `text`   | People (the default) |
| `json`   | Scripts: every finding with its path, rule, severity and message |
| `sarif`  | GitHub code scanning and other SARIF 2.1.0 tools |
| `github` | GitHub Actions annotations on the files, plus a table of every finding in the job summary |

## GitHub Action

```yaml
# .github/workflows/assets.yml
name: Assets
on: [push, pull_request]

jobs:
  assetlint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          lfs: true          # if your assets are in Git LFS
      - uses: kaydee001/assetlint@main
        with:
          path: assets       # default: the whole repository
```

Problems show up as annotations on the run and on the pull request. GitHub shows
the first 10 errors and 10 warnings of a step there; the job summary lists them all.

For code scanning alerts as well (public repositories, or private ones with
GitHub Advanced Security), write SARIF and upload it. Code scanning only keeps
alerts for text files (`.obj`, `.gltf`), not binary ones (`.png`, `.glb`), so
keep the annotations as the main report:

```yaml
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@v7
      - uses: kaydee001/assetlint@main
        with:
          sarif-file: assetlint.sarif
      - uses: github/codeql-action/upload-sarif@v4
        if: always()
        with:
          sarif_file: assetlint.sarif
```

## pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/kaydee001/assetlint
    rev: main
    hooks:
      - id: assetlint
```

The hook runs when an asset or `assetlint.toml` changes, and checks the whole
repository, because duplicates and missing references need to see every file.

## Develop

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
uv run mypy
uv run python tests/make_samples.py   # rebuild samples/ after changing it
```

## Licence

MIT
