from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from scripts import package_lambdas


def configure_test_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(package_lambdas, "ROOT", tmp_path)
    build_dir = tmp_path / "build"
    monkeypatch.setattr(package_lambdas, "BUILD_DIR", build_dir)
    build_dir.mkdir()
    return build_dir


def test_package_lambda_creates_valid_archive(monkeypatch, tmp_path):
    build_dir = configure_test_paths(monkeypatch, tmp_path)

    source = tmp_path / "handler.py"
    source.write_text("def handler(event, context):\n    return {'ok': True}\n")

    output = package_lambdas.package_lambda("test_function", source)

    assert output == build_dir / "test_function.zip"
    assert output.is_file()

    with ZipFile(output, "r") as archive:
        assert archive.testzip() is None
        assert archive.namelist() == ["handler.py"]

        entry = archive.getinfo("handler.py")

        assert entry.date_time == (1980, 1, 1, 0, 0, 0)
        assert entry.compress_type == ZIP_DEFLATED
        assert entry.external_attr >> 16 == 0o100644
        assert archive.read("handler.py") == source.read_bytes()


def test_package_lambda_is_reproducible(monkeypatch, tmp_path):
    build_dir = configure_test_paths(monkeypatch, tmp_path)

    source = tmp_path / "handler.py"
    source.write_text("VALUE = 42\n")

    output = package_lambdas.package_lambda("test_function", source)
    first_hash = sha256(output.read_bytes()).hexdigest()

    package_lambdas.package_lambda("test_function", source)
    second_hash = sha256(output.read_bytes()).hexdigest()

    assert first_hash == second_hash


def test_missing_source_preserves_existing_archive(monkeypatch, tmp_path):
    build_dir = configure_test_paths(monkeypatch, tmp_path)

    output = build_dir / "test_function.zip"
    original_content = b"existing artifact"
    output.write_bytes(original_content)

    with pytest.raises(FileNotFoundError):
        package_lambdas.package_lambda(
            "test_function",
            tmp_path / "missing_handler.py",
        )

    assert output.read_bytes() == original_content
    assert not (build_dir / "test_function.zip.tmp").exists()


def test_packaging_failure_cleans_temporary_file(
    monkeypatch,
    tmp_path,
):
    build_dir = configure_test_paths(monkeypatch, tmp_path)

    source = tmp_path / "handler.py"
    source.write_text("VALUE = 42\n")

    output = build_dir / "test_function.zip"
    original_content = b"previous artifact"
    output.write_bytes(original_content)

    original_read_bytes = Path.read_bytes

    def fail_source_read(path):
        if path == source:
            raise OSError("Simulated source read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_source_read)

    with pytest.raises(OSError, match="Simulated source read failure"):
        package_lambdas.package_lambda("test_function", source)

    assert output.read_bytes() == original_content
    assert not (build_dir / "test_function.zip.tmp").exists()
