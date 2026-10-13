# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Identify a VDO Mk4 cluster EEPROM: layout, ROM family, exact ROM build.

Everything here reads format-defined structure -- a checksum the cluster
itself enforces, a field whose format the immobilizer defines, the patch
module's own header -- and never infers identity from what the bytes happen
to look like. In order of authority:

1. **The cluster's own word.** A ``.vdo`` read by this app's flasher stores the
   ReadSoftwareVersion reply ("VWK501MH 01.10") in its metadata. Nothing
   below overrides it.
2. **The patch-module header.** H4/H5 name the exact ROM build the patch was
   written for (KWHack Reference/PatchModule.md): H4 = version byte 8, and H5
   = version byte 9, or -- when its top bit is set -- the sum of every version
   byte except byte 8, OR 0x80. A header whose own checksum (H0) verifies is
   matched against every ROM version string the definitions know. Verified on
   every sample that carries a patch.
3. **The layout alone.** The gauge / K-value checksum (which the cluster
   checks at power-up, 'dEF' otherwise) and the immobilizer-ID field sit at
   different, fixed addresses in the two layouts. Checked on 50 real
   EEPROMs: the split is total.

``identify()`` reports which of these settled the answer, so the GUI can say
"from the cluster" vs "from the patch header" vs "layout only".
"""

from dataclasses import dataclass, field
from typing import List, Optional

from . import EEPROM_SIZE, LAYOUTS
# The format-level half (layouts, checksum, immobilizer field, patch header,
# ROM version bytes) is base-app knowledge; re-exported here unchanged.
from ..platforms.vdo import (  # noqa: F401
    IMMO_ID_RE, _BLANK_IMMO, CHASSIS, checksum_ok, immo_id_ok, layout_of,
    rom_bytes, version_string, header_rom_match, PatchHeader, patch_checksum,
    patch_header)


# ---------------------------------------------------------------- identity
@dataclass
class Identity:
    layout: str
    family: str                       # definition family (VWK501, VMMJ08 ...)
    rom_version: str = ""             # "VWK501MH 01.10", "" when unknown
    rom_source: str = ""              # "cluster" | "patch header" | ""
    candidates: List[str] = field(default_factory=list)
    lowline: Optional[bool] = None
    chassis: Optional[str] = None
    family_byte: Optional[int] = None
    notes: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.rom_version or ("%s layout" % self.layout)


def _family_of_version(version: str, families) -> Optional[str]:
    head = (version or "")[:6]
    for fam in families:
        if fam == head:
            return fam
    return None


def identify(data: bytes, meta: Optional[dict] = None,
             family: Optional[str] = None) -> Optional[Identity]:
    """Identify ``data`` (a 2 KB EEPROM). ``meta`` is a ``.vdo`` container's
    metadata (its ``rom_version`` is the cluster's own reply); ``family``
    forces a definition family (still checked against the layout).

    Returns None when ``data`` is not a supported cluster EEPROM."""
    from . import defs as _defs
    meta = meta or {}
    lay = layout_of(data)
    if lay is None and meta.get("layout") in LAYOUTS and len(data) == EEPROM_SIZE:
        # A container states its layout; a broken checksum AND a blanked
        # immobilizer field must not lose the file.
        lay = meta["layout"]
    if lay is None:
        return None
    all_defs = _defs.all_definitions()
    in_layout = [f for f, d in all_defs.items() if d.layout == lay]
    ident = Identity(layout=lay, family=lay)

    # Only the cluster's own ReadSoftwareVersion reply is authoritative; a
    # version a save recorded from the patch header is simply re-derived.
    reported = (meta.get("rom_version") or "").strip()
    if meta.get("rom_source", "cluster") != "cluster":
        reported = ""
    if reported:
        fam = _family_of_version(reported, all_defs)
        if fam is not None and all_defs[fam].layout != lay:
            ident.notes.append(
                "the cluster reported %s, a %s-layout ROM, but the EEPROM is "
                "%s layout -- trusting the EEPROM's structure"
                % (reported, all_defs[fam].layout, lay))
        elif fam is not None:
            ident.family = fam
            ident.rom_version = reported
            ident.rom_source = "cluster"
        else:
            ident.rom_version = reported
            ident.rom_source = "cluster"
            ident.notes.append("no definition for ROM %s; using the %s "
                               "layout's" % (reported, lay))

    if not ident.rom_source:
        # The patch header names the exact ROM build -- when it verifies.
        hdr = patch_header(data, LAYOUTS[lay]["patch"])
        if hdr is not None and hdr.valid:
            hits = [v for f in in_layout for v in all_defs[f].rom_versions
                    if header_rom_match(hdr.h[4], hdr.h[5], v)]
            ident.candidates = hits
            if len(hits) == 1:
                ident.rom_version = hits[0]
                ident.rom_source = "patch header"
                ident.family = _family_of_version(hits[0], all_defs) or lay
            elif hits:
                fams = {_family_of_version(v, all_defs) for v in hits}
                if len(fams) == 1:
                    ident.family = fams.pop() or lay
                ident.notes.append("patch header matches %s"
                                   % " / ".join(hits))

    if family:
        if family not in all_defs:
            raise ValueError("no VDO definition named %r" % family)
        if all_defs[family].layout != lay:
            raise ValueError("%s is a %s-layout definition; this EEPROM is "
                             "%s layout" % (family, all_defs[family].layout,
                                            lay))
        ident.family = family

    if ident.rom_version:
        ident.lowline = ident.rom_version[6:8] == "LL"
    d = all_defs.get(ident.family)
    if d is not None and d.vehicle_family_address is not None:
        fb = data[d.vehicle_family_address]
        ident.family_byte = fb
        ident.chassis = CHASSIS.get(fb & 0x0F)
    return ident
