# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Build a TunerSession for a VDO Mk4 cluster EEPROM.

The session's ``binfile`` is the 2 KB EEPROM (little-endian: the cluster is
a 65C02-family CDC16xxF-E). This turns the identified family's definition
(:mod:`ovtsuite.vdo.defs`) into editable :class:`VdoEntity` objects that load,
compare, search and patch like every other platform's parameters.

:class:`VdoEntity` is an :class:`ovtsuite.model.Entity` with the three things
a cluster EEPROM needs that an ECU calibration does not:

* ``bit_mask`` -- a coding option that is one bit (or a few) of a shared
  byte. Reads shift the field down; writes are read-modify-write, so the
  other bits in the byte are never touched.
* ``mirrors`` -- redundant copies (the SKC is stored three times); an edit
  writes every copy.
* ``options`` -- raw value -> label, shown in the table instead of the bare
  number (and accepted as input).

``cell_writes`` is the single place a cell edit becomes byte writes, used by
both ``set_cell`` and ``TunerSession.edit_cells`` -- so undo, the change log,
version history and patch apply all see exactly the bytes that changed.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..model import Entity
from ..progress import Reporter
from .. import groups as _groups
from . import defs as _defs
from .identify import identify, patch_header

#: Parameter group -> tree group id (ovtsuite.groups).
GROUP_TIER = {
    "gauges": getattr(_groups, "CLUSTER_GAUGES", _groups.VEHICLE),
    "coding": getattr(_groups, "CLUSTER_CODING", _groups.VEHICLE),
    "identity": getattr(_groups, "CLUSTER_IDENTITY", _groups.VEHICLE),
    "firmware": getattr(_groups, "CLUSTER_FIRMWARE", _groups.INTERNALS),
}

FLAG_OPTIONS = {0: "Off", 1: "On"}


@dataclass
class VdoEntity(Entity):
    bit_mask: int = 0
    mirrors: Tuple[int, ...] = ()
    options: Dict[int, str] = field(default_factory=dict)
    row_labels: List[str] = field(default_factory=list)
    col_labels: List[str] = field(default_factory=list)
    read_only: bool = False
    role: str = ""
    confidence: str = "verified"
    vmin: Optional[float] = None
    vmax: Optional[float] = None

    # -- bit fields ----------------------------------------------------
    @property
    def _shift(self) -> int:
        m, s = self.bit_mask, 0
        while m and not m & 1:
            m >>= 1
            s += 1
        return s

    def raw_cell(self, r: int, c: int):
        v = self.binfile.read(self._cell_addr(r, c), self.bits, self.signed)
        if self.bit_mask:
            v = (v & self.bit_mask) >> self._shift
        return v

    @property
    def raw_range(self) -> tuple:
        if self.bit_mask:
            return (0, self.bit_mask >> self._shift)
        return super().raw_range

    @property
    def value_range(self) -> tuple:
        lo, hi = super().value_range
        if self.vmin is not None:
            lo = max(lo, self.vmin)
        if self.vmax is not None:
            hi = min(hi, self.vmax)
        return (lo, hi)

    # -- writes ----------------------------------------------------------
    def encode_raw(self, display_value) -> int:
        lo, hi = self.raw_range
        raw = int(round(self.eq.encode(float(display_value))))
        if self.vmin is not None or self.vmax is not None:
            dlo, dhi = self.value_range
            raw_lo = int(round(self.eq.encode(dlo)))
            raw_hi = int(round(self.eq.encode(dhi)))
            lo, hi = max(lo, min(raw_lo, raw_hi)), min(hi, max(raw_lo, raw_hi))
        return max(lo, min(hi, raw))

    def cell_writes(self, r: int, c: int, display_value,
                    data=None) -> List[Tuple[int, int, int, int]]:
        """``(addr, bits, old, new)`` for writing one cell, every mirror
        included, in display units. ``data`` defaults to the live image."""
        bf = self.binfile
        raw = self.encode_raw(display_value)
        if raw < 0:
            raw += 1 << self.bits
        out = []
        off = self.index(r, c) * self.step
        for base in (self.addr,) + tuple(self.mirrors):
            a = base + off
            old = bf.read(a, self.bits, False)
            new = raw
            if self.bit_mask:
                new = (old & ~self.bit_mask & ((1 << self.bits) - 1)) | (
                    (raw << self._shift) & self.bit_mask)
            out.append((a, self.bits, old, new))
        return out

    def set_cell(self, r: int, c: int, display_value: float) -> float:
        for a, bits, _old, new in self.cell_writes(r, c, display_value):
            self.binfile.write(a, new, bits)
        return self.cell(r, c)

    @property
    def end(self) -> int:
        return self.addr + self.n_cells * self.step

    def option_label(self, raw) -> Optional[str]:
        try:
            return self.options.get(int(round(raw)))
        except (TypeError, ValueError):
            return None


def _describe(p, opts, mirrors, ident) -> str:
    lines = [p.description] if p.description else []
    if opts:
        lines.append("Values: " + "; ".join(
            "%s = %s" % (("0x%02X" % k) if p.kind in ("enum", "hex") and k > 9
                         else str(k), v)
            for k, v in sorted(opts.items())))
    if p.mask and p.kind in ("flag", "enum"):
        lines.append("Bits 0x%02X of the byte at 0x%03X; the other bits are "
                     "left untouched." % (p.mask, p.address))
    if mirrors:
        lines.append("Also stored at %s; an edit writes every copy."
                     % ", ".join("0x%03X" % m for m in mirrors))
    if p.checksummed:
        lines.append("Covered by the gauge checksum (corrected on save).")
    if not p.editable:
        lines.append("Read-only in the table; it is carried by patches and "
                     "whole-cluster transfers.")
    if p.not_on_lowline:
        lines.append("Not present on lowline (LL) clusters.")
    if p.confidence != "verified":
        lines.append("UNCONFIRMED for %s: this address is extrapolated from "
                     "another ROM family and has not been checked against a "
                     "real %s EEPROM." % (ident.family, ident.family))
    return "\n\n".join(lines)


def build_entities(binfile, defn, ident) -> List[VdoEntity]:
    out: List[VdoEntity] = []
    order = 0
    for p in defn.params:
        if p.not_on_lowline and ident.lowline:
            continue
        opts = dict(p.options_for(ident.chassis))
        if p.kind == "flag" and not opts:
            opts = dict(FLAG_OPTIONS)
        mirrors = tuple(p.address + p.copy_stride * (i + 1)
                        for i in range(p.copies))
        n = p.rows * p.cols
        kind = "constant" if n == 1 else "indexed"
        text_kind = {"text": "ascii", "hex": "hex"}.get(p.kind, "")
        e = VdoEntity(
            name=p.name, kind=kind, tier=GROUP_TIER[p.group],
            categories=[p.heading] if p.heading else [],
            category_path=[p.heading] if p.heading else [],
            description=_describe(p, opts, mirrors, ident), units=p.units,
            addr=p.address, rows=p.rows, cols=p.cols, bits=p.bits,
            signed=False, equation=p.equation,
            source="verified" if p.confidence == "verified" else "projected",
            binfile=binfile, declared_rows=p.rows, declared_cols=p.cols,
            order="row", text_kind=text_kind,
            note="%s definition, 0x%03X (%s)" % (defn.family, p.address,
                                                 p.source or "definition"),
            bit_mask=p.mask if p.kind in ("flag", "enum") else 0,
            mirrors=mirrors, options=opts if p.kind != "text" else {},
            row_labels=list(p.row_labels), col_labels=list(p.col_labels),
            read_only=not p.editable, role=p.role, confidence=p.confidence,
            vmin=p.min, vmax=p.max,
            # The definition names every field: the tree and the table tab
            # show that name (catalogue.display_name), not a label cut from
            # the description -- which read "Soft-coding digits 1-2" four times.
            plain=p.name)
        e.cat_order = order
        order += 1
        out.append(e)
    pm = defn.patch_module
    if pm:
        out.append(_patch_entity(binfile, defn, ident, pm, order))
    return out


def patch_entity_name(ident) -> str:
    """The patch block is code for ONE exact ROM build, so the ROM build is
    part of its identity: a patch captured on VWK501MH 01.10 resolves only
    on another VWK501MH 01.10, and simply does not exist on any other ROM --
    cross-version patching cannot carry it somewhere it would crash."""
    return "Firmware patch module (%s)" % (
        ident.rom_version if ident.rom_version else "ROM not identified")


def _patch_entity(binfile, defn, ident, pm, order) -> VdoEntity:
    start, end = pm["address"], pm["end"]
    hdr = patch_header(bytes(binfile.data), start, end)
    if hdr is None:
        state = "No patch block is loaded (header erased)."
    elif hdr.valid:
        state = ("Patch block present: %d bytes of code, %d bytes of patch "
                 "table, header checksum valid." % (hdr.code_len, hdr.data_len))
    else:
        state = "A patch header is present but the cluster would reject it."
    desc = (pm.get("description", "") + "\n\n" + state + "\n\n"
            "Identified as %s (%s). The name carries the ROM build because "
            "the block only runs on that build; a patch never applies it to "
            "a different ROM." % (
                ident.rom_version or "an unidentified ROM",
                ("reported by the cluster" if ident.rom_source == "cluster"
                 else "from this patch header" if ident.rom_source
                 else "no exact ROM known")))
    e = VdoEntity(
        name=patch_entity_name(ident), kind="indexed",
        tier=GROUP_TIER["firmware"], categories=["Patch module"],
        category_path=["Patch module"], description=desc, units="",
        addr=start, rows=1, cols=end - start, bits=8, signed=False,
        equation="X", source="verified", binfile=binfile,
        declared_rows=1, declared_cols=end - start, order="row",
        text_kind="hex",
        note="%s patch module 0x%03X-0x%03X" % (defn.layout, start, end - 1),
        role="patch_module", confidence="verified", plain=patch_entity_name(ident))
    e.cat_order = order
    return e


def build(session, family: Optional[str] = None, progress=None) -> None:
    """Populate ``session`` for the VDO cluster platform."""
    rep = Reporter.of(progress, "vdo")
    # The cluster CPU is a 65C02-family part: 16-bit values are stored low
    # byte first. BinaryFile picks big-endian unless the image is an EDC15.
    session.binfile.endian = "<"
    data = bytes(session.binfile.data)
    cont = getattr(session, "_container", None)
    meta = cont.meta() if cont is not None else {}
    rep.step("Identifying the cluster ROM")
    ident = identify(data, meta, family)
    if ident is None:
        raise ValueError("not a VDO Mk4 cluster EEPROM")
    defn = _defs.get(ident.family)

    session.platform = "vdo"
    session.datasets = []            # EDC15-only fields the GUI reads defensively
    session.match15 = None
    session.message_table = None
    session.family_choice = None
    session.family = defn.family
    session.region = (0, len(data))
    session.vdo_identity = ident
    session.vdo_definition = defn
    session.vdo_meta = dict(meta)

    rep.step("Loading the %s definition" % defn.family)
    session.entities = build_entities(session.binfile, defn, ident)
    session.by_key = {(e.name, e.addr): e for e in session.entities}
    rep.step("Building the parameter tree")

    notes = list(ident.notes)
    if defn.status != "verified":
        notes.append("The %s definition is EXTRAPOLATED from VWK503: only the "
                     "immobilizer, key, SKC, VIN, odometer and radio-ID "
                     "addresses are confirmed for this ROM. Parameters marked "
                     "unconfirmed need checking before a write."
                     % defn.family)
    if not ident.rom_version:
        notes.append("The exact ROM build is not known (no patch block to "
                     "read it from, and the file was not read from the cluster); "
                     "%s layout parameters are shown." % ident.layout)
    if notes and not getattr(session, "load_note", None):
        session.load_note = " ".join(notes)
    rep.finish("%d parameters" % len(session.entities))


def odometer_km(session) -> Optional[int]:
    """The odometer reading in km (sum of the eight counters), or None."""
    e = next((x for x in session.entities
              if getattr(x, "role", "") == "odometer"), None)
    if e is None:
        return None
    return int(round(sum(v for row in e.values() for v in row)))


def summary(session) -> List[Tuple[str, str]]:
    """``(label, value)`` rows for the file-information panel and the CLI."""
    ident = session.vdo_identity
    defn = session.vdo_definition
    rows = [("Platform", "VDO instrument cluster (2 KB EEPROM)"),
            ("Definition", "%s (%s)" % (defn.family, defn.status)),
            ("EEPROM layout", ident.layout)]
    if ident.rom_version:
        rows.append(("ROM version", "%s  (%s)" % (
            ident.rom_version, "reported by the cluster"
            if ident.rom_source == "cluster" else "from the patch header")))
    elif ident.candidates:
        rows.append(("ROM version", "one of " + " / ".join(ident.candidates)))
    else:
        rows.append(("ROM version", "not identified"))
    if ident.lowline is not None:
        rows.append(("Lowline", "yes" if ident.lowline else "no"))
    if ident.chassis:
        rows.append(("Vehicle family", "%s (byte 0x%02X)"
                     % (ident.chassis, ident.family_byte)))
    meta = getattr(session, "vdo_meta", {}) or {}
    for key, label in (("ident", "Cluster ident"), ("coding", "Soft coding"),
                       ("workshop", "Workshop code"), ("read_at", "Read on")):
        if meta.get(key):
            rows.append((label, str(meta[key])))
    for role, label in (("vin", "VIN"), ("part_number", "Part number"),
                        ("immo_id", "Immobilizer ID")):
        e = next((x for x in session.entities
                  if getattr(x, "role", "") == role), None)
        if e is not None:
            txt = "".join(chr(int(v)) if 0x20 <= int(v) < 0x7F else "."
                          for v in e.values()[0]).strip()
            rows.append((label, txt))
    skc = next((x for x in session.entities if x.role == "skc"), None)
    if skc is not None:
        rows.append(("SKC", "%05d" % int(skc.cell(0, 0))))
    km = odometer_km(session)
    if km is not None:
        rows.append(("Odometer", "%d km (%d mi on the cluster's 103/64 "
                                 "conversion)" % (km, int(km * 64 / 103))))
    try:
        rep = session.checksum_status()
        if rep is not None:
            rows.append(("Checksums", "valid" if rep.ok else "MISMATCH -- "
                         "corrected on save"))
    except Exception:
        pass
    return rows
