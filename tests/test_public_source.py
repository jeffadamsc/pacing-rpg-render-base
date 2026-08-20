from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from scripts.fetch_verified import fetch_verified
from scripts.materialize_runtime import materialize_runtime
from scripts.render_image_manifest import (
    canonical_json_text,
    canonical_sha256,
    load_runtime_inputs,
    render_image_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
BASE_IMAGE = (
    "pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime@"
    "sha256:0a3b9fedefe1f61ac4d5a9de9015c0863db27ca0fde2d4e37e6268147980b726"
)


def _run(*arguments: str) -> str:
    result = subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        },
    )
    return result.stdout.strip()


def _make_git_source(root: Path, name: str, content: bytes) -> tuple[Path, str, str]:
    repository = root / f"{name}-repository"
    repository.mkdir()
    _run("git", "init", "--quiet", str(repository))
    (repository / "fixture.bin").write_bytes(content)
    _run("git", "-C", str(repository), "add", "fixture.bin")
    _run("git", "-C", str(repository), "commit", "--quiet", "-m", "fixture")
    revision = _run("git", "-C", str(repository), "rev-parse", "HEAD")
    archive_path = root / f"{name}.tgz"
    _build_fixture_archive(repository, archive_path)
    return repository, revision, hashlib.sha256(archive_path.read_bytes()).hexdigest()


def _build_fixture_archive(source: Path, destination: Path) -> None:
    entries: list[tuple[str, Path, bool]] = []
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if ".git" in relative.parts or path.is_symlink():
            continue
        if path.is_dir():
            entries.append((relative.as_posix(), path, True))
        elif path.is_file():
            entries.append((relative.as_posix(), path, False))
    with destination.open("wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", compresslevel=9, fileobj=raw, mtime=0
        ) as compressed:
            with tarfile.open(
                fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
            ) as archive:
                for member_name, path, is_directory in sorted(entries):
                    info = tarfile.TarInfo(member_name)
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


class PublicSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture_license_root = self.root / "licenses"
        self.fixture_license_root.mkdir()
        (self.fixture_license_root / "model-card.md").write_text(
            "fixture model card\n", encoding="utf-8"
        )
        (self.fixture_license_root / "license.html").write_text(
            "<p>fixture license</p>\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_runtime_inputs_pin_exact_public_assets(self) -> None:
        inputs = load_runtime_inputs(ROOT / "runtime-inputs.json")
        self.assertEqual(inputs["schema"], 1)
        self.assertEqual(inputs["layout_version"], 1)
        self.assertEqual(inputs["base_image"], BASE_IMAGE)
        self.assertNotIn("devel", inputs["base_image"])
        self.assertEqual(inputs["models"]["checkpoint"]["size"], 6_938_040_416)
        self.assertEqual(inputs["models"]["face_model"]["size"], 52_026_019)
        for record in inputs["models"].values():
            self.assertTrue(
                record["path"].startswith(
                    "/workspace/sfw-static-public/models/by-sha/"
                )
            )

    def test_runtime_lock_contains_comfy_startup_dependencies(self) -> None:
        inputs = load_runtime_inputs(ROOT / "runtime-inputs.json")
        lock = ROOT / "requirements/sfw_static_runtime_requirements.txt"
        source = lock.read_text(encoding="utf-8").casefold()

        self.assertEqual(
            hashlib.sha256(lock.read_bytes()).hexdigest(),
            inputs["runtime"]["requirements_sha256"],
        )
        for requirement in ("pydantic==", "pydantic-core==", "sqlalchemy=="):
            self.assertIn(requirement, source)

    def test_fetch_verified_never_publishes_wrong_bytes(self) -> None:
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            fetch_verified(
                "https://example.invalid/model",
                self.root / "model.bin",
                7,
                hashlib.sha256(b"correct").hexdigest(),
                opener=lambda request: io.BytesIO(b"wrong!!"),
            )
        self.assertFalse((self.root / "model.bin").exists())
        self.assertFalse((self.root / "model.bin.part").exists())

    def test_fetch_verified_rejects_wrong_size_and_existing_destination(self) -> None:
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            fetch_verified(
                "https://example.invalid/model",
                self.root / "model.bin",
                8,
                hashlib.sha256(b"correct").hexdigest(),
                opener=lambda request: io.BytesIO(b"correct"),
            )
        destination = self.root / "existing.bin"
        destination.write_bytes(b"keep")
        with self.assertRaisesRegex(FileExistsError, "destination exists"):
            fetch_verified(
                "https://example.invalid/model",
                destination,
                4,
                hashlib.sha256(b"keep").hexdigest(),
                opener=lambda request: io.BytesIO(b"keep"),
            )
        self.assertEqual(destination.read_bytes(), b"keep")

    def test_manifest_is_canonical_and_binds_source_and_license_hashes(self) -> None:
        manifest = render_image_manifest(
            load_runtime_inputs(ROOT / "runtime-inputs.json"),
            "1" * 40,
            self.fixture_license_root,
        )
        self.assertEqual(
            manifest["payload_sha256"], canonical_sha256(manifest["payload"])
        )
        self.assertEqual(
            manifest["payload"]["public_source"]["revision"], "1" * 40
        )
        self.assertEqual(
            [entry["path"] for entry in manifest["payload"]["licenses"]],
            ["license.html", "model-card.md"],
        )
        self.assertEqual(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            canonical_json_text(manifest),
        )

    def test_materialize_runtime_excludes_external_models(self) -> None:
        source_records = {}
        for name in ("comfyui", "impact-pack", "impact-subpack"):
            repository, revision, archive_sha256 = _make_git_source(
                self.root, name, f"{name}\n".encode()
            )
            source_records[name] = {
                "url": str(repository),
                "revision": revision,
                "archive_sha256": archive_sha256,
            }
        model_bytes = b"fixture-public-model"
        model_sha256 = hashlib.sha256(model_bytes).hexdigest()
        model_source = self.root / "fixture-model.bin"
        model_source.write_bytes(model_bytes)
        inputs = {
            "schema": 1,
            "layout_version": 1,
            "base_image": BASE_IMAGE,
            "runtime": {"requirements_sha256": "0" * 64},
            "sources": source_records,
            "models": {
                "fixture": {
                    "url": model_source.as_uri(),
                    "filename": "fixture-model.bin",
                    "size": len(model_bytes),
                    "sha256": model_sha256,
                    "path": (
                        f"/workspace/sfw-static-public/models/by-sha/{model_sha256}/"
                        "fixture-model.bin"
                    ),
                }
            },
        }
        image_root = self.root / "image-root"
        materialize_runtime(inputs, image_root)
        self.assertTrue((image_root / "opt/sfw-static/runtime/ComfyUI").is_dir())
        self.assertTrue(
            (
                image_root
                / "opt/sfw-static/runtime/ComfyUI/custom_nodes/ComfyUI-Impact-Pack"
            ).is_dir()
        )
        self.assertTrue(
            (
                image_root
                / "opt/sfw-static/runtime/ComfyUI/custom_nodes/ComfyUI-Impact-Subpack"
            ).is_dir()
        )
        self.assertFalse((image_root / "opt/sfw-static/models").exists())
        self.assertFalse((image_root / "workspace").exists())
        self.assertFalse(any(path.name == ".git" for path in image_root.rglob("*")))

    def test_containerfile_uses_pinned_base_and_build_time_runtime(self) -> None:
        recipe = (ROOT / "Containerfile").read_text(encoding="utf-8")
        self.assertEqual(recipe.count(f"FROM {BASE_IMAGE}"), 2)
        self.assertIn("ARG PUBLIC_SOURCE_REVISION", recipe)
        self.assertIn("--target /opt/sfw-static/site-packages", recipe)
        self.assertIn("PYTHONPATH=/opt/sfw-static/site-packages", recipe)
        runtime_stage = recipe.split(" AS runtime", 1)[1]
        self.assertIn("openssh-server=1:8.9p1-3ubuntu0.16", runtime_stage)
        self.assertEqual(runtime_stage.count("openssh-server="), 1)
        self.assertIn("--no-install-recommends", runtime_stage)
        self.assertIn("/var/lib/apt/lists/* /var/cache/apt/*", runtime_stage)
        self.assertNotIn("buildah", recipe.casefold())
        self.assertNotIn("podman", recipe.casefold())
        self.assertNotIn("docker build", recipe.casefold())
        self.assertIn('ENTRYPOINT ["/opt/sfw-static/start-sshd.sh"]', recipe)
        self.assertIn("EXPOSE 22", recipe)
        self.assertIn("ARG RUNTIME_MANIFEST_SHA256", recipe)
        self.assertIn("--require-hashes", recipe)
        self.assertIn("--no-deps", recipe)
        self.assertIn("--ignore-installed", recipe)
        self.assertIn("COPY --from=materializer /prepared/opt /opt", recipe)
        self.assertIn(
            "org.opencontainers.image.source=\"https://github.com/jeffadamsc/"
            "pacing-rpg-render-base\"",
            recipe,
        )
        self.assertIn(
            "org.pacing-rpg.runtime-layout-version=\"1\"",
            recipe,
        )
        self.assertNotIn("/opt/sfw-static/models", recipe)
        self.assertNotIn("/workspace/sfw-static-public", recipe)

    def test_registry_native_contract_has_exact_runtime_configuration(self) -> None:
        recipe = (ROOT / "Containerfile").read_text(encoding="utf-8")
        startup = (ROOT / "scripts/start-sshd.sh").read_text(encoding="utf-8")
        for label in (
            "org.opencontainers.image.source",
            "org.opencontainers.image.revision",
            "org.opencontainers.image.licenses",
            "org.pacing-rpg.runtime-manifest-sha256",
            "org.pacing-rpg.runtime-layout-version",
        ):
            self.assertIn(label, recipe)
        self.assertNotIn("models/by-sha", recipe)
        for setting in (
            "PIP_DISABLE_PIP_VERSION_CHECK=1",
            "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONPATH=/opt/sfw-static/site-packages",
        ):
            self.assertIn(setting, recipe)
        self.assertIn("ssh-keygen -A", startup)
        self.assertRegex(startup, r"mkdir -p [^\n]*/run/sshd")
        self.assertNotIn("/run/sshd", "\n".join(
            line for line in recipe.splitlines()
            if line.lstrip().startswith(("COPY ", "ADD "))
        ))

    def test_startup_is_install_free_and_workflow_never_builds_image(self) -> None:
        startup = (ROOT / "scripts/start-sshd.sh").read_text(encoding="utf-8")
        lowered = startup.lower()
        for forbidden in ("apt", "git", "pip", "curl", "huggingface"):
            self.assertNotRegex(lowered, rf"\b{forbidden}\b")
        self.assertIn('"${SSH_PUBLIC_KEY:?', startup)
        self.assertIn("exec /usr/sbin/sshd -D -e", startup)
        workflow = (ROOT / ".github/workflows/verify.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python3 -m unittest discover -v", workflow)
        for forbidden in ("docker build", "buildah", "podman"):
            self.assertNotIn(forbidden, workflow.lower())

    def test_public_inputs_bind_exact_source_archive_hashes(self) -> None:
        inputs = load_runtime_inputs(ROOT / "runtime-inputs.json")
        self.assertEqual(
            inputs["sources"]["comfyui"]["archive_sha256"],
            "ca23d01341b8d36e4f794f5cf06b532554944fddfb2d9e3abe5f1ad82692ccd1",
        )
        self.assertEqual(
            inputs["sources"]["impact-pack"]["archive_sha256"],
            "0e872810f1718d58d41ef4ad95bab6dd3e31eb9cf1f1312e875d0d3c97569348",
        )
        self.assertEqual(
            inputs["sources"]["impact-subpack"]["archive_sha256"],
            "a059290adcb1021a7f230a1d5d4030bf87f28bc44b02ca3b567cf58365dba685",
        )


if __name__ == "__main__":
    unittest.main()
