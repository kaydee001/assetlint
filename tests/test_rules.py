"""Unit tests for the core rules, on files built in tmp_path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from make_samples import glb_bytes, gltf_doc, image_bytes, obj_text

from assetlint.config import (
    Config,
    DuplicatesRuleConfig,
    FormatsRuleConfig,
    ReferencesRuleConfig,
    SizeRuleConfig,
    TexturesRuleConfig,
    TrianglesRuleConfig,
)
from assetlint.engine import discover, run
from assetlint.model import Asset
from assetlint.rules.base import Rule
from assetlint.rules.duplicates import DuplicatesRule
from assetlint.rules.formats import FormatsRule
from assetlint.rules.references import ReferencesRule
from assetlint.rules.size import SizeRule, human_size
from assetlint.rules.textures import TexturesRule
from assetlint.rules.triangles import TrianglesRule


def write(root: Path, rel: str, content: str | bytes) -> Asset:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode() if isinstance(content, str) else content)
    return Asset(path=path, rel=rel)


def check(rule: Rule[Any], asset: Asset) -> list[str]:
    return list(rule.check(asset))


# --- formats ----------------------------------------------------------------


class TestFormats:
    rule = FormatsRule(FormatsRuleConfig())

    def test_valid_files_pass(self, tmp_path: Path) -> None:
        doc, data = gltf_doc(3)
        assert check(self.rule, write(tmp_path, "a.glb", glb_bytes(doc, data))) == []
        assert check(self.rule, write(tmp_path, "a.gltf", json.dumps(doc))) == []
        assert check(self.rule, write(tmp_path, "a.png", image_bytes(4, 4))) == []
        assert check(self.rule, write(tmp_path, "a.jpg", image_bytes(4, 4, "JPEG"))) == []
        assert check(self.rule, write(tmp_path, "a.exr", b"\x76\x2f\x31\x01rest")) == []

    def test_type_not_allowed(self, tmp_path: Path) -> None:
        rule = FormatsRule(FormatsRuleConfig(allowed=["glb", ".PNG"]))
        assert check(rule, write(tmp_path, "a.png", image_bytes(4, 4))) == []
        [message] = check(rule, write(tmp_path, "a.fbx", b"x"))
        assert message == ".fbx files aren't allowed (allowed: .glb, .png)"

    def test_empty_file(self, tmp_path: Path) -> None:
        assert check(self.rule, write(tmp_path, "a.glb", b"")) == ["the file is empty"]

    def test_image_with_the_wrong_extension(self, tmp_path: Path) -> None:
        [message] = check(self.rule, write(tmp_path, "a.png", image_bytes(4, 4, "JPEG")))
        assert message == "it's a JPEG image with a .png extension"

    @pytest.mark.parametrize(
        ("name", "content", "expected"),
        [
            ("a.png", b"not an image", "not a readable image"),
            ("a.glb", b"PK\x03\x04 a zip, not a glb file", "missing the 'glTF' header"),
            ("a.gltf", b"{not json", "not valid glTF JSON"),
            ("a.gltf", b'{"asset": {"version": "1.0"}}', "glTF 1.0 isn't supported"),
            ("a.obj", b"v 0 0 0\x00\x00\x01", "binary file"),
            ("a.ktx2", b"something else", "doesn't look like a .ktx2 file"),
        ],
    )
    def test_corrupt_files(self, tmp_path: Path, name: str, content: bytes, expected: str) -> None:
        [message] = check(self.rule, write(tmp_path, name, content))
        assert expected in message

    def test_git_lfs_pointer(self, tmp_path: Path) -> None:
        pointer = "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 12345\n"
        [message] = check(self.rule, write(tmp_path, "T_A.png", pointer))
        assert message.startswith("this is a Git LFS pointer")

    def test_truncated_glb(self, tmp_path: Path) -> None:
        doc, data = gltf_doc(3)
        [message] = check(self.rule, write(tmp_path, "a.glb", glb_bytes(doc, data)[:-8]))
        assert message.startswith("truncated")

    def test_broken_accessor(self, tmp_path: Path) -> None:
        doc, _ = gltf_doc(1)
        doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"] = 7
        [message] = check(self.rule, write(tmp_path, "a.gltf", json.dumps(doc)))
        assert "missing or invalid accessor" in message

    def test_formats_without_a_signature_are_only_checked_for_being_empty(
        self, tmp_path: Path
    ) -> None:
        assert check(self.rule, write(tmp_path, "a.fbx", b"anything")) == []


def test_only_formats_reports_an_unreadable_file(tmp_path: Path) -> None:
    write(tmp_path, "SM_A.glb", b"garbage")
    write(tmp_path, "T_A.png", b"other garbage")
    result = run(tmp_path, Config())
    assert {(f.path, f.rule) for f in result.findings} == {
        ("SM_A.glb", "formats"),
        ("T_A.png", "formats"),
    }


# --- size -------------------------------------------------------------------


class TestSize:
    def test_no_limit_by_default(self, tmp_path: Path) -> None:
        assert check(SizeRule(SizeRuleConfig()), write(tmp_path, "a.png", b"x" * 10_000)) == []

    def test_over_the_limit(self, tmp_path: Path) -> None:
        rule = SizeRule(SizeRuleConfig.model_validate({"max": "1KB"}))
        assert check(rule, write(tmp_path, "ok.png", b"x" * 1000)) == []
        assert check(rule, write(tmp_path, "big.png", b"x" * 1500)) == [
            "1.5 KB, over the 1 KB limit"
        ]

    def test_rounding_never_hides_the_difference(self, tmp_path: Path) -> None:
        rule = SizeRule(SizeRuleConfig.model_validate({"max": "1KB"}))
        assert check(rule, write(tmp_path, "a.png", b"x" * 1040)) == [
            "1,040 bytes, over the 1,000-byte limit"
        ]

    def test_limit_by_type_overrides_max(self, tmp_path: Path) -> None:
        rule = SizeRule(SizeRuleConfig.model_validate({"max": 100, "max_by_type": {"PNG": 2000}}))
        assert check(rule, write(tmp_path, "a.png", b"x" * 1500)) == []
        assert len(check(rule, write(tmp_path, "a.glb", b"x" * 1500))) == 1

    @pytest.mark.parametrize(
        ("size", "text"),
        [(999, "999 bytes"), (1000, "1 KB"), (1_250_000, "1.2 MB"), (3 * 10**9, "3 GB")],
    )
    def test_human_size(self, size: int, text: str) -> None:
        assert human_size(size) == text


# --- duplicates -------------------------------------------------------------


class TestDuplicates:
    def findings(self, root: Path) -> list[tuple[str, str]]:
        rule = DuplicatesRule(DuplicatesRuleConfig())
        for asset in discover(root, Config()):
            check(rule, asset)
        return sorted((asset.rel, message) for asset, message in rule.finish())

    def test_copies_name_each_other(self, tmp_path: Path) -> None:
        for rel in ("a.obj", "props/b.obj", "old/c.obj"):
            write(tmp_path, rel, "same content\n")
        write(tmp_path, "d.obj", "different content\n")
        assert self.findings(tmp_path) == [
            ("a.obj", "same content as 'old/c.obj', 'props/b.obj'"),
            ("old/c.obj", "same content as 'a.obj', 'props/b.obj'"),
            ("props/b.obj", "same content as 'a.obj', 'old/c.obj'"),
        ]

    def test_same_size_different_content_passes(self, tmp_path: Path) -> None:
        write(tmp_path, "a.obj", "aaaa")
        write(tmp_path, "b.obj", "bbbb")
        assert self.findings(tmp_path) == []

    def test_empty_files_are_not_duplicates(self, tmp_path: Path) -> None:
        write(tmp_path, "a.obj", "")
        write(tmp_path, "b.obj", "")
        assert self.findings(tmp_path) == []


# --- triangles --------------------------------------------------------------


class TestTriangles:
    rule = TrianglesRule(TrianglesRuleConfig(max=10))

    def test_obj_within_and_over_budget(self, tmp_path: Path) -> None:
        assert check(self.rule, write(tmp_path, "a.obj", obj_text(10))) == []
        [message] = check(self.rule, write(tmp_path, "b.obj", obj_text(1200)))
        assert message == "1,200 triangles, over the budget of 10"

    def test_obj_polygons_count_as_n_minus_2(self, tmp_path: Path) -> None:
        # a quad (2), a pentagon (3) with v/vt/vn tokens, a line and a point (0): 5 in all
        text = "f 1 2 3 4\nf 1/1/1 2/2/2 3/3/3 4/4/4 5/5/5\nl 1 2\np 1\n"
        rule = TrianglesRule(TrianglesRuleConfig(max=4))
        assert check(rule, write(tmp_path, "a.obj", text)) == ["5 triangles, over the budget of 4"]

    def test_obj_with_tabs_and_a_byte_order_mark(self, tmp_path: Path) -> None:
        text = "\ufeffmtllib\ta.mtl\nf\t1\t2\t3\t4\n" + "f 1 2 3\n" * 9
        write(tmp_path, "a.mtl", "map_Kd\tmissing.png\n")
        asset = write(tmp_path, "a.obj", text)
        assert check(self.rule, asset) == ["11 triangles, over the budget of 10"]
        assert check(ReferencesRule(ReferencesRuleConfig()), asset) == [
            "references 'missing.png' (in 'a.mtl'), which doesn't exist"
        ]

    def test_gltf_and_glb(self, tmp_path: Path) -> None:
        doc, data = gltf_doc(11)
        assert len(check(self.rule, write(tmp_path, "a.glb", glb_bytes(doc, data)))) == 1
        assert len(check(self.rule, write(tmp_path, "a.gltf", json.dumps(doc)))) == 1

    @pytest.mark.parametrize(
        ("mode", "count", "triangles"),
        [(None, 30, 10), (4, 30, 10), (5, 30, 28), (6, 30, 28), (1, 30, 0), (0, 30, 0)],
    )
    def test_gltf_primitive_modes(
        self, tmp_path: Path, mode: int | None, count: int, triangles: int
    ) -> None:
        doc, _ = gltf_doc(1)
        doc["accessors"][0]["count"] = count
        if mode is not None:
            doc["meshes"][0]["primitives"][0]["mode"] = mode
        rule = TrianglesRule(TrianglesRuleConfig(max=1))
        messages = check(rule, write(tmp_path, "a.gltf", json.dumps(doc)))
        expected = [f"{triangles} triangles, over the budget of 1"] if triangles > 1 else []
        assert messages == expected

    def test_gltf_indices_take_precedence_over_positions(self, tmp_path: Path) -> None:
        doc, _ = gltf_doc(1)  # 3 positions
        doc["accessors"].append({"componentType": 5123, "count": 36, "type": "SCALAR"})
        doc["meshes"][0]["primitives"][0]["indices"] = 1
        [message] = check(self.rule, write(tmp_path, "a.gltf", json.dumps(doc)))
        assert message.startswith("12 triangles")

    def test_no_budget_by_default(self, tmp_path: Path) -> None:
        rule = TrianglesRule(TrianglesRuleConfig())
        assert check(rule, write(tmp_path, "a.obj", obj_text(5000))) == []


# --- textures ---------------------------------------------------------------


class TestTextures:
    def test_power_of_two(self, tmp_path: Path) -> None:
        rule = TexturesRule(TexturesRuleConfig())
        assert check(rule, write(tmp_path, "a.png", image_bytes(256, 64))) == []
        assert check(rule, write(tmp_path, "b.png", image_bytes(1, 1))) == []
        [message] = check(rule, write(tmp_path, "c.png", image_bytes(256, 100)))
        assert message.startswith("256x100 isn't a power of two")

    def test_power_of_two_can_be_switched_off(self, tmp_path: Path) -> None:
        rule = TexturesRule(TexturesRuleConfig(power_of_two=False))
        assert check(rule, write(tmp_path, "a.png", image_bytes(300, 100))) == []

    def test_max_size(self, tmp_path: Path) -> None:
        rule = TexturesRule(TexturesRuleConfig(max_size=128))
        assert check(rule, write(tmp_path, "a.tga", image_bytes(128, 128, "TGA"))) == []
        [message] = check(rule, write(tmp_path, "b.jpg", image_bytes(64, 256, "JPEG")))
        assert message == "64x256, over the maximum of 128"

    def test_formats_pillow_cant_read_are_skipped(self, tmp_path: Path) -> None:
        rule = TexturesRule(TexturesRuleConfig(max_size=1))
        assert check(rule, write(tmp_path, "a.exr", b"\x76\x2f\x31\x01")) == []


# --- references -------------------------------------------------------------


class TestReferences:
    def refs(self, asset: Asset) -> list[str]:
        return check(ReferencesRule(ReferencesRuleConfig()), asset)

    def test_obj_with_its_mtl_and_textures_present(self, tmp_path: Path) -> None:
        # Texture paths are relative to the .mtl, not the .obj.
        mtl = "newmtl a\nmap_Kd -s 2 2 1 -bm 0.5 tex/T_A.png\nmap_Bump ../T_B.png\n"
        write(tmp_path, "mats/a.mtl", mtl)
        write(tmp_path, "mats/tex/T_A.png", image_bytes(4, 4))
        write(tmp_path, "T_B.png", image_bytes(4, 4))
        assert self.refs(write(tmp_path, "a.obj", obj_text(mtllib="mats/a.mtl"))) == []

    def test_missing_mtl(self, tmp_path: Path) -> None:
        asset = write(tmp_path, "a.obj", obj_text(mtllib="a.mtl"))
        assert self.refs(asset) == ["references 'a.mtl', which doesn't exist"]

    def test_missing_texture_in_mtl(self, tmp_path: Path) -> None:
        write(tmp_path, "a.mtl", "map_Kd wood floor.png\n")
        asset = write(tmp_path, "a.obj", obj_text(mtllib="a.mtl"))
        assert self.refs(asset) == ["references 'wood floor.png' (in 'a.mtl'), which doesn't exist"]

    def test_case_mismatch(self, tmp_path: Path) -> None:
        write(tmp_path, "Textures/T_A.png", image_bytes(4, 4))
        write(tmp_path, "a.mtl", "map_Kd textures/t_a.png\n")
        [message] = self.refs(write(tmp_path, "a.obj", obj_text(mtllib="a.mtl")))
        assert message.endswith("but it's 'Textures/T_A.png' on disk; the case must match on Linux")

    @pytest.mark.parametrize(
        "path", [r"C:\Users\artist\a.mtl", "C:/Users/artist/a.mtl", "/home/artist/a.mtl"]
    )
    def test_absolute_paths(self, tmp_path: Path, path: str) -> None:
        [message] = self.refs(write(tmp_path, "a.obj", obj_text(mtllib=path)))
        assert message == f"references '{path}', an absolute path; use a path relative to the file"

    def test_backslashes(self, tmp_path: Path) -> None:
        write(tmp_path, "tex/a.mtl", "newmtl a\n")
        [message] = self.refs(write(tmp_path, "a.obj", obj_text(mtllib=r"tex\a.mtl")))
        assert "backslashes" in message

    def test_gltf_images_and_buffers(self, tmp_path: Path) -> None:
        write(tmp_path, "T_A B.png", image_bytes(4, 4))
        doc, data = gltf_doc(1, images=["T_A%20B.png", "missing.png"], buffer_uri="a.bin")
        doc["images"].append({"uri": "data:image/png;base64,AAAA"})
        doc["images"].append({"bufferView": 0, "mimeType": "image/png"})
        write(tmp_path, "a.bin", data)
        assert self.refs(write(tmp_path, "a.gltf", json.dumps(doc))) == [
            "references 'missing.png', which doesn't exist"
        ]

    def test_glb_own_buffer_has_no_uri(self, tmp_path: Path) -> None:
        doc, data = gltf_doc(1)
        assert self.refs(write(tmp_path, "a.glb", glb_bytes(doc, data))) == []
