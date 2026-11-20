import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build"

FUNCTIONS = {
    "document_expiry": ROOT / "lambda/document_expiry/handler.py",
    "document_cleanup": ROOT / "lambda/document_cleanup/handler.py",
    "document_finalization": ROOT / "lambda/document_finalization/handler.py",
    "jwks_sync": ROOT / "lambda/jwks_sync/handler.py",
    "document_version_hygiene": ROOT / "lambda/document_version_hygiene/handler.py",
}


def package_lambda(name: str, source: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"Lambda source does not exist: {source}")

    output = BUILD_DIR / f"{name}.zip"
    temporary = BUILD_DIR / f"{name}.zip.tmp"

    archive_entry = ZipInfo("handler.py")
    archive_entry.date_time = (1980, 1, 1, 0, 0, 0)
    archive_entry.compress_type = ZIP_DEFLATED
    archive_entry.external_attr = 0o100644 << 16

    try:
        with ZipFile(temporary, "w") as archive:
            archive.writestr(
                archive_entry,
                source.read_bytes(),
            )

        with ZipFile(temporary, "r") as archive:
            if archive.testzip() is not None:
                raise RuntimeError(f"ZIP integrity check failed: {name}")

            if archive.namelist() != ["handler.py"]:
                raise RuntimeError(f"Unexpected ZIP contents: {name}")

        os.replace(temporary, output)

    finally:
        if temporary.exists():
            temporary.unlink()

    print(f"Packaged {name}: {output.relative_to(ROOT)}")
    print(f"  Size: {output.stat().st_size:,} bytes")

    return output


def main():
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    for name, source in FUNCTIONS.items():
        package_lambda(name, source)


if __name__ == "__main__":
    main()
