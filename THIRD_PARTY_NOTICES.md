# Third-party notices

This inventory covers only the public runtime inputs in this repository and its
OCI image. It makes no claim about licensing of private derivatives or private
assets kept outside this repository.

- Base image: `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`, pinned
  by the digest recorded in `runtime-inputs.json`. Its inherited notices and
  licenses remain in the base image.
- ComfyUI: <https://github.com/comfyanonymous/ComfyUI>, revision
  `7c8450ef2b720bb096f0d94ff933c62fd174cb57`.
- ComfyUI Impact Pack: <https://github.com/ltdrdata/ComfyUI-Impact-Pack>,
  revision `429d0159ad429e64d2b3916e6e7be9c22d025c3c`.
- ComfyUI Impact Subpack:
  <https://github.com/ltdrdata/ComfyUI-Impact-Subpack>, revision
  `50c7b71a6a224734cc9b21963c6d1926816a97f1`.
- NoobAI-XL v1.0 checkpoint: public model file and model card at
  <https://huggingface.co/Laxhar/noobai-XL-1.0/tree/70dee4d903b83cc6d1e8d12e65051cfdbcf54ab3>.
  The reviewed model-card snapshot is
  `LICENSES/NoobAI-XL-v1.0-model-card.md`; its linked additional license is
  snapshotted as `LICENSES/fair-ai-public-license-1.0-sd.html`.
- ADetailer face model: `face_yolov8m.pt` from
  <https://huggingface.co/Bingsu/adetailer/tree/53cc19de382014514d9d4038601d261a7faa9b7b>.

Exact model filenames, revisions, byte sizes, SHA-256 values, and download URLs
are recorded in `runtime-inputs.json`. Exact source archive hashes prove the
normalized source trees used by the image build.

The locked Python dependency file is
`requirements/sfw_static_runtime_requirements.txt`; each package artifact is
selected by hash. Upstream package licenses apply.
