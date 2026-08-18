#!/usr/bin/env python3
"""Fetch one public file with exact size and SHA-256 verification."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
from collections.abc import Callable
import urllib.request


SHA256_RE = re.compile(r"[0-9a-f]{64}")
USER_AGENT = "pacing-rpg-render-base/1"


def fetch_verified(
    url: str,
    destination: Path,
    size: int,
    sha256: str,
    *,
    opener: Callable[[urllib.request.Request], object] | None = None,
) -> Path:
    """Stream a public asset, verify it, then publish it without overwriting."""
    if not isinstance(url, str) or not url:
        raise ValueError("URL is empty")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("size is invalid")
    if not isinstance(sha256, str) or SHA256_RE.fullmatch(sha256) is None:
        raise ValueError("SHA-256 is invalid")
    target = Path(destination)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"destination exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    written = 0
    open_url = opener or urllib.request.urlopen
    try:
        response = open_url(request)
        with response, partial.open("xb") as stream:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise ValueError("download returned non-byte content")
                written += len(chunk)
                if written > size:
                    raise ValueError(
                        f"size mismatch: expected {size} bytes, received more"
                    )
                digest.update(chunk)
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if written != size:
            raise ValueError(
                f"size mismatch: expected {size} bytes, received {written}"
            )
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != sha256:
            raise ValueError(
                f"SHA-256 mismatch: expected {sha256}, received {actual_sha256}"
            )
        partial.chmod(0o444)
        os.link(partial, target)
        partial.unlink()
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--size", required=True, type=int)
    parser.add_argument("--sha256", required=True)
    arguments = parser.parse_args(argv)
    fetch_verified(
        arguments.url,
        arguments.destination,
        arguments.size,
        arguments.sha256,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
