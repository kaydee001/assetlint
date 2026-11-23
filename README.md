# Asset Lint

A linter for 3D asset folders that runs headless. Put the rules in `assetlint.toml`
and run it from the terminal, in CI or as a pre-commit hook. It does for asset
folders what ESLint does for code.

> Pre-alpha. The core rules work; JSON and SARIF output, per-folder overrides,
> the GitHub Action and the pre-commit hook are next.

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
# Only these file types are checked (the defaults cover common mesh and texture formats).
extensions = [".glb", ".gltf", ".obj", ".png", ".jpg", ".tga"]

# Paths to skip, as globs relative to the checked folder.
exclude = ["build/*", "*_backup.*"]

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
