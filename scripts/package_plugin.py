"""Package only the two self-contained Hermes plugin files, without runtime data."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def main():
    root = Path(__file__).resolve().parents[1]
    destination = root / "artifacts" / "tavrel-hermes-plugin.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    names = ("__init__.py", "plugin.yaml")
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for name in names:
            info = ZipInfo("tavrel/" + name, date_time=(2026, 11, 10, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (root / "hermes_plugin" / name).read_bytes())
    with ZipFile(destination) as archive:
        assert archive.namelist() == ["tavrel/" + name for name in names]
        assert archive.testzip() is None
        for name in names:
            assert archive.read("tavrel/" + name) == (root / "hermes_plugin" / name).read_bytes()
    print(f"Packaged and verified: {destination}")


if __name__ == "__main__":
    main()
