"""The app's API, and the local server's guards against other websites."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from make_samples import obj_text

from assetlint.app import api
from assetlint.app.server import AppServer


@pytest.fixture(autouse=True)
def state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep recent folders out of the real home folder."""
    path = tmp_path / "state" / "app.json"
    monkeypatch.setattr(api, "STATE_FILE", path)
    return path


# --- API ----------------------------------------------------------------------


def test_check_returns_findings_relative_to_the_folder(samples: Path) -> None:
    data = api.check(str(samples / "bad"))
    assert data["config"] == str(samples / "assetlint.toml")
    assert (data["files_checked"], data["errors"]) == (17, 17)
    paths = {f["path"] for f in data["findings"]}
    assert "copies/SM_Pot.obj" in paths  # relative to the chosen folder, not the config's
    assert [r["id"] for r in data["rules"]][:3] == ["formats", "size", "naming"]


def test_check_without_a_config_uses_defaults(tmp_path: Path) -> None:
    (tmp_path / "Cube.001.obj").write_text(obj_text())
    data = api.check(str(tmp_path))
    assert data["config"] is None
    assert [f["rule"] for f in data["findings"]] == ["naming"]


@pytest.mark.parametrize(
    ("folder", "message"),
    [("", "Choose a folder"), ("/no/such/folder", "doesn't exist")],
)
def test_check_explains_bad_folders(folder: str, message: str) -> None:
    with pytest.raises(api.ApiError, match=message):
        api.check(folder)


def test_check_reports_an_invalid_config(tmp_path: Path) -> None:
    (tmp_path / "assetlint.toml").write_text("[rules.naming]\nserverity = 'x'\n")
    with pytest.raises(api.ApiError, match="unknown key"):
        api.check(str(tmp_path))


def test_recent_folders_newest_first_without_repeats(tmp_path: Path) -> None:
    for name in ("a", "b", "a"):
        (tmp_path / name).mkdir(exist_ok=True)
        api.check(str(tmp_path / name))
    assert api.recent() == [str(tmp_path / "a"), str(tmp_path / "b")]


def test_a_broken_state_file_is_ignored(state_file: Path) -> None:
    state_file.parent.mkdir(parents=True)
    state_file.write_text("not json")
    assert api.recent() == []


# --- server ---------------------------------------------------------------------


@pytest.fixture
def server() -> Iterator[AppServer]:
    app = AppServer()
    thread = threading.Thread(target=app.serve_forever, daemon=True)
    thread.start()
    yield app
    app.shutdown()
    app.server_close()


def request(
    server: AppServer,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    all_headers = {"X-Assetlint-Token": server.token, "Content-Type": "application/json"}
    all_headers.update(headers or {})
    payload = json.dumps(body).encode() if body is not None else None
    connection.request(method, path, body=payload, headers=all_headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    is_json = response.getheader("Content-Type") == "application/json"
    return response.status, json.loads(raw) if is_json else raw


def test_serves_the_page_and_its_files(server: AppServer) -> None:
    status, page = request(server, "GET", "/")
    assert status == 200 and b"Asset Lint" in page
    for name in ("app.js", "app.css", "icon.svg"):
        assert request(server, "GET", f"/static/{name}")[0] == 200
    assert request(server, "GET", "/static/../server.py")[0] == 404


def test_check_through_the_server(server: AppServer, samples: Path) -> None:
    status, data = request(server, "POST", "/api/check", {"folder": str(samples / "good")})
    assert status == 200
    assert data["findings"] == []


def test_api_errors_come_back_as_messages(server: AppServer) -> None:
    status, data = request(server, "POST", "/api/check", {"folder": "/no/such/folder"})
    assert status == 422
    assert "doesn't exist" in data["error"]


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Assetlint-Token": "wrong"},
        {"Host": "evil.example:80"},  # DNS rebinding
        {"Origin": "https://evil.example"},  # another site's page posting to us
        {"Content-Type": "text/plain"},  # a "simple" request that skips CORS preflight
    ],
)
def test_requests_from_elsewhere_are_refused(
    server: AppServer, samples: Path, headers: dict[str, str]
) -> None:
    status, _ = request(server, "POST", "/api/check", {"folder": str(samples)}, headers)
    assert status in (403, 415)


def test_info_needs_the_token(server: AppServer) -> None:
    assert request(server, "GET", "/api/info", headers={"X-Assetlint-Token": ""})[0] == 403
    status, data = request(server, "GET", "/api/info")
    assert status == 200 and "recent" in data
