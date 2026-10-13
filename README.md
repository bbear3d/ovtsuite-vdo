# OVT-Suite VDO Cluster module

The VDO instrument-cluster module for [OVT-Suite](https://github.com/bbear3d/ovtsuite): cluster EEPROM
definitions and checksums, the speedometer and needle-sweep tools, and the
sweep-patch library.

## Licence

This module is free software under the Mozilla Public License 2.0 (`LICENSE`,
and `ovtsuite/vdo/LICENSE.txt`, which travels in the built package).

The needle-sweep patches in `ovtsuite/data/cluster_sweep_patches.json` are
third-party work, published unchanged under their authors' own licences
(LGPL-3.0, MIT, Apache-2.0, or freely with permission); each patch names its
author, licence and source, and the licence texts are the
`ovtsuite/data/cluster_sweep_LICENSE-*.txt` files beside it. Those licences,
not the MPL, govern the patches. They run on the cluster, not in the app.

## Building

The module is laid out exactly as it sits inside the OVT-Suite source tree.
Copy this repository's files over a checkout of the base app (same paths),
then:

    python tools/build_modules.py packages --modules vdo --unsigned

That writes `dist/modules/vdo-<version>.ovtmod`. A module you build is not
signed with the official key, so the app loads it only with **Allow unsigned
modules (development)** ticked in Tools > Modules... (or `OVT_ALLOW_UNSIGNED=1`).

Run its tests from the combined tree:

    python -m pytest tests/test_vdo.py tests/test_vdo_sweep.py tests/test_vdo_flash.py -q

## Trademarks and legal use

VDO and Continental, Volkswagen and Audi are trademarks of their owners; this
project is not affiliated with or endorsed by them. Editing a cluster's EEPROM
can make it unusable and can change the odometer; altering a vehicle's recorded
mileage is illegal in most countries. See `LEGAL.md` in the base app.
