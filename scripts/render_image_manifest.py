#!/usr/bin/env python3
"""Validate public runtime inputs and render their canonical manifest."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re


PUBLIC_SOURCE_REPOSITORY = "https://github.com/jeffadamsc/pacing-rpg-render-base"
BASE_IMAGE = (
    "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04@"
    "sha256:61a4aafb0094cd773f11eefa378929d5a687bd775febeb78eac62fc824141fb5"
)
SOURCE_NAMES = {"comfyui", "impact-pack", "impact-subpack"}
MODEL_NAMES = {"checkpoint", "face_model"}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")


def canonical_json_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_text(value).encode("utf-8")).hexdigest()


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} is not a lowercase SHA-256")
    return value


def _validate_inputs(inputs: Mapping[str, object]) -> None:
    if set(inputs) != {
        "schema",
        "layout_version",
        "base_image",
        "runtime",
        "sources",
        "models",
    }:
        raise ValueError("runtime input fields are invalid")
    if inputs.get("schema") != 1 or inputs.get("layout_version") != 1:
        raise ValueError("runtime input schema is invalid")
    if inputs.get("base_image") != BASE_IMAGE:
        raise ValueError("base image identity is invalid")
    runtime = inputs.get("runtime")
    if not isinstance(runtime, Mapping):
        raise ValueError("runtime dependency record is invalid")
    _require_sha256(runtime.get("requirements_sha256"), "requirements SHA-256")
    sources = inputs.get("sources")
    if not isinstance(sources, Mapping) or set(sources) != SOURCE_NAMES:
        raise ValueError("runtime source set is invalid")
    for name, raw_source in sources.items():
        if not isinstance(raw_source, Mapping) or set(raw_source) != {
            "url",
            "revision",
            "archive_sha256",
        }:
            raise ValueError(f"runtime source record is invalid: {name}")
        if not isinstance(raw_source.get("url"), str) or not raw_source["url"]:
            raise ValueError(f"runtime source URL is invalid: {name}")
        revision = raw_source.get("revision")
        if not isinstance(revision, str) or REVISION_RE.fullmatch(revision) is None:
            raise ValueError(f"runtime source revision is invalid: {name}")
        _require_sha256(raw_source.get("archive_sha256"), f"{name} archive SHA-256")
    models = inputs.get("models")
    if not isinstance(models, Mapping) or set(models) != MODEL_NAMES:
        raise ValueError("runtime model set is invalid")
    for name, raw_model in models.items():
        if not isinstance(raw_model, Mapping) or set(raw_model) != {
            "url",
            "filename",
            "size",
            "sha256",
            "path",
        }:
            raise ValueError(f"runtime model record is invalid: {name}")
        filename = raw_model.get("filename")
        size = raw_model.get("size")
        sha256 = _require_sha256(raw_model.get("sha256"), f"{name} SHA-256")
        if not isinstance(filename, str) or not filename or "/" in filename:
            raise ValueError(f"runtime model filename is invalid: {name}")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ValueError(f"runtime model size is invalid: {name}")
        if not isinstance(raw_model.get("url"), str) or not raw_model["url"]:
            raise ValueError(f"runtime model URL is invalid: {name}")
        expected_path = (
            f"/workspace/sfw-static-public/models/by-sha/{sha256}/{filename}"
        )
        if raw_model.get("path") != expected_path:
            raise ValueError(f"runtime model path is invalid: {name}")


def load_runtime_inputs(path: Path) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read runtime inputs: {path}") from error
    if not isinstance(value, dict):
        raise ValueError("runtime inputs must be an object")
    _validate_inputs(value)
    return value


def _license_records(license_root: Path) -> list[dict[str, object]]:
    root = Path(license_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"license root is not a directory: {root}")
    records: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"license inventory contains a symbolic link: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        pure = PurePosixPath(relative.as_posix())
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"license path is unsafe: {relative}")
        data = path.read_bytes()
        records.append(
            {
                "path": pure.as_posix(),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    if not records:
        raise ValueError("license inventory is empty")
    return records


def render_image_manifest(
    inputs: Mapping[str, object],
    source_revision: str,
    license_root: Path,
) -> dict[str, object]:
    _validate_inputs(inputs)
    if REVISION_RE.fullmatch(source_revision) is None:
        raise ValueError("public source revision is invalid")
    manifest: dict[str, object] = {
        "payload": {
            "schema": 1,
            "layout_version": inputs["layout_version"],
            "base_image": inputs["base_image"],
            "public_source": {
                "repository": PUBLIC_SOURCE_REPOSITORY,
                "revision": source_revision,
            },
            "sources": inputs["sources"],
            "runtime": inputs["runtime"],
            "models": inputs["models"],
            "licenses": _license_records(license_root),
        }
    }
    manifest["payload_sha256"] = canonical_sha256(manifest["payload"])
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--license-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    output = arguments.output
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"manifest output exists: {output}")
    manifest = render_image_manifest(
        load_runtime_inputs(arguments.inputs),
        arguments.source_revision,
        arguments.license_root,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(canonical_json_text(manifest), encoding="utf-8")
        temporary.chmod(0o444)
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
