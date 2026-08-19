# Pacing RPG render base

This public repository defines a reproducible, public-only OCI runtime for the
Pacing RPG static rendering pipeline. It contains ComfyUI, two public custom
node projects, public model provenance, their public license material, and the
locked Python runtime. The checkpoint and face-detection model are external
requirements mounted below `/workspace/sfw-static-public`; the image contains no
model bytes. It contains no
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
fixed external-volume paths. A controller creates canonical `image-manifest.json`, then a
bounded external builder supplies its source revision and manifest hash as build
arguments. The build refuses missing or malformed bindings.

The `Containerfile` is the readable public reference contract. Production
publication materializes the same files and configuration with pinned skopeo
and umoci tools, without starting a nested container builder or changing the
published runtime contents.

See `THIRD_PARTY_NOTICES.md` and `LICENSES/` for upstream provenance and terms.
