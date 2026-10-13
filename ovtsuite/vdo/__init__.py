# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""VDO instrument clusters of the VW Mk4 / B5 era (VWK501, VWK503, VMMJ08,
VQMJ07, K5MJ07): the 2 KB serial EEPROM as an editable platform.

The cluster's firmware is mask ROM; everything a tuner, a swap or a cluster
replacement touches -- K-value, needle maps, soft coding, options, the
immobilizer / VIN / odometer data -- lives in its 2048-byte EEPROM, read and
written over K-line KW1281 (see :mod:`ovtsuite.flash.vdo_cluster`). That
EEPROM is this platform's main image.

Two physical layouts exist among the supported ROMs, told apart purely by
format-defined structure, never by guessing at content (see
:mod:`ovtsuite.vdo.identify`):

* ``VWK501``: gauge / K-value checksum at 0x14E, immobilizer ID at 0xA2,
  patch-module header at 0x4F4.
* ``VWK503`` (also VMMJ08, and by extrapolation VQMJ07 / K5MJ07): checksum
  at 0x190, immobilizer ID at 0xE0, patch-module header at 0x4F6.

Within a layout, the exact ROM build comes from the cluster's own
ReadSoftwareVersion reply when the file was read by the app's flasher (stored in the
``.vdo`` container's metadata), or else from the patch-module header's ROM
match bytes (H4/H5), checked against every known ROM version string.

Parameters are defined per ROM family in ``ovtsuite/data/vdo_*.json``
(:mod:`ovtsuite.vdo.defs`). A parameter's NAME is the same in every family
that has it, which is what makes a patch captured on one family apply to
another (``ovtsuite.patch`` resolves entries by name against the target's own
addresses).
"""

# The layout anchors and the structural detector are base-app knowledge
# (ovtsuite.platforms.vdo), so a VDO EEPROM is recognised without this module.
from ..platforms.vdo import EEPROM_SIZE, LAYOUTS, detect  # noqa: F401
