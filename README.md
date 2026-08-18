# Pacing RPG render base

This public repository defines a reproducible, public-only OCI runtime for the
Pacing RPG static rendering pipeline. It contains ComfyUI, two public custom
node projects, one public base checkpoint, one public face-detection model,
their public license material, and the locked Python runtime. It contains no
prompts, private LoRAs, job records, generated images, or private application
source.

The image must be consumed by immutable digest:

```text
ghcr.io/jeffadamsc/pacing-rpg-render-base@sha256:<64 lowercase hex characters>
```

Tags are publication aids only and are not valid runtime authority.

## Offline verification

```bash
python3 -m unittest discover -v
```

These tests inspect the pinned inputs, deterministic manifest and source layout,
Containerfile, and install-free SSH entry point. They do not download models or
build the image.

## Reproduction

`runtime-inputs.json` pins the base image digest, public Git revisions,
deterministic archive hashes, public model URLs, byte sizes, SHA-256 values, and
fixed image paths. A controller creates canonical `image-manifest.json`, then a
bounded external builder supplies its source revision and manifest hash as build
arguments. The build refuses missing or malformed bindings.

See `THIRD_PARTY_NOTICES.md` and `LICENSES/` for upstream provenance and terms.
