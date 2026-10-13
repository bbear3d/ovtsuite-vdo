# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Moved to :mod:`ovtsuite.platforms.vdo_container` (container formats belong to the base app, so the flasher can save .vdo files).

This name stays importable: it IS that module (one object, so a monkeypatch
through either name affects both).
"""
import sys

from ..platforms import vdo_container as _moved

sys.modules[__name__] = _moved
