FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04@sha256:61a4aafb0094cd773f11eefa378929d5a687bd775febeb78eac62fc824141fb5 AS materializer

ENV DEBIAN_FRONTEND=noninteractive \
    GIT_TERMINAL_PROMPT=0 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
COPY runtime-inputs.json /build/source/runtime-inputs.json
COPY scripts/materialize_runtime.py /build/source/scripts/
RUN python3 /build/source/scripts/materialize_runtime.py \
    --inputs /build/source/runtime-inputs.json \
    --destination /prepared

FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04@sha256:61a4aafb0094cd773f11eefa378929d5a687bd775febeb78eac62fc824141fb5 AS runtime

ARG PUBLIC_SOURCE_REVISION
ARG RUNTIME_MANIFEST_SHA256
RUN python3 -c 'import re,sys; assert re.fullmatch(r"[0-9a-f]{40}",sys.argv[1]); assert re.fullmatch(r"[0-9a-f]{64}",sys.argv[2])' \
    "${PUBLIC_SOURCE_REVISION}" "${RUNTIME_MANIFEST_SHA256}"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/sfw-static/site-packages
COPY requirements/sfw_static_runtime_requirements.txt /tmp/sfw-static-runtime-requirements.txt
RUN python3 -m pip install --no-cache-dir --no-deps --require-hashes \
      --target /opt/sfw-static/site-packages \
      -r /tmp/sfw-static-runtime-requirements.txt \
    && rm -f /tmp/sfw-static-runtime-requirements.txt

COPY --from=materializer /prepared/opt /opt
COPY image-manifest.json /opt/sfw-static/image-manifest.json
COPY scripts/start-sshd.sh /opt/sfw-static/start-sshd.sh
COPY Containerfile runtime-inputs.json README.md THIRD_PARTY_NOTICES.md \
    /usr/share/sfw-static/source/
COPY requirements /usr/share/sfw-static/source/requirements
COPY scripts /usr/share/sfw-static/source/scripts
COPY LICENSES /usr/share/sfw-static/source/LICENSES

RUN chmod 0555 /opt/sfw-static/start-sshd.sh \
    && chmod 0444 /opt/sfw-static/image-manifest.json

LABEL org.opencontainers.image.source="https://github.com/jeffadamsc/pacing-rpg-render-base" \
      org.opencontainers.image.revision="${PUBLIC_SOURCE_REVISION}" \
      org.opencontainers.image.licenses="fair-ai-public-license-1.0-sd" \
      org.pacing-rpg.runtime-manifest-sha256="${RUNTIME_MANIFEST_SHA256}" \
      org.pacing-rpg.runtime-layout-version="1"

EXPOSE 22
ENTRYPOINT ["/opt/sfw-static/start-sshd.sh"]
