# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Blair Campbell
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""What the AI assistant / MCP clients get from the VDO cluster module.

Found by the base app by convention (``tools()``). Wraps the module's own
code: identification (``session_vdo.summary`` / ``identify``), the K-value
arithmetic (``speed``) and the sweep-patch library with its compatibility
check (``sweep.check``) -- a patch is only ever proposed for the exact ROM
build it was written for. VIN, immobiliser ID and SKC are never returned.
"""

from __future__ import annotations

from ..ai.describe import num
from ..ai.tools import Tool, ToolError

H = {"type": "string", "description": "Target handle (open_file / list_open)."}
_WITHHOLD = ("VIN", "Immobilizer ID", "SKC")


def _vdo(ctx, handle):
    t = ctx.workspace.get(handle)
    if getattr(t.session, "platform", "") != "vdo":
        raise ToolError("%s is not a VDO cluster EEPROM" % handle)
    return t


def cluster_info(ctx, handle):
    from . import speed, sweep
    from .session_vdo import summary
    t = _vdo(ctx, handle)
    s = t.session
    rows = [{"field": k, "value": "[withheld]" if k in _WITHHOLD else v}
            for k, v in summary(s)]
    k = speed.k_value(s)
    out = {"identity": rows, "k_value": k, "patch_block": sweep.current_patch(s, sweep.load_library()),
           "warnings": speed.warnings(s)}
    e = speed._entity(s, name=speed.K_NAME)
    if e is not None:
        out["k_value_id"] = t.index.eid(e)
    e = speed._entity(s, name=speed.SPEEDO_NAME)
    if e is not None:
        out["speedometer_map_id"] = t.index.eid(e)
    return out


def new_k_value(ctx, handle, old_tyre=None, new_tyre=None, shown=None, actual=None):
    """The arithmetic only; the change itself is an ordinary proposal on the
    K-value parameter."""
    from . import speed
    t = _vdo(ctx, handle)
    k = speed.k_value(t.session)
    if k is None:
        raise ToolError("this cluster definition has no K-value")
    try:
        if old_tyre and new_tyre:
            new = speed.k_for_tyre_change(k, old_tyre, new_tyre)
            how = "tyres %s -> %s" % (old_tyre, new_tyre)
        elif shown and actual:
            new = speed.k_from_measured(k, float(shown), float(actual))
            how = "shown %s vs actual %s" % (shown, actual)
        else:
            raise ToolError("give old_tyre + new_tyre, or shown + actual")
    except ValueError as ex:
        raise ToolError(str(ex))
    e = speed._entity(t.session, name=speed.K_NAME)
    return {"k_value": k, "new_k_value": new, "from": how,
            "k_value_id": t.index.eid(e) if e is not None else None,
            "warnings": speed.warnings(t.session),
            "next": "propose_change on k_value_id with values [[new_k_value]]"}


def sweep_patches(ctx, handle, assume_rom=None):
    from . import sweep
    t = _vdo(ctx, handle)
    out = []
    for p in sweep.load_library():
        ok, why = sweep.check(t.session, p, assume_rom)
        out.append({"name": p.name, "rom_version": p.rom_version, "size": p.size,
                    "fits": ok, "why_not": why if not ok else [],
                    "credit": p.credit, "license": p.license or "not stated"})
    return {"cluster_rom": sweep.cluster_rom(t.session),
            "current": sweep.current_patch(t.session, sweep.load_library()),
            "patches": out,
            "note": "a patch is code for ONE ROM build; only those that fit can be proposed"}


def propose_sweep_patch(ctx, handle, name, rationale="", assume_rom=None, rom_version=None):
    from ..ai import proposals as P
    from . import sweep
    t = _vdo(ctx, handle)
    lib = sweep.load_library()
    # one name can exist for several ROM builds: the one that fits is meant
    cands = [x for x in lib if x.name.lower() == str(name).lower()
             and (not rom_version or x.rom_version == rom_version)]
    if not cands:
        raise ToolError("no sweep patch %r; sweep_patches lists them" % name)
    checked = [(x, sweep.check(t.session, x, assume_rom)) for x in cands]
    fit = [x for x, (ok, _w) in checked if ok]
    if not fit:
        raise ToolError("this patch does not fit this cluster: %s"
                        % " ".join(checked[0][1][1]))
    p = fit[0]
    note = "needle sweep patch %s (%s, %d bytes)" % (p.name, p.rom_version, p.size)
    why_txt = (rationale.strip() + "\n\n" if rationale else "") + p.attribution
    rep = sweep.replaced_patch(t.session, p)
    if rep is not None:
        why_txt += ("\n\nThis replaces the patch block the cluster carries now; %d of its %d "
                    "fix routine(s) are carried over." % rep)
    prop = P.build_bytes(t, "Needle sweep: %s" % p.name, why_txt,
                         [(p.address, p.data, note)], client=ctx.client, kind="vdo-sweep")
    P.save(prop)
    return {"proposal": prop["id"], "status": "pending review in the app",
            "after_accepting": "write the cluster from Tools > ECU read / write (Cluster)"}


def tools():
    return [
        Tool("cluster_info",
             "VDO cluster: identification (layout, ROM build, lowline, vehicle family, coding, "
             "odometer), the K-value and speedometer map ids, the patch block it carries, and "
             "anything that would stop a K-value change from taking effect. VIN, immobiliser ID "
             "and SKC are withheld.", cluster_info,
             {"type": "object", "required": ["handle"], "properties": {"handle": H}},
             title="Cluster info"),
        Tool("new_k_value",
             "VDO cluster: the K-value (impulses per km; drives speedometer AND odometer) for a "
             "tyre change or for a measured error. Returns the value to propose.", new_k_value,
             {"type": "object", "required": ["handle"], "properties": {
                 "handle": H, "old_tyre": {"type": "string", "description": "e.g. 205/55R16"},
                 "new_tyre": {"type": "string"},
                 "shown": {"type": "number", "description": "Speed or distance shown"},
                 "actual": {"type": "number", "description": "...and the true value"}}},
             title="New K-value"),
        Tool("sweep_patches",
             "VDO cluster: the needle/LED sweep patch library, and which patches fit this exact "
             "ROM build (and why the others do not).", sweep_patches,
             {"type": "object", "required": ["handle"], "properties": {
                 "handle": H, "assume_rom": {"type": "string",
                                             "description": "Only when the user confirms the ROM "
                                                            "build of an unidentified cluster."}}},
             title="Sweep patches"),
        Tool("propose_sweep_patch",
             "VDO cluster: propose applying a sweep patch that fits (see sweep_patches). Filed as a "
             "proposal for review; its credit and licence travel with it.", propose_sweep_patch,
             {"type": "object", "required": ["handle", "name"], "properties": {
                 "handle": H, "name": {"type": "string"}, "rationale": {"type": "string"},
                 "rom_version": {"type": "string", "description": "When one name exists for "
                                                                 "several ROM builds."},
                 "assume_rom": {"type": "string"}}},
             read_only=False, title="Propose sweep patch"),
    ]
