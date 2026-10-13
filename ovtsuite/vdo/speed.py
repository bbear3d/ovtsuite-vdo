# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Speed and distance correction for a VDO cluster EEPROM -- the arithmetic
behind the VSS dialog's cluster mode, free of Qt so the CLI and tests use it
too.

Two different things can be wrong, and they are fixed in different places:

* **The K-value** (impulses per km) drives BOTH the speedometer and the
  odometer. Change it for a different tyre size, a different gearbox sender,
  or a measured error in speed or distance.
* **The speedometer needle map** drives only the needle. Scale it when the
  odometer is right but the needle reads high/low (a gauge face swap, a
  mismatched cluster), leaving the odometer alone.

Formulas follow KWHack's cluster tools (``SpeedoCalibrationViewModel`` and
``VwVdoLayout``): K = wheel revolutions per km x sender pulses per
revolution; a measured error scales K by displayed / actual (the cluster
shows pulses / K, so a reading that is high means K is too low); the needle
correction divides each stepper position by (1 + error), or -- on a gauge
whose map has a slope break (B5 Highline) -- the speed points instead.
"""

import math
from typing import List, Optional, Tuple

from .identify import CHASSIS


def tyre_circumference_mm(spec: str) -> float:
    """'205/55R16' -> nominal rolling circumference in mm (shared with the
    EDC15 speed tools)."""
    from ..edc15.vss15 import tyre_circumference_mm as _circ
    return _circ(spec)


def default_pulses_per_rev(family_byte: Optional[int]) -> int:
    """Gearbox sender pulses per wheel revolution the cluster family implies:
    7 for Golf/Jetta (family nibble 0), 8 for everything else (KWHack
    VwVdoLayout.DefaultPulsesPerRotation)."""
    if family_byte is None:
        return 7
    return 7 if (family_byte & 0x0F) == 0x0 else 8


def k_from_tyre(spec: str, pulses_per_rev: float) -> int:
    """K-value for a tyre size and sender pulse count."""
    if pulses_per_rev <= 0:
        raise ValueError("pulses per revolution must be positive")
    revs_per_km = 1.0e6 / tyre_circumference_mm(spec)
    return int(round(revs_per_km * pulses_per_rev))


def k_for_tyre_change(k: int, old_spec: str, new_spec: str) -> int:
    """K-value after fitting ``new_spec`` tyres in place of ``old_spec``:
    a bigger tyre turns fewer times per km, so K falls in proportion."""
    return int(round(k * tyre_circumference_mm(old_spec)
                     / tyre_circumference_mm(new_spec)))


def k_from_measured(k: int, shown: float, actual: float) -> int:
    """K-value that makes a shown speed (or odometer distance) read true."""
    if shown <= 0 or actual <= 0:
        raise ValueError("both readings must be positive")
    return int(round(k * shown / actual))


def has_slope_break(values: List[float], steps: List[float],
                    tolerance: float = 0.08) -> bool:
    """Does the needle map have two distinct slopes (a B5 Highline / W8 face,
    broken around 100 km/h) rather than one straight line?

    Adapted from KWHack's DetectHighlineSlopeChange with one correction: the
    FIRST segment is left out. It runs from the needle's rest point to the
    first real calibration point and is steep on every map (1.5-3x the rest),
    so including it -- as KWHack did, with a 20% margin -- reports a break on
    all 23 distinct reference maps, and scaled the speed points of a plain
    single-slope map whose real 5%-high reference correction changed only the
    needle positions. Without it (max deviation from the median slope),
    single-slope faces measure 0-5% and the real breaks 12-13% (B5 Highline
    3B7920946D, R32 1J0920927A) or 49-77% (Euro Highline, W8) -- so the
    margin is 8%; 20% would miss the Highline/R32 breaks."""
    slopes = []
    for i in range(1, len(values) - 1):
        dv = values[i + 1] - values[i]
        if dv:
            slopes.append((steps[i + 1] - steps[i]) / dv)
    if len(slopes) < 2:
        return False
    med = sorted(slopes)[len(slopes) // 2]
    if med == 0:
        return False
    return max(abs(s - med) / abs(med) for s in slopes) > tolerance


def needle_correction(values: List[float], steps: List[float], shown: float,
                      actual: float) -> Tuple[str, List[float]]:
    """New speedometer map for a needle that shows ``shown`` at ``actual``.
    Returns ``("steps", new_steps)`` or, on a slope-break map,
    ``("values", new_values)`` -- the row to rewrite."""
    if shown <= 0 or actual <= 0:
        raise ValueError("both readings must be positive")
    factor = shown / actual
    if has_slope_break(values, steps):
        return "values", [min(65535, max(0, round(v / factor))) for v in values]
    return "steps", [min(65535, max(0, round(s / factor))) for s in steps]


def chassis_note(family_byte: Optional[int]) -> str:
    if family_byte is None:
        return ""
    ch = CHASSIS.get(family_byte & 0x0F)
    return "%s (vehicle family 0x%X)" % (ch or "unknown chassis", family_byte & 0x0F)


# -- applying to a session ----------------------------------------------------
def _entity(session, role=None, name=None):
    for e in session.entities:
        if (role and getattr(e, "role", "") == role) or (name and e.name == name):
            return e
    return None


K_NAME = "K-value (distance impulse number)"
SPEEDO_NAME = "Speedometer calibration"
CODING_NAME = "Coding: distance impulse number"
SIGNAL_NAME = "Speed / coolant temperature signal source"


def k_value(session) -> Optional[int]:
    e = _entity(session, name=K_NAME)
    return int(e.cell(0, 0)) if e is not None else None


def set_k_value(session, k: int, label: str = "K-value") -> None:
    e = _entity(session, name=K_NAME)
    if e is None:
        raise ValueError("this cluster definition has no K-value")
    if not 0 < k <= 0xFFFF:
        raise ValueError("a K-value is stored in 16 bits (1-65535); %d does "
                         "not fit" % k)
    with session.transaction(label):
        session.edit_cells(e, [(0, 0, k)])


def apply_needle_correction(session, shown: float, actual: float) -> str:
    e = _entity(session, name=SPEEDO_NAME)
    if e is None:
        raise ValueError("this cluster definition has no speedometer map")
    vals = e.values()
    which, row = needle_correction(vals[0], vals[1], shown, actual)
    r = 0 if which == "values" else 1
    with session.transaction("speedometer needle correction"):
        session.edit_cells(e, [(r, c, v) for c, v in enumerate(row)])
    return which


def warnings(session) -> List[str]:
    """Things that make a K-value change have no (or a temporary) effect."""
    out = []
    sig = _entity(session, name=SIGNAL_NAME)
    if sig is not None and int(sig.cell(0, 0)) & 0x01:
        out.append("Road speed is coded to come from CAN (ABS), so the "
                   "K-value does not set the speedometer here.")
    cod = _entity(session, name=CODING_NAME)
    if cod is not None and int(cod.cell(0, 0)) == 0:
        out.append("Coding digit 5 is 0 (impulses via CAN).")
    out.append("Re-coding the cluster (soft-coding digit 5) loads one of the "
               "ROM's K-values over this one.")
    return out
