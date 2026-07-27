# Tier 2's sandbox. Built once, then run per step with no network, a read-only root,
# a memory cap and a hard timeout. If any of that stops Lean from answering, the verifier
# reports "unverifiable" — never "invalid".
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl git ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m lean
USER lean
WORKDIR /home/lean

ENV ELAN_HOME=/home/lean/.elan
ENV PATH=/home/lean/.elan/bin:$PATH

RUN curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
      -o elan-init.sh \
    && sh elan-init.sh -y --default-toolchain leanprover/lean4:v4.15.0 \
    && rm elan-init.sh

# A project whose only purpose is to have mathlib built and cached in the image, so that
# a per-step run does no compilation of its own.
RUN mkdir -p /home/lean/warrant-lean
WORKDIR /home/lean/warrant-lean
COPY --chown=lean:lean lakefile.toml lean-toolchain ./
RUN lake update && lake exe cache get && lake build

ENV LEAN_PATH=/home/lean/warrant-lean/.lake/packages/mathlib/.lake/build/lib

ENTRYPOINT ["lake", "env", "lean"]
