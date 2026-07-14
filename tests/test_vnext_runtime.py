from __future__ import annotations

import pytest

from stonks_cli.vnext.filesystem import enforce_private_file, ensure_private_directory
from stonks_cli.vnext.runtime import RUNTIME_ROOT_ENV, RuntimeDirectory, runtime_directories


def test_runtime_directory_policy_uses_absolute_root_and_creates_known_subdirectories(tmp_path):
    directories = runtime_directories(tmp_path)

    directories.ensure()

    assert directories.root == tmp_path.resolve()
    assert {directories.path_for(directory).name for directory in RuntimeDirectory} == {
        "runs",
        "snapshots",
        "reports",
        "queue",
        "backups",
    }
    assert all(directories.path_for(directory).is_dir() for directory in RuntimeDirectory)
    assert directories.root.stat().st_mode & 0o777 == 0o700
    assert all(directories.path_for(directory).stat().st_mode & 0o777 == 0o700 for directory in RuntimeDirectory)


def test_runtime_directory_policy_honors_absolute_environment_override(monkeypatch, tmp_path):
    root = tmp_path / "runtime"
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(root))

    assert runtime_directories().root == root.resolve()


@pytest.mark.parametrize("root", ["relative/runtime", ""])
def test_runtime_directory_policy_rejects_malformed_roots(monkeypatch, root):
    monkeypatch.setenv(RUNTIME_ROOT_ENV, root)

    with pytest.raises(ValueError, match="runtime root must be absolute"):
        runtime_directories()


def test_runtime_directory_policy_rejects_unknown_directory(tmp_path):
    with pytest.raises(ValueError, match="unknown runtime directory"):
        runtime_directories(tmp_path).path_for("secrets")


def test_runtime_directory_policy_fails_when_root_is_a_file(tmp_path):
    root = tmp_path / "runtime"
    root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(FileExistsError):
        runtime_directories(root).ensure()


def test_runtime_permissions_are_corrected_for_existing_paths(tmp_path):
    directory = tmp_path / "runtime"
    directory.mkdir(mode=0o755)
    path = directory / "state.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o644)

    ensure_private_directory(directory)
    enforce_private_file(path)

    assert directory.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600


def test_runtime_permissions_reject_symlink_paths(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    symlink = tmp_path / "runtime-link"
    symlink.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="must not be a symlink"):
        ensure_private_directory(symlink)
