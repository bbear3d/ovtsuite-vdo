# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""The VDO Cluster module's declaration (see :mod:`ovtsuite.modules.api`).

Read by the base app's registry; it names this module's hooks without
importing them, so reading it is free.
"""
from ..modules import api as _api

#: The module's own version (independent of the app's): bump it whenever
#: this module's files change -- the build warns when they changed and it did not.
MODULE = _api.ModuleSpec(
    id="vdo", name="VDO Cluster", version="0.1.8",
    platforms=("vdo",),
    capabilities=(_api.CHECKSUM, _api.DEFINITIONS, _api.TOOLS),
    build=".session_vdo:build",
    checksum=".module:checksum",
    menu_tools=".module:menu_tools",
    data=("vdo_*", "cluster_sweep_*"),
    # the checksum slots are per ROM family, read from its definition file
    checksum_data=("vdo_*.json",),
    # open source, published in its own repository (tools/export_public.py);
    # the sweep patches keep their authors' licences (cluster_sweep_LICENSE-*)
    license={"required": False, "terms": "MPL-2.0"},
)


def checksum(session=None):
    """The checksums of the session's cluster definition; without a session,
    of the definition the EEPROM itself identifies as (None if it does not)."""
    from .checksum_vdo import VdoChecksum
    defn = getattr(session, "vdo_definition", None)
    if defn is None:
        return _VdoByImage()
    return _Wrap(VdoChecksum(defn))


def menu_tools():
    """Tools > Needle sweep... -- for a cluster tab."""
    return [_api.MenuTool(
        "Needle sweep...", lambda win: win.current.open_sweep(),
        _api.TOOLS_SETTINGS, icon="needle-sweep",
        tooltip="Apply a needle / LED sweep or DSG-needle patch to a VDO "
                "cluster EEPROM (only patches for its exact ROM build)")]


class _Wrap(_api.ChecksumProvider):
    name = "VDO"

    def __init__(self, inner):
        self._i = inner

    def is_supported(self, data):
        return self._i.is_supported(data)

    def verify(self, data, **opts):
        return self._i.verify(data)

    def correct(self, data, **opts):
        return self._i.correct(data)

    def exempt_ranges(self, data, **opts):
        return self._i.exempt_ranges(data)


class _VdoByImage(_api.ChecksumProvider):
    """For the flasher: pick the definition from the EEPROM's own identity."""
    name = "VDO"

    def _inner(self, data):
        from . import defs as _defs
        from .identify import identify
        from .checksum_vdo import VdoChecksum
        ident = identify(bytes(data))
        if ident is None:
            return None
        return VdoChecksum(_defs.get(ident.family))

    def is_supported(self, data):
        i = self._inner(data)
        return i is not None and i.is_supported(data)

    def verify(self, data, **opts):
        return self._inner(data).verify(data)

    def correct(self, data, **opts):
        return self._inner(data).correct(data)

    def exempt_ranges(self, data, **opts):
        i = self._inner(data)
        return i.exempt_ranges(data) if i is not None else []
