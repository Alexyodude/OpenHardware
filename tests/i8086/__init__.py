# OpenHardware - package marker for the native core suite.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# A package rather than a bare directory so test_conformance.py can do
# `from . import conformance`. Without it pytest imports the test module as
# top-level and the relative import fails.
