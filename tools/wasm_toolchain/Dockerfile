# OpenHardware - the image GCC is compiled to WebAssembly in (OH-244).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# Emscripten 5.0.3, the version tools/build_site.py builds the cores with,
# pinned by digest so a rebuild cannot quietly change compiler. The four
# packages are what GCC 7.3.0, 8.4.0 and 12.3.1, and binutils 2.26, 2.35.1 and
# 2.40, need on the BUILD side: m4 for GMP, bison and flex for ld's grammar,
# makeinfo for binutils' docs.
#
# Each at the version the image's Ubuntu 24.04 gave on 2026-10-16, when two
# builds from nothing gave the same bytes: a build input that moved with the
# archive would make that claim one about a day. bison's is an update, which
# Ubuntu may one day replace; this then stops at apt-get, by name, rather than
# building with another.
FROM emscripten/emsdk:5.0.3@sha256:7b5d14203bb4ef20da6f5b71b90c8f37ec09c2776d342efff3bc989ebf1aa873
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      m4=1.4.19-4build1 bison=2:3.8.2+dfsg-1ubuntu0.24.04.1 flex=2.6.4-8.2build1 \
      texinfo=7.1-3build2 \
 && rm -rf /var/lib/apt/lists/*
# One image for every toolchain; tools/build_compiler.py names the script.
# By pattern, so a toolchain added later changes its own script and not this
# file, which every toolchain's key hashes.
COPY build-*.sh /usr/local/bin/
# A Windows checkout with core.autocrlf hands bash a script it cannot read.
RUN sed -i 's/\r$//' /usr/local/bin/build-*.sh
ENTRYPOINT ["bash"]
