# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Checksums a VDO Mk4 cluster EEPROM carries, verified and corrected.

Two kinds, both from the cluster's own documented behaviour (KWHack
Reference/Checksums.md and PatchModule.md) and both verified on every real
sample available:

* **Gauge / K-value checksum** -- one byte; that byte plus region 1 (8 bytes,
  K-value) plus region 2 (32 bytes, speedometer map) must sum to 0xFF, or
  the cluster shows "dEF". Addresses per definition.
* **Patch-module header checksum (H0)** -- only when a patch block is present
  and its header is self-consistent (sizes obey the module's rules). An
  erased header (H0 == H1, the module's own "no patch" test) is left alone:
  correcting it would be inventing a patch.

The odometer's 7-byte check value is NOT handled: its algorithm is unknown,
so it is never recomputed -- it only ever travels together with the counters
it protects (see the odometer parameters' descriptions).

Shaped like the other platforms' checksum modules (``is_supported`` /
``verify`` / ``correct`` / ``exempt_ranges``) so ``TunerSession`` drives it
the same way; it is an object rather than a module because the addresses
come from the session's definition.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .identify import patch_header, patch_checksum


@dataclass
class Slot:
    name: str
    offset: int
    stored: int
    computed: int

    @property
    def ok(self) -> bool:
        return self.stored == self.computed


@dataclass
class VdoChecksumReport:
    slots: List[Slot] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.slots)

    def describe(self) -> str:
        if not self.slots:
            return "No checksums to verify on this cluster EEPROM."
        parts = ["%s @0x%03X: stored %02X, computed %02X -- %s"
                 % (s.name, s.offset, s.stored, s.computed,
                    "valid" if s.ok else "MISMATCH") for s in self.slots]
        return "\n".join(parts + self.notes)


class VdoChecksum:
    """Checksum handling for one cluster definition."""

    def __init__(self, definition):
        self.defn = definition

    # -- the interface TunerSession uses ---------------------------------
    def is_supported(self, data) -> bool:
        return len(data) == self.defn.eeprom_size

    def _gauge_slots(self, data) -> List[Slot]:
        out = []
        for c in self.defn.checksums:
            total = sum(sum(data[a:a + n]) for a, n in c["regions"])
            want = (c["sum_to"] - total) & 0xFF
            out.append(Slot(c["name"], c["address"], data[c["address"]], want))
        return out

    def _patch_slot(self, data) -> Optional[Slot]:
        pm = self.defn.patch_module
        if not pm:
            return None
        hdr = patch_header(bytes(data), pm["address"], pm["end"])
        if hdr is None:
            return None
        n = hdr.code_len + hdr.data_len
        if not (n > 0 and n % 2 == 0 and hdr.data_len > 3
                and hdr.data_len % 4 == 2):
            return None      # not a block the cluster would load: leave it
        return Slot("Patch module header (H0)", pm["address"], hdr.h[0],
                    hdr.computed_h0)

    def verify(self, data, **_kw) -> VdoChecksumReport:
        data = bytes(data)
        rep = VdoChecksumReport(self._gauge_slots(data))
        ps = self._patch_slot(data)
        if ps is not None:
            rep.slots.append(ps)
        return rep

    def correct(self, data, **_kw) -> bytes:
        out = bytearray(data)
        for s in self._gauge_slots(out):
            out[s.offset] = s.computed
        ps = self._patch_slot(out)
        if ps is not None:
            out[ps.offset] = ps.computed
        return bytes(out)

    def exempt_ranges(self, data, **_kw) -> List[Tuple[int, int]]:
        try:
            return [(s.offset, s.offset + 1) for s in self.verify(data).slots]
        except Exception:
            return []


__all__ = ["VdoChecksum", "VdoChecksumReport", "Slot", "patch_checksum"]
