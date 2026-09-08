"""Fast unit tests for source integrity and release gates.

No native GDAL build is required.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ci"))

import sources  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


manifest = load_module("manifest", ROOT / "ci/generate-manifest.py")


PLATFORMS = {
    "linux-x86_64": "manylinux_2_28_x86_64",
    "macos-arm64": "macosx_11_0_arm64",
    "windows-x86_64": "win_amd64",
}


def python_abis() -> tuple[str, ...]:
    """Return four CPython ABI tags without hard-coding Python versions.

    With the new dynamic manifest this is only synthetic unit-test data.
    If an older manifest still exposes PYTHONS, use it for compatibility.
    """
    configured = getattr(manifest, "PYTHONS", None)
    if configured:
        return tuple(sorted(configured, key=lambda tag: int(tag[2:])))

    major, minor = sys.version_info[:2]
    return tuple(
        f"cp{major}{version}"
        for version in range(minor - 3, minor + 1)
    )


def make_release(tmp_path: Path):
    wheels = tmp_path / "wheels"
    results = tmp_path / "results"
    wheels.mkdir()
    results.mkdir()

    for python in python_abis():
        for platform, tag in PLATFORMS.items():
            filename = f"gdal-3.13.3-{python}-{python}-{tag}.whl"
            wheel = wheels / filename
            wheel.write_bytes(filename.encode())

            result_dir = results / f"{python}-{platform}"
            result_dir.mkdir()

            report = {
                "wheel": filename,
                "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "feature_tests": "passed",
                # Kept for compatibility with an older manifest.
                "leak_tests": "passed",
                "coexistence_tests": "passed",
                "hdf4": (
                    "not-supported"
                    if platform == "windows-x86_64"
                    else "passed"
                ),
            }

            (result_dir / "test-result.json").write_text(
                json.dumps(report)
            )

    return wheels, results


def test_digest_mismatch_never_replaces_archive(tmp_path):
    destination = tmp_path / "source.tar"

    with patch(
        "urllib.request.urlopen",
        return_value=io.BytesIO(b"wrong"),
    ):
        with pytest.raises(ValueError, match="SHA256 mismatch"):
            sources.download(
                {
                    "url": "https://example.org/source",
                    "sha256": "0" * 64,
                },
                destination,
            )

    assert not destination.exists()
    assert not destination.with_suffix(".partial").exists()


def test_verified_cache_avoids_network(tmp_path):
    destination = tmp_path / "source.tar"
    destination.write_bytes(b"good")

    with patch(
        "urllib.request.urlopen",
        side_effect=AssertionError("network"),
    ):
        sources.download(
            {
                "url": "https://example.org/source",
                "sha256": hashlib.sha256(b"good").hexdigest(),
            },
            destination,
        )


def test_archive_traversal_rejected(tmp_path):
    archive = tmp_path / "evil.tar"

    with tarfile.open(archive, "w") as output:
        member = tarfile.TarInfo("../../escaped")
        member.size = 1
        output.addfile(member, io.BytesIO(b"x"))

    with pytest.raises(tarfile.FilterError):
        sources.extract(archive, tmp_path / "out")

    assert not (tmp_path / "escaped").exists()


@pytest.mark.parametrize(
    "version",
    ["3.14.0rc1", "main", "../3.13.3", "3.13.3;echo no"],
)
def test_version_rejects_nonstable_input(version):
    with pytest.raises(ValueError, match="stable semantic"):
        sources.resolve(version)


def test_complete_release(tmp_path):
    wheels, results = make_release(tmp_path)

    record = manifest.generate(
        wheels,
        results,
        {"version": "3.13.3"},
        "owner/repo",
    )

    assert record["complete"]
    assert len(record["wheels"]) == len(python_abis()) * len(PLATFORMS)
    assert (
        (wheels / "index.html").read_text().count("#sha256=")
        == len(record["wheels"])
    )

    if "python_versions" in record:
        assert set(record["python_versions"]) == set(python_abis())


@pytest.mark.parametrize(
    "fault",
    [
        "missing-wheel",
        "missing-test",
        "failed-test",
        "coexistence",
        "hdf4",
        "tampered-wheel",
    ],
)
def test_incomplete_release_rejected(tmp_path, fault):
    wheels, results = make_release(tmp_path)

    report_path = next(results.rglob("test-result.json"))
    report = json.loads(report_path.read_text())

    if fault == "missing-wheel":
        (wheels / report["wheel"]).unlink()

    elif fault == "missing-test":
        report_path.unlink()

    elif fault == "tampered-wheel":
        (wheels / report["wheel"]).write_bytes(b"tampered")

    else:
        field = {
            "failed-test": "feature_tests",
            "coexistence": "coexistence_tests",
            "hdf4": "hdf4",
        }[fault]
        report[field] = "failed"
        report_path.write_text(json.dumps(report))

    with pytest.raises(ValueError):
        manifest.generate(
            wheels,
            results,
            {"version": "3.13.3"},
            "owner/repo",
        )

    assert not (wheels / "manifest.json").exists()


def test_bootstrap_preserves_application_settings(tmp_path):
    class Gdal:
        settings = {"GDAL_DATA": "application"}

        def GetConfigOption(self, name):
            return self.settings.get(name)

        def SetConfigOption(self, name, value):
            self.settings[name] = value

    (tmp_path / "data/gdal").mkdir(parents=True)
    (tmp_path / "data/proj").mkdir()

    gdal = Gdal()

    with patch.dict(
        "os.environ",
        {"PROJ_LIB": "legacy-user-proj"},
        clear=True,
    ):
        exec(
            (ROOT / "ci/bootstrap.py").read_text(),
            {
                "__file__": str(tmp_path / "__init__.py"),
                "_gdal": gdal,
            },
        )

        import os

        assert gdal.settings["GDAL_DATA"] == "application"
        assert "PROJ_DATA" not in os.environ
