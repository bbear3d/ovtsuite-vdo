# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""VDO Mk4 cluster EEPROM platform: definitions, identification, session,
checksums, the .vdo container, cross-version patching and speed tools.

Synthetic EEPROMs cover the always-run cases; the real-sample tests use the
KWHack cluster corpus copied to Reference/VDO and skip when it is absent.
"""
import os

import pytest

from ovtsuite import container as C
from ovtsuite import patch as P
from ovtsuite.session import TunerSession
from ovtsuite.vdo import defs, detect, identify as I, speed as VS
from ovtsuite.vdo.checksum_vdo import VdoChecksum

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VDO = os.path.join(ROOT, "Reference", "VDO")
SAMPLES = os.path.join(VDO, "Samples")
CONVERTED = os.path.join(VDO, "Converted")


def _need(*parts):
    p = os.path.join(VDO, *parts)
    if not os.path.exists(p):
        pytest.skip("%s not present" % os.path.basename(p))
    return p


def synthetic(layout="VWK501", rom=None):
    """A minimal valid EEPROM of ``layout``: immobilizer ID in place, gauge
    checksum correct, optionally a patch block naming ``rom``."""
    a = I.LAYOUTS[layout]
    d = bytearray(b"\xFF" * 2048)
    off = 0 if layout == "VWK501" else 0x3E
    d[a["immo_id"]:a["immo_id"] + 42] = b"VWZ7Z0B6127535" * 3
    d[0xD2 + off:0xD2 + off + 17] = b"WVWZZZ1JZ3W000001"
    d[0x150 + 0x42 * (off != 0):0x152 + 0x42 * (off != 0)] = (3648).to_bytes(2, "little")
    d[0x144 + 0x42 * (off != 0)] = 0x15
    if rom:
        rb = I.rom_bytes(rom)
        h5 = ((sum(rb[:8]) + rb[9]) & 0xFF) | 0x80
        body = bytes(range(12)) + bytes(14)          # 12 code + 14 table bytes
        blk = bytearray([0, 14, 12, 0, rb[8], h5]) + body
        blk[0] = I.patch_checksum(bytes(blk))
        p = a["patch"]
        d[p:p + len(blk)] = blk
    fam = layout
    return VdoChecksum(defs.get(fam)).correct(bytes(d))


def session_of(tmp_path, data, name="c.bin"):
    path = tmp_path / name
    path.write_bytes(data)
    return TunerSession(str(path))


# ---------------------------------------------------------------- definitions
def test_definitions_load_and_share_parameter_names():
    ds = defs.all_definitions()
    assert {"VWK501", "VWK503", "VMMJ08", "VQMJ07", "K5MJ07"} <= set(ds)
    assert ds["VMMJ08"].layout == ds["VQMJ07"].layout == "VWK503"
    n501 = {p.name for p in ds["VWK501"].params}
    n503 = {p.name for p in ds["VWK503"].params}
    # the identity a cross-version patch resolves by: shared names
    assert len(n501 & n503) >= 37
    assert n501 - n503 == set()
    assert n503 - n501 == {"Ice warning", "Outside temperature source"}
    # no artificial range on the K-value (KWHack's 50..10000 was a bug)
    k = ds["VWK501"].param("K-value (distance impulse number)")
    assert k.min is None and k.max is None


def test_extrapolated_families_mark_unconfirmed_parameters():
    d = defs.get("VQMJ07")
    assert d.status == "extrapolated"
    assert d.param("VIN").confidence == "verified"
    assert d.param("K-value (distance impulse number)").confidence == "extrapolated"
    assert d.param("Cluster ID for radio").address == 0x45C
    assert defs.get("K5MJ07").param("Cluster ID for radio").address == 0x50A
    assert d.patch_module is None


# ------------------------------------------------------------- identification
def test_layout_detection_and_refusals():
    assert I.layout_of(synthetic("VWK501")) == "VWK501"
    assert I.layout_of(synthetic("VWK503")) == "VWK503"
    assert not detect(b"\xFF" * 2048)               # no anchors
    assert not detect(synthetic()[:1024])            # wrong size
    assert not detect(bytes(0x80000))                # an ECU image


def test_broken_checksum_still_identified_by_the_immobilizer_field():
    d = bytearray(synthetic("VWK501"))
    d[0x150] ^= 0x55
    assert I.layout_of(bytes(d)) == "VWK501"


def test_rom_version_from_the_patch_header():
    for lay, rom in (("VWK501", "VWK501MH 01.10"), ("VWK501", "VWK501LL 01.00"),
                     ("VWK503", "VWK503MH 09.00"), ("VWK503", "VMMJ08MH 09.00")):
        ident = I.identify(synthetic(lay, rom))
        assert (ident.rom_version, ident.rom_source) == (rom, "patch header")
        assert ident.family == rom[:6]
        assert ident.lowline is rom.endswith("LL 01.00")


def test_the_clusters_own_version_wins_over_the_header():
    ident = I.identify(synthetic("VWK503", "VWK503MH 09.00"),
                       {"rom_version": "VMMJ08MH 09.00", "rom_source": "cluster"})
    assert (ident.family, ident.rom_source) == ("VMMJ08", "cluster")
    # a version a save only derived from the header is re-derived, not trusted
    ident = I.identify(synthetic("VWK503", "VWK503MH 09.00"),
                       {"rom_version": "VMMJ08MH 09.00", "rom_source": "patch header"})
    assert ident.family == "VWK503"


# -------------------------------------------------------------------- session
def test_session_reads_little_endian_and_edits_bits_and_copies(tmp_path):
    s = session_of(tmp_path, synthetic("VWK501", "VWK501MH 01.10"))
    assert s.platform == "vdo" and s.family == "VWK501"
    E = {e.name: e for e in s.entities}
    assert E["K-value (distance impulse number)"].cell(0, 0) == 3648
    seat = E["Coding: seatbelt warning"]
    assert seat.cell(0, 0) == 0
    s.edit_cells(seat, [(0, 0, 1)])
    assert s.binfile.data[0x144] == 0x17             # only bit 0x02 changed
    s.undo_stack.undo(s.binfile)
    assert s.binfile.data[0x144] == 0x15
    s.edit_cells(E["SKC (login code)"], [(0, 0, 12345)])
    assert bytes(s.binfile.data[0xCC:0xD2]) == (12345).to_bytes(2, "little") * 3
    assert E["Odometer"].read_only and not E["Coding: country"].read_only
    assert E["Coding: country"].options[4] == "England"
    assert "Firmware patch module (VWK501MH 01.10)" in E


def test_checksums_verify_and_correct(tmp_path):
    s = session_of(tmp_path, synthetic("VWK501", "VWK501MH 01.10"))
    assert s.checksum_status().ok
    E = {e.name: e for e in s.entities}
    s.edit_cells(E["K-value (distance impulse number)"], [(0, 0, 4100)])
    rep = s.checksum_status()
    assert not rep.ok
    assert any(sl.name.startswith("Patch module") and sl.ok for sl in rep.slots)
    s.correct_checksums()
    assert s.checksum_status().ok


def test_vdo_container_round_trip(tmp_path):
    s = session_of(tmp_path, synthetic("VWK503", "VWK503MH 09.00"))
    out = str(tmp_path / "c.vdo")
    s.save(out)
    raw = open(out, "rb").read()
    assert C.is_container(raw, "vdo")
    c = C.Container.from_bytes(raw)
    assert c.external() == bytes(s.binfile.data)
    assert c.meta()["rom_version"] == "VWK503MH 09.00"
    assert c.meta()["rom_source"] == "patch header"
    s2 = TunerSession(out)
    assert s2.platform == "vdo" and bytes(s2.binfile.data) == bytes(s.binfile.data)


def test_cluster_read_container_keeps_the_reported_version(tmp_path):
    from ovtsuite.vdo.container_vdo import container_bytes
    blob = container_bytes(synthetic("VWK503"), {"rom_version": "VMMJ08MH 09.00",
                                                 "rom_source": "cluster",
                                                 "ident": "1J5920826L KOMBI"})
    p = tmp_path / "r.vdo"
    p.write_bytes(blob)
    s = TunerSession(str(p))
    assert s.family == "VMMJ08"
    assert s.vdo_identity.rom_source == "cluster"


# ----------------------------------------------------------- cross-version patch
def test_cross_version_patch_resolves_by_name(tmp_path):
    src = session_of(tmp_path, synthetic("VWK503", "VWK503MH 09.00"), "a.bin")
    tgt = session_of(tmp_path, synthetic("VWK501", "VWK501MH 01.10"), "b.bin")
    E = {e.name: e for e in src.entities}
    src.edit_cells(E["K-value (distance impulse number)"], [(0, 0, 4202)])
    src.edit_cells(E["Coding: seatbelt warning"], [(0, 0, 1)])
    entries = [e for e in P.diff_entities(tgt, src)
               if not e.name.startswith("Firmware")]
    names = {e.name for e in entries}
    assert {"K-value (distance impulse number)", "Coding: seatbelt warning"} <= names
    res = P.apply_patch(P.new_patch(tgt, src, entries), tgt,
                        default_disposition=P.APPLY)
    assert not res.skipped
    T = {e.name: e for e in tgt.entities}
    assert T["K-value (distance impulse number)"].cell(0, 0) == 4202
    assert tgt.binfile.data[0x150:0x152] == (4202).to_bytes(2, "little")
    assert tgt.binfile.data[0x144] == 0x17
    assert tgt.checksum_status().ok                    # corrected by the apply


def test_firmware_patch_never_crosses_rom_versions(tmp_path):
    src = session_of(tmp_path, synthetic("VWK501", "VWK501MH 01.10"), "a.bin")
    tgt = session_of(tmp_path, synthetic("VWK501", "VWK501LL 01.00"), "b.bin")
    pm = [e for e in src.entities if e.name.startswith("Firmware")][0]
    entry = P._candidate(pm, pm)
    if entry is None:                                   # identical -> force one
        entry = P.PatchEntry(name=pm.name, kind=pm.kind, rows=pm.rows,
                             cols=pm.cols, values=pm.values())
    res = P.apply_patch(P.new_patch(tgt, src, [entry]), tgt,
                        default_disposition=P.APPLY)
    assert res.skipped and "not identified" in res.skipped[0][1]


def test_real_vehicle_data_transfer_matches_the_reference():
    """VMMJ08 -> VWK501 (different layouts): the identity group, applied by
    name, reproduces KWHack's reference transfer except the stale 4th key
    KWHack left behind and the radio ID this older reference did not copy."""
    base = os.path.join(CONVERTED, "VMMJ08 to VWK501")
    _need("Converted", "VMMJ08 to VWK501")
    tgt = TunerSession(os.path.join(base, "VWK501-FIS-Diesel-B5-RDW-Base.bin"))
    src = TunerSession(os.path.join(base, "VMMJ08-MFA-Petrol-A4-RDW-City.bin"))
    from ovtsuite.vdo.session_vdo import GROUP_TIER
    ents = [e for e in P.diff_entities(tgt, src) if e.tier == GROUP_TIER["identity"]]
    P.apply_patch(P.new_patch(tgt, src, ents), tgt, default_disposition=P.APPLY)
    want = open(os.path.join(
        base, "Vehicle-data-copied-from-VMMJ08-VWK501-FIS-Diesel-B5-RDW-Base.bin"),
        "rb").read()
    got = bytes(tgt.binfile.data)
    allowed = set(range(0x2C, 0x30)) | set(range(0x4C, 0x50)) | {0x398, 0x399} \
        | set(range(0x10C, 0x11C))
    assert {i for i in range(2048) if got[i] != want[i]} <= allowed


def test_every_real_sample_identifies():
    _need("Samples")
    for fn in sorted(os.listdir(SAMPLES)):
        d = open(os.path.join(SAMPLES, fn), "rb").read()
        ident = I.identify(d)
        assert ident is not None, fn
        assert ident.layout == ("VWK501" if fn.startswith("VWK501") else "VWK503"), fn
        assert I.checksum_ok(d, ident.layout), fn


# ---------------------------------------------------------------------- speed
def test_k_value_formulas():
    assert VS.k_from_tyre("195/65R15", 7) == 3512
    assert VS.k_for_tyre_change(4000, "195/65R15", "195/65R15") == 4000
    assert VS.k_from_measured(4000, 105, 100) == 4200
    assert VS.default_pulses_per_rev(0x00) == 7
    assert VS.default_pulses_per_rev(0x0A) == 8


def test_k_value_has_no_artificial_limit(tmp_path):
    s = session_of(tmp_path, synthetic())
    VS.set_k_value(s, 12000)
    assert VS.k_value(s) == 12000
    with pytest.raises(ValueError):
        VS.set_k_value(s, 70000)                        # does not fit 16 bits


def test_needle_correction_matches_the_real_5_percent_reference():
    src = _need("Samples", "VMMJ08-MFA-Petrol-A4-RDW-City.bin")
    ref = _need("Converted", "Speedo-Calibrated-for-speedo-that-reads-5-percent-"
                "high-VMMJ08-MFA-Petrol-A4-RDW-City.bin")
    s = TunerSession(src)
    assert VS.apply_needle_correction(s, 105, 100) == "steps"
    s.correct_checksums()
    assert bytes(s.binfile.data) == open(ref, "rb").read()


def test_slope_break_ignores_the_park_segment():
    # single slope after a steep park segment: no break
    assert not VS.has_slope_break([24, 73, 909, 1841, 2773],
                                  [15, 111, 937, 1858, 2778])
    # B5 Highline face: two slopes
    assert VS.has_slope_break([24, 99, 474, 1474, 3099, 3752, 4296, 4404],
                              [23, 134, 466, 1353, 2793, 3458, 4012, 4123])
