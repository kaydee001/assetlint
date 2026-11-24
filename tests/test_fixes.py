"""The app's fixes: planning a rename, path repair or duplicate removal, and applying it."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import pytest
from make_samples import glb_bytes, gltf_doc, image_bytes, obj_text

from assetlint.app import api, fixes
from assetlint.config import NamingRuleConfig
from assetlint.readers import MeshInfo
from assetlint.readers.gltf import read_gltf


@pytest.fixture(autouse=True)
def state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "STATE_FILE", tmp_path / "state" / "app.json")


@pytest.fixture
def trash(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Record what would go to the trash, and delete it, instead of using the real trash."""
    sent: list[Path] = []

    def fake(path: Path) -> None:
        sent.append(Path(path))
        Path(path).unlink()

    import send2trash

    monkeypatch.setattr(send2trash, "send2trash", fake)
    return sent


def write(root: Path, rel: str, content: str | bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode() if isinstance(content, str) else content)
    return path


def fixes_for(folder: Path, rel: str, name: str | None = None) -> dict[str, Any]:
    return {f["id"]: f for f in fixes.list_fixes(str(folder), rel, name)["fixes"]}


def apply(folder: Path, rel: str, fix: dict[str, Any], name: str | None = None) -> None:
    fixes.apply_fix(str(folder), rel, fix["id"], fix["fingerprint"], name)


def gltf_text(images: list[str]) -> str:
    doc, _ = gltf_doc(images=images)
    return json.dumps(doc, indent=2)


# --- suggested names -------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "prefixes", "expected"),
    [
        ("Cube.001.obj", {}, "Cube.obj"),
        ("rock wall.png", {".png": "T_"}, "T_rock_wall.png"),
        ("t_rock.png", {".png": "T_"}, "T_rock.png"),
        ("Crate.GLB", {".glb": "SM_"}, "SM_Crate.GLB"),
        ("  .png", {}, "asset.png"),
    ],
)
def test_suggest_name(name: str, prefixes: dict[str, str], expected: str) -> None:
    assert fixes.suggest_name(name, NamingRuleConfig(prefixes=prefixes)) == expected


# --- rename ----------------------------------------------------------------------


def test_rename_updates_every_file_that_points_at_it(tmp_path: Path) -> None:
    write(tmp_path, "tex/rock wall.png", image_bytes(4, 4))
    write(tmp_path, "tex/rock wall.png.meta", "guid: 1\n")
    write(tmp_path, "Rock.gltf", gltf_text(["tex/rock%20wall.png"]))
    # an .mtl with texture options and Windows line endings, used by an OBJ elsewhere
    mtl = "newmtl rock\r\nmap_Kd -s 2 2 1 -bm 0.5 tex/rock wall.png\r\nKd 1 1 1\r\n"
    write(tmp_path, "Rock.mtl", mtl)
    write(tmp_path, "Rock.obj", obj_text(mtllib="Rock.mtl"))

    fix = fixes_for(tmp_path, "tex/rock wall.png")["rename"]
    assert fix["name"] == "rock_wall.png"
    kinds = sorted((c["kind"], c["path"]) for c in fix["changes"])
    assert kinds == [
        ("edit", "Rock.gltf"),
        ("edit", "Rock.mtl"),
        ("rename", "tex/rock wall.png"),
        ("rename", "tex/rock wall.png.meta"),
    ]
    apply(tmp_path, "tex/rock wall.png", fix)

    assert (tmp_path / "tex/rock_wall.png").is_file()
    assert (tmp_path / "tex/rock_wall.png.meta").read_text() == "guid: 1\n"
    assert not (tmp_path / "tex/rock wall.png").exists()
    gltf = (tmp_path / "Rock.gltf").read_text()
    assert '"uri": "tex/rock_wall.png"' in gltf
    assert gltf.startswith('{\n  "asset"')  # the rest of the file is untouched
    assert (tmp_path / "Rock.mtl").read_bytes() == mtl.replace(
        "rock wall.png", "rock_wall.png"
    ).encode()
    assert api.check(str(tmp_path))["findings"] == []


def test_rename_updates_an_obj_mtllib(tmp_path: Path) -> None:
    write(tmp_path, "assetlint.toml", '[rules.naming]\nprefixes = { ".obj" = "SM_" }\n')
    write(tmp_path, "pot.obj", obj_text(mtllib="pot.mtl"))
    write(tmp_path, "pot.mtl", "newmtl a\n")
    # the .mtl isn't a checked type, so its name can be anything: rename the OBJ
    fix = fixes_for(tmp_path, "pot.obj")["rename"]
    assert fix["name"] == "SM_pot.obj"
    apply(tmp_path, "pot.obj", fix)
    assert "mtllib pot.mtl" in (tmp_path / "SM_pot.obj").read_text()


def test_rename_uses_the_name_typed(tmp_path: Path) -> None:
    write(tmp_path, "Cube.001.obj", obj_text())
    fix = fixes_for(tmp_path, "Cube.001.obj", name="Crate.obj")["rename"]
    assert fix["blocked"] is None
    apply(tmp_path, "Cube.001.obj", fix, name="Crate.obj")
    assert (tmp_path / "Crate.obj").is_file()


def test_rename_refuses_a_name_that_is_taken(tmp_path: Path) -> None:
    write(tmp_path, "Cube.obj", obj_text())
    write(tmp_path, "Cube.001.obj", obj_text(2))
    fix = fixes_for(tmp_path, "Cube.001.obj")["rename"]
    assert "already exists" in fix["blocked"]
    with pytest.raises(api.ApiError, match="already exists"):
        apply(tmp_path, "Cube.001.obj", fix)
    assert (tmp_path / "Cube.001.obj").is_file()


def test_rename_can_change_only_the_case(tmp_path: Path) -> None:
    write(tmp_path, "assetlint.toml", '[rules.naming]\npattern = "[A-Z][A-Za-z]+"\n')
    write(tmp_path, "crate.obj", obj_text())
    fix = fixes_for(tmp_path, "crate.obj", name="Crate.obj")["rename"]
    assert fix["blocked"] is None
    apply(tmp_path, "crate.obj", fix, name="Crate.obj")
    assert [p.name for p in tmp_path.glob("*.obj")] == ["Crate.obj"]


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", "Type a new name"),
        ("a/b.obj", "can't contain"),
        ("Crate.fbx", "Keep the .obj extension"),
        ("CON.obj", "reserved"),
        ("Crate.obj.", "can't end"),
    ],
)
def test_rename_refuses_bad_names(tmp_path: Path, name: str, message: str) -> None:
    write(tmp_path, "Cube.001.obj", obj_text())
    assert message in fixes_for(tmp_path, "Cube.001.obj", name=name)["rename"]["blocked"]


def test_rename_warns_when_the_name_still_breaks_the_rule(tmp_path: Path) -> None:
    write(tmp_path, "Cube.001.obj", obj_text())
    fix = fixes_for(tmp_path, "Cube.001.obj", name="Big Crate.obj")["rename"]
    assert fix["blocked"] is None
    assert any("naming pattern" in note for note in fix["notes"])


def test_rename_follows_overrides(tmp_path: Path) -> None:
    write(
        tmp_path,
        "assetlint.toml",
        '[[overrides]]\npaths = ["props/"]\nrules.naming.prefixes = { ".png" = "T_" }\n',
    )
    write(tmp_path, "props/wood.png", image_bytes(4, 4))
    assert fixes_for(tmp_path, "props/wood.png")["rename"]["name"] == "T_wood.png"


def test_rename_rewrites_a_glb_and_keeps_it_valid(tmp_path: Path) -> None:
    write(tmp_path, "my tex.png", image_bytes(4, 4))
    doc, data = gltf_doc(images=["my%20tex.png"])
    write(tmp_path, "SM_Box.glb", glb_bytes(doc, data))

    apply(tmp_path, "my tex.png", fixes_for(tmp_path, "my tex.png")["rename"])

    raw = (tmp_path / "SM_Box.glb").read_bytes()
    _, _, total = struct.unpack_from("<4sII", raw)
    length, _ = struct.unpack_from("<I4s", raw, 12)
    assert total == len(raw)
    assert length % 4 == 0
    mesh = read_gltf(tmp_path / "SM_Box.glb")
    assert isinstance(mesh, MeshInfo)
    assert [r.raw for r in mesh.references] == ["my_tex.png"]
    assert raw.endswith(data)  # the binary chunk is still there, unchanged


# --- path repairs -------------------------------------------------------------------


def test_repairs_backslashes_and_case(tmp_path: Path) -> None:
    write(tmp_path, "Textures/Wood.png", image_bytes(4, 4))
    write(tmp_path, "Textures/Bark.png", image_bytes(4, 4, color=(1, 2, 3)))
    write(tmp_path, "Tree.mtl", "newmtl a\nmap_Kd Textures\\Wood.png\nmap_Bump textures/bark.png\n")
    write(tmp_path, "Tree.obj", obj_text(mtllib="Tree.mtl"))
    write(tmp_path, "Tree.gltf", gltf_text(["Textures\\Wood.png", "missing.png"]))

    fix = fixes_for(tmp_path, "Tree.obj")["paths"]
    assert fix["title"] == "Fix 2 paths"
    apply(tmp_path, "Tree.obj", fix)
    assert (tmp_path / "Tree.mtl").read_text() == (
        "newmtl a\nmap_Kd Textures/Wood.png\nmap_Bump Textures/Bark.png\n"
    )

    apply(tmp_path, "Tree.gltf", fixes_for(tmp_path, "Tree.gltf")["paths"])
    assert '"uri": "Textures/Wood.png"' in (tmp_path / "Tree.gltf").read_text()
    # what can't be fixed without guessing is left alone
    messages = [f["message"] for f in api.check(str(tmp_path))["findings"]]
    assert messages == ["references 'missing.png', which doesn't exist"]


def test_no_path_fix_for_absolute_or_missing_files(tmp_path: Path) -> None:
    write(tmp_path, "A.gltf", gltf_text(["C:/art/wood.png", "gone.png"]))
    assert "paths" not in fixes_for(tmp_path, "A.gltf")
    assert api.check(str(tmp_path))["fixable"] == []


# --- duplicates -----------------------------------------------------------------------


def test_trash_a_duplicate_and_point_its_users_at_the_copy_kept(
    tmp_path: Path, trash: list[Path]
) -> None:
    png = image_bytes(4, 4)
    write(tmp_path, "shared/T_Wood.png", png)
    write(tmp_path, "props/T_Wood.png", png)
    write(tmp_path, "props/T_Wood.png.meta", "guid: 2\n")
    write(tmp_path, "props/SM_Box.gltf", gltf_text(["T_Wood.png"]))

    found = fixes_for(tmp_path, "props/T_Wood.png")
    fix = found["trash:shared/T_Wood.png"]
    assert [c["kind"] for c in fix["changes"]] == ["trash", "trash", "edit"]
    apply(tmp_path, "props/T_Wood.png", fix)

    assert trash == [tmp_path / "props/T_Wood.png", tmp_path / "props/T_Wood.png.meta"]
    assert '"uri": "../shared/T_Wood.png"' in (tmp_path / "props/SM_Box.gltf").read_text()
    assert api.check(str(tmp_path))["findings"] == []


# --- safety -------------------------------------------------------------------------------


def test_apply_refuses_when_files_changed_since_the_preview(tmp_path: Path) -> None:
    write(tmp_path, "rock.png", image_bytes(4, 4))
    write(tmp_path, "A.gltf", gltf_text(["rock.png"]))
    write(tmp_path, "assetlint.toml", '[rules.naming]\nprefixes = { ".png" = "T_" }\n')
    fix = fixes_for(tmp_path, "rock.png")["rename"]
    write(tmp_path, "B.gltf", gltf_text(["rock.png"]))  # a new user of the file appears
    with pytest.raises(api.ApiError, match="changed since the preview"):
        apply(tmp_path, "rock.png", fix)
    assert (tmp_path / "rock.png").is_file()


def test_only_files_inside_the_folder(tmp_path: Path) -> None:
    write(tmp_path, "outside.obj", obj_text())
    (tmp_path / "inside").mkdir()
    with pytest.raises(api.ApiError, match="isn't a file in this folder"):
        fixes.list_fixes(str(tmp_path / "inside"), "../outside.obj")


def test_a_failed_fix_undoes_its_edits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path, "rock.png", image_bytes(4, 4))
    original = gltf_text(["rock.png"])
    write(tmp_path, "A.gltf", original)
    write(tmp_path, "assetlint.toml", '[rules.naming]\nprefixes = { ".png" = "T_" }\n')
    fix = fixes_for(tmp_path, "rock.png")["rename"]

    def locked(src: Any, dst: Any) -> None:
        raise PermissionError(13, "Access is denied", str(src))

    monkeypatch.setattr(fixes.os, "rename", locked)
    with pytest.raises(api.ApiError, match="nothing was changed"):
        apply(tmp_path, "rock.png", fix)
    assert (tmp_path / "A.gltf").read_text() == original


def test_check_lists_the_fixable_files(tmp_path: Path) -> None:
    write(tmp_path, "Cube.001.obj", obj_text())
    write(tmp_path, "SM_Ok.gltf", gltf_text(["missing.png"]))
    assert api.check(str(tmp_path))["fixable"] == ["Cube.001.obj"]


def test_a_rename_never_hashes_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Typing a name re-plans the rename; it mustn't hash every same-size texture each time."""
    write(tmp_path, "Cube.001.obj", obj_text())
    write(tmp_path, "Other.obj", obj_text())  # same size and content: a duplicate

    def no_hashing(asset: Any) -> bytes:
        raise AssertionError("hashed a file")

    monkeypatch.setattr(fixes, "_digest", no_hashing)
    found = fixes.list_fixes(str(tmp_path), "Cube.001.obj", "Crate.obj", rules=["naming"])
    fix = found["fixes"][0]
    apply(tmp_path, "Cube.001.obj", fix, name="Crate.obj")
    assert (tmp_path / "Crate.obj").is_file()


def test_rename_refuses_when_the_meta_name_is_taken(tmp_path: Path) -> None:
    write(tmp_path, "Cube.001.obj", obj_text())
    write(tmp_path, "Cube.001.obj.meta", "guid: 1\n")
    write(tmp_path, "Cube.obj.meta", "guid: 2\n")  # left over from a deleted Cube.obj
    assert (
        "Cube.obj.meta' already exists" in fixes_for(tmp_path, "Cube.001.obj")["rename"]["blocked"]
    )


def test_a_file_that_cannot_be_planned_is_reported(tmp_path: Path) -> None:
    write(tmp_path, "rock.png", image_bytes(4, 4))
    # JSON readers accept UTF-16, so this passes the check, but it can't be edited as UTF-8
    write(tmp_path, "A.gltf", gltf_text(["rock.png"]).encode("utf-16"))
    write(tmp_path, "assetlint.toml", '[rules.naming]\nprefixes = { ".png" = "T_" }\n')
    with pytest.raises(api.ApiError, match="Couldn't work out the fix"):
        fixes.list_fixes(str(tmp_path), "rock.png")


def test_duplicates_on_a_network_drive_are_deleted_for_good(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    png = image_bytes(4, 4)
    write(tmp_path, "T_A.png", png)
    write(tmp_path, "T_B.png", png)
    monkeypatch.setattr(fixes, "_no_recycle_bin", lambda path: True)
    fix = fixes_for(tmp_path, "T_B.png")["trash:T_A.png"]
    assert fix["button"] == "Delete"
    assert any("deleted for good" in note for note in fix["notes"])
