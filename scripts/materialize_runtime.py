#!/usr/bin/env python3
"""Materialize exact public sources and models into the image layout."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile

try:
    from .fetch_verified import fetch_verified
except ImportError:  # Direct script execution in the image build.
    from fetch_verified import fetch_verified


SOURCE_LOCATIONS = {
    "comfyui": PurePosixPath("/opt/sfw-static/runtime/ComfyUI"),
    "impact-pack": PurePosixPath(
        "/opt/sfw-static/runtime/ComfyUI/custom_nodes/ComfyUI-Impact-Pack"
    ),
    "impact-subpack": PurePosixPath(
        "/opt/sfw-static/runtime/ComfyUI/custom_nodes/ComfyUI-Impact-Subpack"
    ),
}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")


def _archive_entries(checkout: Path) -> list[tuple[str, Path, bool]]:
    result: list[tuple[str, Path, bool]] = []
    for path in checkout.rglob("*"):
        relative = path.relative_to(checkout)
        if (
            ".git" in relative.parts
            or "__pycache__" in relative.parts
            or relative.name.endswith((".pyc", ".pyo"))
            or path.is_symlink()
        ):
            continue
        if path.is_dir():
            result.append((relative.as_posix(), path, True))
        elif path.is_file():
            result.append((relative.as_posix(), path, False))
    return sorted(result, key=lambda item: item[0])


def build_source_archive(checkout: Path, destination: Path) -> Path:
    """Reproduce the controller's byte-deterministic source archive."""
    source = Path(checkout).resolve(strict=True)
    if not source.is_dir():
        raise ValueError(f"source checkout is not a directory: {source}")
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    temporary.unlink(missing_ok=True)
    try:
        with temporary.open("xb") as raw_stream:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw_stream,
                mtime=0,
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed,
                    mode="w",
                    format=tarfile.PAX_FORMAT,
                ) as archive:
                    for name, path, is_directory in _archive_entries(source):
                        info = tarfile.TarInfo(name)
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        info.mtime = 0
                        if is_directory:
                            info.type = tarfile.DIRTYPE
                            info.mode = 0o555
                            info.size = 0
                            archive.addfile(info)
                        else:
                            info.type = tarfile.REGTYPE
                            info.mode = 0o444
                            info.size = path.stat().st_size
                            with path.open("rb") as stream:
                                archive.addfile(info, stream)
            raw_stream.flush()
            os.fsync(raw_stream.fileno())
        os.replace(temporary, target)
        target.chmod(0o444)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _run(arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except OSError as error:
        raise ValueError(f"cannot run source command: {arguments[0]}") from error
    if result.returncode != 0:
        detail = " ".join(result.stderr.split())[:300]
        raise ValueError(f"source command failed: {arguments[1]}: {detail}")
    return result.stdout.strip()


def _checkout_source(record: Mapping[str, object], destination: Path) -> None:
    url = record.get("url")
    revision = record.get("revision")
    if not isinstance(url, str) or not url:
        raise ValueError("source URL is invalid")
    if not isinstance(revision, str) or REVISION_RE.fullmatch(revision) is None:
        raise ValueError("source revision is invalid")
    _run(["git", "init", str(destination)])
    _run(["git", "-C", str(destination), "remote", "add", "origin", url])
    _run(
        [
            "git",
            "-C",
            str(destination),
            "fetch",
            "--depth",
            "1",
            "origin",
            revision,
        ]
    )
    _run(["git", "-C", str(destination), "checkout", "--detach", "FETCH_HEAD"])
    actual = _run(["git", "-C", str(destination), "rev-parse", "HEAD"])
    if actual != revision:
        raise ValueError(f"source revision mismatch: {actual}")


def _safe_member_name(name: str) -> bool:
    pure = PurePosixPath(name)
    return (
        bool(name)
        and not pure.is_absolute()
        and ".." not in pure.parts
        and name == pure.as_posix()
    )


def _extract_source(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        seen: set[str] = set()
        for member in members:
            if (
                not _safe_member_name(member.name)
                or member.name in seen
                or not (member.isdir() or member.isfile())
            ):
                raise ValueError(f"unsafe source archive member: {member.name}")
            seen.add(member.name)
        for member in members:
            output = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
                output.chmod(0o755)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"cannot read source archive member: {member.name}")
            with output.open("xb") as stream:
                shutil.copyfileobj(source, stream)
            output.chmod(0o644)


def _rooted(root: Path, absolute: PurePosixPath) -> Path:
    if not absolute.is_absolute() or ".." in absolute.parts:
        raise ValueError(f"image path is invalid: {absolute}")
    return root.joinpath(*absolute.parts[1:])


def materialize_runtime(
    inputs: Mapping[str, object],
    destination: Path,
) -> Path:
    """Build the fixed public runtime and model layout beneath an image root."""
    target = Path(destination)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"runtime destination exists: {target}")
    raw_sources = inputs.get("sources")
    raw_models = inputs.get("models")
    if not isinstance(raw_sources, Mapping) or set(raw_sources) != set(
        SOURCE_LOCATIONS
    ):
        raise ValueError("public source set is invalid")
    if not isinstance(raw_models, Mapping) or not raw_models:
        raise ValueError("public model set is invalid")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.materialize.", dir=target.parent)
    )
    checkout_root = Path(tempfile.mkdtemp(prefix="sfw-source-checkouts."))
    try:
        for source_name, location in SOURCE_LOCATIONS.items():
            record = raw_sources[source_name]
            if not isinstance(record, Mapping):
                raise ValueError(f"public source record is invalid: {source_name}")
            expected_archive = record.get("archive_sha256")
            if (
                not isinstance(expected_archive, str)
                or SHA256_RE.fullmatch(expected_archive) is None
            ):
                raise ValueError(f"source archive SHA-256 is invalid: {source_name}")
            checkout = checkout_root / source_name
            _checkout_source(record, checkout)
            archive = checkout_root / f"{source_name}.tgz"
            build_source_archive(checkout, archive)
            actual_archive = hashlib.sha256(archive.read_bytes()).hexdigest()
            if actual_archive != expected_archive:
                raise ValueError(
                    f"source archive SHA-256 mismatch: {source_name}: "
                    f"expected {expected_archive}, received {actual_archive}"
                )
            output = _rooted(staging, location)
            output.mkdir(parents=True, exist_ok=False)
            _extract_source(archive, output)

        for model_name, raw_model in sorted(raw_models.items()):
            if not isinstance(model_name, str) or not isinstance(raw_model, Mapping):
                raise ValueError("public model record is invalid")
            url = raw_model.get("url")
            filename = raw_model.get("filename")
            size = raw_model.get("size")
            sha256 = raw_model.get("sha256")
            raw_path = raw_model.get("path")
            if not isinstance(filename, str) or not filename or "/" in filename:
                raise ValueError(f"public model filename is invalid: {model_name}")
            if not isinstance(sha256, str) or SHA256_RE.fullmatch(sha256) is None:
                raise ValueError(f"public model SHA-256 is invalid: {model_name}")
            expected_path = f"/opt/sfw-static/models/by-sha/{sha256}/{filename}"
            if raw_path != expected_path:
                raise ValueError(f"public model path is invalid: {model_name}")
            if not isinstance(url, str) or not isinstance(size, int):
                raise ValueError(f"public model download record is invalid: {model_name}")
            fetch_verified(
                url,
                _rooted(staging, PurePosixPath(expected_path)),
                size,
                sha256,
            )

        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(checkout_root, ignore_errors=True)
    return target / "opt/sfw-static/runtime/ComfyUI"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    arguments = parser.parse_args(argv)
    inputs = json.loads(arguments.inputs.read_text(encoding="utf-8"))
    if not isinstance(inputs, Mapping):
        raise ValueError("runtime inputs must be an object")
    materialize_runtime(inputs, arguments.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
