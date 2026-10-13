# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""The VDO cluster K-line reader/writer, driven against the byte-level KW1281
cluster simulator (complement handshakes, block counters, unlock, seed/key,
EEPROM blocks) -- no hardware."""
import pytest

from ovtsuite.flash import kwp
from ovtsuite.flash import vdo_cluster as vc
from ovtsuite.flash.vdo_sim import SimClusterLink
from tests.test_vdo import synthetic


@pytest.fixture(autouse=True)
def _no_wire_delays(monkeypatch):
    monkeypatch.setattr(kwp, "R6", 0)
    monkeypatch.setattr(kwp, "BLOCK_LEAD", 0)
    monkeypatch.setattr(vc.time, "sleep", lambda s: None)


def _edited(img, addr, data):
    from ovtsuite.vdo import defs
    from ovtsuite.vdo.checksum_vdo import VdoChecksum
    from ovtsuite.vdo.identify import layout_of
    d = bytearray(img)
    d[addr:addr + len(data)] = data
    return VdoChecksum(defs.get(layout_of(bytes(img)))).correct(bytes(d))


def test_key_derivation_is_stable():
    seed = bytes.fromhex("005a00c3001700e80100")
    assert vc.find_key(seed).hex() == "07ef7b00dc006a"
    with pytest.raises(vc.ClusterError):
        vc.find_key(b"\x00" * 9)


def test_unlock_tables_came_through_intact():
    assert vc.unlock_codes("VWK501MH 01.10") == [bytes.fromhex("39343440")]
    assert vc.unlock_codes("VWK503MH 09.00") == [bytes.fromhex("3E353D3A")]
    assert vc.unlock_codes("VMMJ08MH 09.00") == [bytes.fromhex("3E473D48")]
    generic = vc.unlock_codes("VWK599XX 01.00")
    assert len(generic) == 244
    assert bytes.fromhex("31393446") in generic and bytes.fromhex("3334464A") in generic


def test_software_version_string():
    assert vc.software_version_string(b"VWK501MH\x10\x01") == "VWK501MH 01.10"


def test_read_whole_eeprom():
    img = synthetic("VWK501", "VWK501MH 01.10")
    sim = SimClusterLink(img, "VWK501MH 01.10")
    data, meta = vc.read_cluster(sim)
    assert data == img
    assert meta["rom_version"] == "VWK501MH 01.10"
    assert meta["rom_source"] == "cluster"
    assert sim.level == 7 and sim.ended


def test_read_without_seed_key_and_with_an_untabled_version():
    img = synthetic("VWK501")
    sim = SimClusterLink(img, "VWK501MH 01.10", require_seed_key=False)
    assert vc.read_cluster(sim)[0] == img
    sim = SimClusterLink(img, "VWK501MH 07.70")          # not in the table
    sim.unlock_code = bytes.fromhex("3E354343")          # deep in the generic list
    assert vc.read_cluster(sim)[0] == img


def test_write_is_the_whole_eeprom_without_reading_first():
    """Owner's decision (2026-10-11): connect, unlock, write every block,
    read back. Nothing is read beforehand, so no backup and no comparison
    with the cluster's own data."""
    img = synthetic("VWK501", "VWK501MH 01.10")
    new = _edited(img, 0x150, (3700).to_bytes(2, "little"))
    sim = SimClusterLink(img, "VWK501MH 01.10")
    rep = vc.write_cluster(sim, new)
    every = list(range(0, vc.EEPROM_SIZE, vc.BLOCK))
    assert bytes(sim.eeprom) == new and sim.writes == every == rep.blocks_written
    assert "whole EEPROM" in rep.describe()


def test_another_cars_data_is_written_as_is():
    """No identity comparison any more: the file replaces what the cluster holds."""
    img = synthetic("VWK501")
    other = _edited(img, 0xD2, b"WVWZZZ1JZ3W999999")
    sim = SimClusterLink(img, "VWK501MH 01.10")
    vc.write_cluster(sim, other)
    assert bytes(sim.eeprom) == other


def test_write_refuses_a_file_that_is_no_cluster_eeprom():
    sim = SimClusterLink(synthetic("VWK501"), "VWK501MH 01.10")
    with pytest.raises(vc.ClusterError, match="recognised"):
        vc.write_cluster(sim, b"\x00" * vc.EEPROM_SIZE)
    assert sim.writes == []


def test_write_failures_are_reported():
    img = synthetic("VWK501")
    new = _edited(img, 0x150, (3700).to_bytes(2, "little"))
    with pytest.raises(vc.ClusterError, match="refused"):
        vc.write_cluster(SimClusterLink(img, refuse_write_at={0x150}), new)
    with pytest.raises(vc.ClusterError, match="verify"):
        vc.write_cluster(SimClusterLink(img, corrupt_write_at={0x140}), new)


def test_wrong_size_image_refused():
    with pytest.raises(vc.ClusterError, match="2048"):
        vc.write_cluster(SimClusterLink(synthetic()), b"\xFF" * 1024)
