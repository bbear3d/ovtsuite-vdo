# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""VDO cluster definition files: ``ovtsuite/data/vdo_<family>.json``.

A definition is plain JSON, one file per ROM family, readable and editable
without code. Shape (see ``vdo_vwk501.json`` for a full one)::

    {
      "format": "ovt-vdo-definition", "version": 1,
      "family": "VWK501", "layout": "VWK501", "eeprom_size": 2048,
      "status": "verified" | "extrapolated",
      "rom_versions": ["VWK501MH 01.10", ...],
      "vehicle_family_address": "0x1F7",
      "checksums": [{"name", "address", "sum_to", "regions": [[addr, len]]}],
      "patch_module": {"address": "0x4F4", "end": "0x7E0"} | null,
      "parameters": [ {parameter}, ... ]
    }

A family that shares another's layout says so instead of repeating it::

    {"family": "VMMJ08", "inherits": "VWK503",
     "overrides": {"<parameter name>": {"address": "0x45C"}},
     "default_confidence": "extrapolated", "confirmed": ["VIN", ...]}

Parameter keys: ``name`` (the identity -- the SAME string in every family,
which is what cross-version patching resolves by), ``group``
(gauges | coding | identity | firmware), ``heading``, ``kind``
(value | table | enum | flag | text | hex), ``address``, and as the kind
needs: ``bits``, ``rows``/``cols``, ``length`` (text/hex bytes per row),
``equation``, ``units``, ``min``/``max``, ``mask``, ``options`` (raw value ->
label, hex-string keys), ``options_by_chassis``, ``row_labels``/``col_labels``,
``copies``/``copy_stride`` (redundant copies an edit writes too),
``editable``, ``not_on_lowline``, ``role``, ``description``, ``source``.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data")
PREFIX = "vdo_"

GROUPS = ("gauges", "coding", "identity", "firmware")
KINDS = ("value", "table", "enum", "flag", "text", "hex")


def _int(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    return int(s, 16) if s.lower().startswith("0x") else int(s)


@dataclass
class Param:
    name: str
    group: str
    kind: str
    address: int
    heading: str = ""
    bits: int = 8
    rows: int = 1
    cols: int = 1
    equation: str = "X"
    units: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    mask: int = 0
    options: Dict[int, str] = field(default_factory=dict)
    options_by_chassis: Dict[str, Dict[int, str]] = field(default_factory=dict)
    row_labels: List[str] = field(default_factory=list)
    col_labels: List[str] = field(default_factory=list)
    copies: int = 0
    copy_stride: int = 0
    editable: bool = True
    not_on_lowline: bool = False
    checksummed: bool = False
    role: str = ""
    description: str = ""
    source: str = ""
    confidence: str = "verified"

    @property
    def size(self) -> int:
        return self.rows * self.cols * (self.bits // 8)

    @property
    def end(self) -> int:
        return self.address + self.size

    def options_for(self, chassis: Optional[str]) -> Dict[int, str]:
        if chassis and chassis in self.options_by_chassis:
            return self.options_by_chassis[chassis]
        return self.options


def _options(obj) -> Dict[int, str]:
    return {_int(k): str(v) for k, v in (obj or {}).items()}


def param_from_json(d: dict, confidence: str = "verified") -> Param:
    kind = d["kind"]
    if kind not in KINDS:
        raise ValueError("%s: unknown kind %r" % (d.get("name"), kind))
    group = d.get("group", "coding")
    if group not in GROUPS:
        raise ValueError("%s: unknown group %r" % (d.get("name"), group))
    bits = int(d.get("bits", 8))
    rows = int(d.get("rows", 1))
    cols = int(d.get("cols", 1))
    if kind in ("text", "hex"):
        bits = 8
        if "length" in d:
            cols = int(d["length"])
    if kind in ("flag",):
        bits = 8
    p = Param(
        name=d["name"], group=group, kind=kind, address=_int(d["address"]),
        heading=d.get("heading", ""), bits=bits, rows=rows, cols=cols,
        equation=d.get("equation", "X"), units=d.get("units", ""),
        min=d.get("min"), max=d.get("max"), mask=_int(d.get("mask")) or 0,
        options=_options(d.get("options")),
        options_by_chassis={ch: _options(v) for ch, v in
                            (d.get("options_by_chassis") or {}).items()},
        row_labels=list(d.get("row_labels") or []),
        col_labels=list(d.get("col_labels") or []),
        copies=int(d.get("copies", 0)), copy_stride=int(d.get("copy_stride", 0)),
        editable=bool(d.get("editable", True)),
        not_on_lowline=bool(d.get("not_on_lowline", False)),
        checksummed=bool(d.get("checksummed", False)),
        role=d.get("role", ""), description=d.get("description", ""),
        source=d.get("source", ""),
        confidence=d.get("confidence", confidence))
    if p.kind == "flag" and not p.mask:
        raise ValueError("%s: a flag needs a mask" % p.name)
    if p.bits not in (8, 16):
        raise ValueError("%s: %d-bit cells are not supported" % (p.name, p.bits))
    return p


@dataclass
class Definition:
    family: str
    title: str
    layout: str
    eeprom_size: int
    status: str
    rom_versions: List[str]
    vehicle_family_address: Optional[int]
    checksums: List[dict]
    patch_module: Optional[dict]
    params: List[Param]
    notes: str = ""
    path: str = ""

    def param(self, name: str) -> Optional[Param]:
        return next((p for p in self.params if p.name == name), None)


def _raw(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    if d.get("format") != "ovt-vdo-definition":
        raise ValueError("%s is not an OVT VDO definition" % path)
    if int(d.get("version", 0)) != 1:
        raise ValueError("%s: unsupported definition version %r"
                         % (path, d.get("version")))
    return d


def _resolve(fam: str, raws: Dict[str, dict], seen=()) -> dict:
    d = raws[fam]
    parent = d.get("inherits")
    if not parent:
        return d
    if parent in seen or parent not in raws:
        raise ValueError("%s: bad inherits %r" % (fam, parent))
    base = dict(_resolve(parent, raws, seen + (fam,)))
    over = d.get("overrides") or {}
    params = []
    for p in base.get("parameters", []):
        q = dict(p)
        q.update(over.get(p["name"], {}))
        params.append(q)
    unknown = set(over) - {p["name"] for p in params}
    if unknown:
        raise ValueError("%s: overrides name unknown parameters: %s"
                         % (fam, ", ".join(sorted(unknown))))
    merged = dict(base)
    for k, v in d.items():
        if k in ("inherits", "overrides", "parameters"):
            continue
        merged[k] = v
    merged["parameters"] = params + list(d.get("parameters", []))
    return merged


def _build(d: dict, path: str) -> Definition:
    conf_default = d.get("default_confidence", "verified")
    confirmed = set(d.get("confirmed") or [])
    params = []
    for pj in d.get("parameters", []):
        conf = "verified" if pj["name"] in confirmed else conf_default
        params.append(param_from_json(pj, conf))
    names = [p.name for p in params]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise ValueError("%s: duplicate parameter names: %s"
                         % (d.get("family"), ", ".join(sorted(dup))))
    size = int(d.get("eeprom_size", 2048))
    for p in params:
        last = p.end + p.copies * p.copy_stride
        if p.address < 0 or last > size:
            raise ValueError("%s: %s runs past the EEPROM" % (d["family"], p.name))
    pm = d.get("patch_module")
    if pm:
        pm = {"address": _int(pm["address"]), "end": _int(pm.get("end", 0x7E0)),
              "description": pm.get("description", "")}
    checks = []
    for c in d.get("checksums", []):
        checks.append({"name": c["name"], "address": _int(c["address"]),
                       "sum_to": _int(c.get("sum_to", 0xFF)),
                       "regions": [(_int(a), int(n)) for a, n in c["regions"]],
                       "description": c.get("description", "")})
    return Definition(
        family=d["family"], title=d.get("title", d["family"]),
        layout=d.get("layout", d["family"]), eeprom_size=size,
        status=d.get("status", "verified"),
        rom_versions=list(d.get("rom_versions") or []),
        vehicle_family_address=_int(d.get("vehicle_family_address")),
        checksums=checks, patch_module=pm, params=params,
        notes=d.get("notes", ""), path=path)


_CACHE: Optional[Dict[str, Definition]] = None


def definition_paths(directory: Optional[str] = None) -> List[str]:
    directory = directory or _DATA
    return sorted(os.path.join(directory, f) for f in os.listdir(directory)
                  if f.startswith(PREFIX) and f.endswith(".json"))


def load_all(directory: Optional[str] = None) -> Dict[str, Definition]:
    raws, paths = {}, {}
    for path in definition_paths(directory):
        d = _raw(path)
        raws[d["family"]] = d
        paths[d["family"]] = path
    return {fam: _build(_resolve(fam, raws), paths[fam]) for fam in raws}


def all_definitions() -> Dict[str, Definition]:
    """Every shipped definition, by family (cached)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = load_all()
    return _CACHE


def get(family: str) -> Definition:
    try:
        return all_definitions()[family]
    except KeyError:
        raise ValueError("no VDO definition for %r (have: %s)"
                         % (family, ", ".join(sorted(all_definitions()))))
