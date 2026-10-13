# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Needle / LED sweep patches for VDO clusters: the bundled library (every
block verifies, and carries its author's own licence), the ROM-exact checks,
loading from files, and applying as one undoable edit."""
import os

import pytest

from ovtsuite.vdo import identify as I
from ovtsuite.vdo import sweep as SW
from tests.test_vdo import session_of, synthetic

# The licence each author publishes under (checked against their pages).
AUTHOR_LICENCE = {
    "Feche": "LGPL-3.0-or-later",
    "hayperek": "LGPL-3.0",
    "gmenounos (Greg Menounos)": "MIT",
    "SigurdMyhre": "Apache-2.0",
    "Bodie (Bodie Royle)": "None stated",
}

# VDO's factory bug-fix block on VWK501MH 01.10 (two fix routines).
FACTORY_0110 = bytes.fromhex(
    "af9a1a0010a42907c9059002a9040a4c18a5a40285020a0a650284024c248500"
    "00a5154c00a5167c00a5170e01851d4c01851e8801851f0e007f")


@pytest.fixture(scope="module")
def library():
    return SW.load_library()


def _one(library, rom, author):
    return next(p for p in library if p.rom_version == rom and p.author == author)


def test_every_bundled_block_verifies_and_names_its_build(library):
    assert len(library) >= 15
    for p in library:
        assert p.header_ok, p.label
        assert p.address in (0x4F4, 0x4F6, 0x552), p.label
        assert p.address + p.size <= 0x7E0, p.label


def test_every_bundled_block_carries_its_authors_own_licence(library):
    for p in library:
        assert AUTHOR_LICENCE[p.author] == p.license, p.label
        assert p.credit and p.copyright and p.url.startswith("https://"), p.label
        text = p.license_text()
        if p.license.startswith("LGPL"):
            assert "GNU LESSER GENERAL PUBLIC LICENSE" in text
        elif p.license == "MIT":
            assert "Copyright (c) 2025 Greg Menounos" in text
        elif p.license == "Apache-2.0":
            assert "Apache License" in text and "Version 2.0" in text
        else:                                   # Bodie: permission, credited
            assert text == "" and "Bodie" in p.credit
        assert ("Licence: %s" % p.license) in p.attribution
    assert {p.rom_version for p in library if p.author.startswith("Bodie")} \
        == {"VWK501MH 00.92", "VWK501MH 01.00", "VWK501MH 01.10",
            "VWK503MH 09.00"}


def test_offered_only_for_the_exact_rom_build(tmp_path, library):
    s = session_of(tmp_path, synthetic("VWK501", "VWK501MH 01.10"))
    fit = SW.compatible(s, library)
    assert {p.rom_version for p in fit} == {"VWK501MH 01.10"}
    assert {p.author for p in fit} == {"hayperek", "Bodie (Bodie Royle)"}
    ok, why = SW.check(s, _one(library, "VWK501MH 01.00", "SigurdMyhre"))
    assert not ok and "VWK501MH 01.10" in why[0]


def test_another_layout_is_refused(tmp_path, library):
    s = session_of(tmp_path, synthetic("VWK503", "VWK503MH 09.00"))
    assert {p.rom_version for p in SW.compatible(s, library)} == {
        "VWK503MH 09.00"}
    ok, why = SW.check(s, _one(library, "VWK501MH 01.10", "hayperek"))
    assert not ok and any("0x4F4" in w for w in why)


def test_unidentified_rom_needs_confirmation(tmp_path, library):
    s = session_of(tmp_path, synthetic("VWK501"))          # no patch header
    assert SW.cluster_rom(s) is None
    assert SW.compatible(s, library) == []
    dsg = _one(library, "VWK501MH 01.00", "SigurdMyhre")
    ok, why = SW.check(s, dsg)
    assert not ok and "not identified" in why[0]
    assert SW.check(s, dsg, assume_rom="VWK501MH 01.00")[0]
    # confirming a build of the other layout does not help
    assert not SW.check(s, _one(library, "VWK503MH 09.00", "hayperek"),
                        assume_rom="VWK503MH 09.00")[0]
    SW.apply(s, dsg, assume_rom="VWK501MH 01.00")
    assert s.vdo_identity.rom_version == "VWK501MH 01.00"
    assert s.vdo_identity.rom_source == "patch header"


def test_apply_is_one_undoable_edit_with_attribution(tmp_path, library):
    img = synthetic("VWK501", "VWK501MH 01.10")
    s = session_of(tmp_path, img)
    p = _one(library, "VWK501MH 01.10", "hayperek")
    assert SW.replaced_patch(s, p) == (0, 0)      # a block with no routines
    msg = SW.apply(s, p)
    assert "ECU read / write" in msg
    data = bytes(s.binfile.data)
    assert data[0x4F4:0x4F4 + p.size] == p.data
    hdr = I.patch_header(data, 0x4F4)
    assert hdr.valid and hdr.body_end == 0x4F4 + p.size
    assert "LGPL-3.0" in s.change_log[-1] and "hayperek" in s.change_log[-1]
    assert SW.replaced_patch(s, p) is None
    assert p.label in SW.current_patch(s, library)
    s.undo()
    assert bytes(s.binfile.data) == img


def test_damaged_block_is_refused(tmp_path, library):
    s = session_of(tmp_path, synthetic("VWK501", "VWK501MH 01.10"))
    p = _one(library, "VWK501MH 01.10", "hayperek")
    bad = SW.SweepPatch(p.name, p.rom_version, p.address,
                        p.data[:40] + bytes([p.data[40] ^ 1]) + p.data[41:])
    ok, why = SW.check(s, bad)
    assert not ok and "damaged" in why[0]
    with pytest.raises(ValueError):
        SW.apply(s, bad)


def test_kwhack_patch_file_and_raw_block(library):
    p = _one(library, "VWK501MH 01.00", "SigurdMyhre")
    text = ("Name: DSG\r\nVariant: VWK501MH\r\nSoftwareVersion: 01.00\r\n"
            "Address: 0x4F4\r\nCredit: someone\r\nLicense: Apache-2.0\r\n"
            "Data:\r\n" + " ".join("%02X" % b for b in p.data) + "\r\n")
    q = SW.parse_patch_file(text, source="dsg.patch")
    assert (q.rom_version, q.address, q.data, q.license) == (
        "VWK501MH 01.00", 0x4F4, p.data, "Apache-2.0")
    assert q.header_ok and q.source == "dsg.patch"
    with pytest.raises(ValueError, match="Address"):
        SW.parse_patch_file("Name: x\nVariant: y\nSoftwareVersion: 1\nData: 00")
    with pytest.raises(ValueError):
        SW.parse_patch_file("not a patch")
    assert SW.rom_versions_matching(p.data) == ["VWK501MH 01.00"]
    b = SW.from_block(p.data, 0x4F4, "VWK501MH 01.00", source="x.bin")
    assert b.header_ok and b.name == "x.bin" and b.license == ""
    assert "not stated" in b.attribution


def _factory(tmp_path):
    img = bytearray(synthetic("VWK501", "VWK501MH 01.10"))
    img[0x4F4:0x4F4 + len(FACTORY_0110)] = FACTORY_0110
    return session_of(tmp_path, bytes(img))


def test_factory_fix_routines_carried_or_dropped(tmp_path, library):
    s = _factory(tmp_path)
    assert s.vdo_identity.rom_version == "VWK501MH 01.10"
    assert [r.hex() for r in SW.fix_routines(FACTORY_0110)] == [
        "2907c9059002a9040a4c18a5", "a40285020a0a650284024c2485"]
    # Bodie re-hooks the factory fixes and carries both routines ...
    assert SW.replaced_patch(s, _one(library, "VWK501MH 01.10",
                                     "Bodie (Bodie Royle)")) == (2, 2)
    # ... hayperek's LED sweep drops them.
    assert SW.replaced_patch(s, _one(library, "VWK501MH 01.10",
                                     "hayperek")) == (0, 2)
