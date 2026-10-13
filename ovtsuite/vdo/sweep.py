# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Needle / LED sweep (and DSG-needle) patches for VDO clusters: the library,
the checks, and applying one to an open cluster EEPROM.

A sweep patch is a complete memory-patch block (6-byte header + 6502 code +
patch table) that the cluster loads from EEPROM into RAM at boot. It is code
for ONE exact ROM build: the cluster itself only loads it when the header's
H4/H5 match its ROM version, and code written for another build would patch
the wrong ROM addresses. So a patch is offered and applied only when:

* the cluster's ROM build is known -- reported by the cluster when it was read
  (``.vdo``), or read from its current patch header -- and equals the patch's
  ``rom_version``; or, when nothing identifies it, the user explicitly
  confirms that build (``assume_rom``);
* the patch's own header targets that build and its checksum (H0) verifies;
* it sits at this definition's patch-module address and ends inside the patch
  area (before 0x7E0).

The bundled library (``ovtsuite/data/cluster_sweep_patches.json``) holds the
authors' published blocks, unmodified, each under its author's OWN licence,
which travels with it (``license``, ``copyright``, ``credit``, ``url`` and the
``cluster_sweep_LICENSE-*.txt`` text beside the library):

* Bodie Royle (graeme86.com) -- no licence stated, published with his
  permission; credited;
* Feche (blog.feche.ar) -- LGPL-3.0-or-later;
* hayperek (hayperek.pl) -- LGPLv3 (the posts' notice is GPLv3-or-later text);
* gmenounos (github.com/gmenounos/vwcluster) -- MIT, the repository's licence;
* SigurdMyhre (github.com/SigurdMyhre/VWK501-DSG-Needle) -- Apache-2.0.

The published hex is each patch's only source form. A ``.patch`` file in
KWHack's format (``Name:/Variant:/SoftwareVersion:/Address:/Credit:/Data:``,
optionally ``License:``) or a raw ``.bin`` block can be loaded from disk too.

Applying is an ordinary undoable edit of the open file (one undo step, in the
change log and version history); writing it to the car is the Flash dialog's
cluster Write, which only sends the 16-byte blocks that changed.
"""

import json
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .identify import header_rom_match, patch_checksum, patch_header

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "cluster_sweep_patches.json")


@dataclass
class SweepPatch:
    name: str
    rom_version: str
    address: int
    data: bytes
    credit: str = ""
    license: str = ""
    source: str = "library"        # "library" or the file it was loaded from
    author: str = ""
    copyright: str = ""
    url: str = ""
    license_file: str = ""
    note: str = ""

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def header_ok(self) -> bool:
        """The block's own H0 verifies and its H4/H5 name ``rom_version``."""
        d = self.data
        return (len(d) >= 6 and patch_checksum(d) == d[0]
                and header_rom_match(d[4], d[5], self.rom_version))

    @property
    def label(self) -> str:
        return "%s  [%s]" % (self.name, self.rom_version)

    @property
    def attribution(self) -> str:
        """Credit, copyright, licence and source as one block of text -- what
        is shown beside the patch and written to the change log."""
        lines = [self.credit or ("Loaded from %s" % self.source)]
        if self.copyright:
            lines.append(self.copyright if self.copyright.lower().startswith(
                "copyright") else "Copyright: %s" % self.copyright)
        lines.append("Licence: %s" % (self.license or "not stated"))
        if self.url:
            lines.append("Source: %s" % self.url)
        if self.note:
            lines.append(self.note)
        return "\n".join(lines)

    def license_text(self) -> str:
        """The full licence text this block is distributed under ('' when the
        library carries none for it)."""
        if not self.license_file:
            return ""
        path = os.path.join(os.path.dirname(_DATA),
                            os.path.basename(self.license_file))
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""


def _int(v) -> int:
    s = str(v).strip()
    return int(s, 16) if s.lower().startswith("0x") else int(s)


def load_library(path: Optional[str] = None) -> List[SweepPatch]:
    with open(path or _DATA, encoding="utf-8") as fh:
        d = json.load(fh)
    return [SweepPatch(name=p["name"], rom_version=p["rom_version"],
                       address=_int(p["address"]), data=bytes.fromhex(p["data"]),
                       credit=p.get("credit", ""), license=p.get("license", ""),
                       author=p.get("author", ""),
                       copyright=p.get("copyright", ""), url=p.get("source", ""),
                       license_file=p.get("license_file", ""),
                       note=p.get("note", ""))
            for p in d.get("patches", [])]


def parse_patch_file(text: str, source: str = "file") -> SweepPatch:
    """A KWHack ``.patch`` file (the format hayperek / Feche / gmenounos
    patches are usually published in)."""
    text = text.replace("\r", "")
    if "Data:" not in text:
        raise ValueError("not a sweep patch file (no 'Data:' section)")
    head, data = text.split("Data:", 1)
    kv = {}
    for line in head.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            kv[k.strip().lower()] = v.strip()
    missing = [k for k in ("Name", "Variant", "SoftwareVersion", "Address")
               if not kv.get(k.lower())]
    if missing:
        raise ValueError("patch file is missing: %s" % ", ".join(missing))
    try:
        blob = bytes.fromhex("".join(data.split()))
    except ValueError:
        raise ValueError("patch data is not hex")
    if len(blob) < 6:
        raise ValueError("patch data is too short for a header")
    return SweepPatch(name=kv["name"], rom_version="%s %s" % (
        kv["variant"], kv["softwareversion"]), address=_int(kv["address"]),
        data=blob, credit=kv.get("credit", ""),
        license=kv.get("license", ""), source=source)


def from_block(blob: bytes, address: int, rom_version: str,
               name: str = "", source: str = "file") -> SweepPatch:
    """A raw patch block (a ``.bin`` as gmenounos / kw1281test publish them),
    with the load address and ROM build the user supplies."""
    if len(blob) < 6:
        raise ValueError("a patch block is at least its 6-byte header")
    return SweepPatch(name=name or os.path.basename(source),
                      rom_version=rom_version, address=address,
                      data=bytes(blob), source=source)


def rom_versions_matching(blob: bytes) -> List[str]:
    """The ROM builds a block's header (H4/H5) names, among the builds the
    definitions and the unlock table know about."""
    if len(blob) < 6:
        return []
    from ..flash.vdo_cluster import _UNLOCK_BY_VERSION
    known = set(_UNLOCK_BY_VERSION) | {p.rom_version for p in load_library()}
    return sorted(v for v in known if header_rom_match(blob[4], blob[5], v))


# ------------------------------------------------------------------ checks
def cluster_rom(session) -> Optional[str]:
    ident = getattr(session, "vdo_identity", None)
    return getattr(ident, "rom_version", "") or None


def current_patch(session, library: Optional[List[SweepPatch]] = None) -> str:
    """One line describing the patch block the open EEPROM carries."""
    defn = getattr(session, "vdo_definition", None)
    pm = getattr(defn, "patch_module", None)
    if not pm:
        return "No patch-module location is known for this ROM family."
    data = bytes(session.binfile.data)
    hdr = patch_header(data, pm["address"], pm["end"])
    if hdr is None:
        return "No patch block loaded (header erased)."
    blk = data[pm["address"]:hdr.body_end]
    for p in library or ():
        if p.address == pm["address"] and p.data == blk:
            return "%s (%d bytes)" % (p.label, p.size)
    kind = "valid" if hdr.valid else "NOT loadable"
    return ("Patch block of %d bytes (%d code, %d table), header %s -- not a "
            "library sweep patch (typically the factory bug-fix patch)"
            % (hdr.body_end - pm["address"], hdr.code_len, hdr.data_len, kind))


def check(session, patch: SweepPatch,
          assume_rom: Optional[str] = None) -> Tuple[bool, List[str]]:
    """``(ok, reasons)`` -- whether ``patch`` may be applied to ``session``;
    ``reasons`` says why not (or, when ok, notes worth showing)."""
    why: List[str] = []
    if getattr(session, "platform", "") != "vdo":
        return False, ["The open file is not a VDO cluster EEPROM."]
    defn = session.vdo_definition
    pm = defn.patch_module
    if not pm:
        return False, ["No patch-module location is known for %s." % defn.family]
    if not patch.header_ok:
        why.append("The patch's own header does not verify (checksum or ROM "
                   "target) -- the block is damaged.")
    if patch.address != pm["address"]:
        why.append("The patch is for address 0x%03X; this cluster's patch module "
                   "is at 0x%03X." % (patch.address, pm["address"]))
    if patch.address + patch.size > pm["end"]:
        why.append("The patch (%d bytes) runs past the patch area (ends 0x%03X)."
                   % (patch.size, pm["end"]))
    rom = cluster_rom(session)
    if rom:
        if rom != patch.rom_version:
            why.append("This cluster is %s; the patch is for %s."
                       % (rom, patch.rom_version))
    elif assume_rom != patch.rom_version:
        why.append("This cluster's exact ROM build is not identified (no patch "
                   "header to read it from, and the file was not read from the "
                   "cluster). Read the cluster first, or confirm it is %s."
                   % patch.rom_version)
    elif patch.rom_version[:6] != defn.family and patch.rom_version[:6] not in \
            _families_of_layout(defn.layout):
        why.append("%s is not a %s-layout ROM." % (patch.rom_version, defn.layout))
    return (not why), why


def _families_of_layout(layout: str) -> List[str]:
    from . import defs as _defs
    return [f for f, d in _defs.all_definitions().items() if d.layout == layout]


def compatible(session, library: Optional[List[SweepPatch]] = None,
               assume_rom: Optional[str] = None) -> List[SweepPatch]:
    lib = library if library is not None else load_library()
    return [p for p in lib if check(session, p, assume_rom)[0]]


def _code(block: bytes) -> bytes:
    cn = block[2] | (block[3] << 8)
    return bytes(block[6:6 + cn])


def fix_routines(block: bytes) -> List[bytes]:
    """The routines in a patch block's code: each runs up to and including a
    ``JMP abs`` (0x4C lo hi) back into ROM (target >= 0x4000 -- RAM, where the
    block is loaded, is below). The ROM patch table only hooks ROM addresses
    to these, and a sweep author who keeps the factory fixes re-hooks them
    (Bodie moves the 01.10 hooks from 0xA515/0x1851D to 0xA512/0x1851C), so
    the routines -- not the table entries -- are what identifies a fix."""
    code, out, start, i = _code(block), [], 0, 0
    while i < len(code):
        if code[i] == 0x4C and i + 2 < len(code) and code[i + 2] >= 0x40:
            if i > start:                       # a bare JMP is no fix
                out.append(code[start:i + 3])
            i += 3
            start = i
        else:
            i += 1
    return out


def replaced_patch(session, patch: SweepPatch) -> Optional[Tuple[int, int]]:
    """When the open EEPROM already carries a loadable patch block that is not
    ``patch`` itself: ``(routines carried, routines in the existing block)``
    -- how many of its fix routines (:func:`fix_routines`) appear byte-for-
    byte in the new block's code. The existing block on a stock cluster is
    VDO's factory bug-fix patch: on VWK501MH 01.10 Bodie's and SigurdMyhre's
    blocks carry both of its routines, hayperek's carries neither. None when
    there is nothing loadable to replace."""
    pm = session.vdo_definition.patch_module
    data = bytes(session.binfile.data)
    hdr = patch_header(data, pm["address"], pm["end"])
    if hdr is None or not hdr.valid:
        return None
    old = data[pm["address"]:hdr.body_end]
    if old == patch.data:
        return None
    routines = fix_routines(old)
    new = _code(patch.data)
    return sum(1 for r in routines if r in new), len(routines)


# ------------------------------------------------------------------- apply
def apply(session, patch: SweepPatch, assume_rom: Optional[str] = None) -> str:
    """Write ``patch`` into the open EEPROM as one undoable edit. Raises
    ValueError with the reasons when :func:`check` refuses."""
    ok, why = check(session, patch, assume_rom)
    if not ok:
        raise ValueError(" ".join(why))
    pm = session.vdo_definition.patch_module
    with session.transaction("Needle sweep: %s" % patch.name):
        session.edit_bytes(patch.address, patch.data)
        session.log("applied sweep patch %s (%s, %d bytes) -- %s"
                    % (patch.name, patch.rom_version, patch.size,
                       patch.attribution.replace("\n", "; ")))
    # The patch header now names the build; remember it for this session.
    ident = session.vdo_identity
    if not ident.rom_version:
        ident.rom_version = patch.rom_version
        ident.rom_source = "patch header"
    left = pm["end"] - (patch.address + patch.size)
    return ("Applied %s (%d bytes at 0x%03X; %d bytes of the patch area after "
            "it are unchanged and unused). To put it in the car, write the "
            "cluster from Tools > ECU read / write... (Cluster)."
            % (patch.label, patch.size, patch.address, left))
