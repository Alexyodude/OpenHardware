# OpenHardware - devices a board's pins can be wired to.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Parts that answer on a bus, each a pure function of what it was told.

A device here has no clock and no randomness: what it answers depends on the
bus traffic and the inputs it was held at, so a replay of the same drives
reproduces it (`rules/determinism.md`).
"""
