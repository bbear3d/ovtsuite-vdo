---
title: The cluster EEPROM
order: 10
---
# The cluster EEPROM

A cluster EEPROM opens like any other binary: its fields are in the parameter
tree on the left, grouped by what they are for, and picking one shows it as
a table on the right. This page lists the groups, says which fields you can
edit and which you should leave alone, and explains the checksums and how a
cluster is kept in a project.

## Editing a field

1. Pick the field in the tree. The tree and the table heading show its name
   as used on this page (for example **Coding: country**); the tree's
   description column, and the lines under the table heading, say what it
   does, the values it can take, and where it sits in the EEPROM.
   **Filter parameters...** above the tree finds a field by its name or its
   description.
2. Double-click a cell to change it:
   - **A coding option** (a field whose values have names) opens a drop-down
     list of its choices, shown as *name (raw value)*. You can also type the
     name or the number.
   - **A text field** (VIN, part number) takes characters: type the text in
     the first cell and it fills the cells after it.
   - **A hex field** takes one byte per cell, for example `6C` or `0x6C`.
   - **A number** takes a value in the units shown.
3. Save (**File > Save**, Ctrl+S). The checksums are corrected as the
   version is saved; see [Checksums](#checksums).

Every edit is undoable (Ctrl+Z), like any other edit (see
[Editing and saving](../../editing.md)).

Some details the EEPROM imposes, handled for you:

- **Bit fields.** Several coding options share one byte (for example the four
  switches in soft-coding digits 1–2). An edit changes only that option's
  bits; the other bits in the byte are left as they are.
- **Copies.** Fields the cluster stores more than once — the SKC three times,
  the immobiliser key three times — are written to every copy by one edit.
  The description lists the other addresses.
- **16-bit values** (the K-value, the needle maps) are stored low byte first.

## What is in each group

### Gauges & speedometer

| Field | What it is | Safe to edit? |
|---|---|---|
| K-value (distance impulse number) | Impulses per km the cluster counts for speed **and** distance. Used only when coding digit 5 does not override it. | Yes — best done with [Speed and distance](speed.md). |
| Speedometer calibration | Needle map: row 1 is the speed at each point, row 2 the stepper-motor position for it. | Yes — best done with [Speed and distance](speed.md). |
| Fuel consumption correction | Trip computer fuel consumption trim, in %. | Yes. |
| Tachometer calibration | Tachometer needle map (differs between diesel and petrol faces). | Only when matching a different gauge face. |
| Fuel gauge calibration, Fuel level sender calibration | Fuel needle map, and the tank sender's linearisation. | Only when fitting a different tank or sender. |
| Coolant temperature gauge calibration | Coolant needle map. The flat middle section is the deliberate "needle parks at 90" band. | Only if you know why. |

The K-value and the speedometer map are covered by the gauge checksum. If
that checksum is wrong the cluster shows **dEF** instead of working; the app
corrects it on save.

### Cluster coding & options

| Field | What it is |
|---|---|
| Coding: distance impulse number | Soft-coding digit 5. Picks one of the K-values burned into the ROM (which table depends on the vehicle family); 0 takes the impulses from CAN. |
| Coding: service intervals | Soft-coding digit 4: fixed or flexible (LongLife) service intervals, with or without an oil level/temperature sensor, or no service display. |
| Coding: country | Soft-coding digit 3: country / units variant. |
| Coding: brake pad wear warning, seatbelt warning, washer fluid level warning, secondary display (radio/navigation) | Soft-coding digits 1–2, one bit each (On / Off). |
| Vehicle family | Which chassis the cluster is set up for. It selects the K-value table coding digit 5 uses and the default sender pulses per wheel turn. Changing it re-skins the cluster for another chassis — normally only done when building a cluster for a different car. |
| ABS / lamp-check configuration | Byte that drives ABS lamp and bulb-check behaviour. The listed values are the typical ones per chassis, not the only valid ones; individual bits are not confirmed. |
| Speed / coolant temperature signal source | Whether road speed and coolant temperature come from the hard-wired senders or from CAN (ABS / engine ECU). Needed for some engine swaps. |
| Outside air temperature sensor, Chime above 120 km/h | Option switches (On / Off). |
| Outside temperature source, Ice warning | VWK503-layout clusters only, not on lowline. |
| LED configuration (lights off), LED on while starting, Cruise control lamp when set | Lighting options. |
| Ice warning enable / disable temperature | Outside temperatures, in °C, at which the ice warning shows and clears. Not on lowline. |
| Distance to empty, Welcome message | Whole-byte switches: stock or enabled. Not on lowline. |
| Part number / ident | The 18-character ident string scan tools read, for example `1J0920806M  A4V07`. It describes the cluster hardware. Editable, but leave it unless you have a reason. |
| Hardware level tag | `HL`, `ML` or `LL` (high / mid / lowline). Informational, read-only. |

These are the settings soft coding normally changes. Note that re-coding the
cluster with a scan tool (digit 5 in particular) loads one of the ROM's
K-values over the one in the EEPROM.

### Identity & immobilizer

This group is what makes the cluster belong to one car. Most of it is
**read-only in the table** — you cannot type over it — because hand-editing
it breaks the immobiliser or the odometer. It changes only when a whole
cluster's data is written across (see [Moving data between
clusters](#moving-data-between-clusters)).

| Field | What it is | Editable |
|---|---|---|
| VIN | The car's VIN (first slot). | No |
| VIN (second slot) | A second VIN slot. On every real dump checked it holds `XXXXXXXXXXXXXXXXX`, so it is kept as its own field. | No |
| Cluster ID for radio | The value the radio checks to know it is still in the same car. Copy it when replacing a cluster so the radio does not ask for its code. | No |
| Immobilizer ID | 14-character immobiliser ID, stored three times. | No |
| Immobilizer key | The engine-ECU binding key, three copies. | No |
| Key IDs | The learned transponder key data. | No |
| Number of keys | Keys programmed (three copies). | No |
| Immobilizer adaptation status | Not adapted / Adapted (three copies). | No |
| SKC (login code) | The secret key code (PIN) used to log in and adapt keys. Stored three times; an edit writes all three. | Yes |
| Odometer | Eight 16-bit counters, each counted down once per 2 km in turn. The reading is the **sum** of the eight cells as shown, in km. | No |
| Odometer checksum | 7 bytes in front of the counters. Its algorithm is not known, so the app never recomputes it: it only ever moves together with the counters. | No |

The file information shows the odometer as one figure in km, and the same
distance in miles on the cluster's own conversion.

### Firmware patch module

Shown when **Advanced** is ticked above the tree. It is the memory-patch
block the cluster loads into RAM at power-up: on a stock cluster, VDO's own
bug-fix patch; after a sweep patch, the sweep code. It is code for one exact
ROM build, so its name includes that build, for example **Firmware patch
module (VWK501MH 01.10)**. Its description says whether a block is loaded and
whether its header checksum is valid. Change it only with
[Needle and LED sweep patches](needle-sweep.md).

## Checksums

**Tools > Verify checksums...** checks, and **File > Save** corrects:

| Checksum | Covers | If it is wrong |
|---|---|---|
| Gauge / K-value checksum (1 byte) | The K-value and the speedometer map. The checksum byte plus those bytes must add up to 0xFF. | The cluster shows **dEF**. |
| Patch module header (H0) | The patch block, when one is loaded and its header is self-consistent. | The cluster ignores the patch block. |

An erased patch header (no patch loaded) is left alone: correcting it would
invent a patch. The odometer's check value is not a checksum the app can
compute, which is why the odometer is read-only.

## The .vdo file

A cluster read goes into a [project](../../projects.md), as a set holding:

- the 2048-byte EEPROM;
- what the cluster said about itself when it was read: its software version
  (the exact ROM build), its ident, coding and workshop code, and when it was
  read;
- the saved versions.

The software version the cluster reported is the most reliable identity
there is, which is the main reason to keep the read itself rather than a
`.bin`. A `.vdo` from an earlier version of the app carries the same, and a
raw 2048-byte `.bin` from another tool is imported too (**File > Import**).
**File > Export > Binary (.bin)...** writes a plain `.bin`. (A `.vdo` is
import only: the app no longer writes one.)

## Moving data between clusters

- **Same layout** (for example a VWK501 replacing a VWK501): read the new
  cluster and save that read first, then write the old cluster's EEPROM to
  the new cluster. The flasher does not compare the file with the cluster:
  it writes the old cluster's vehicle data (immobiliser, VIN, odometer) over
  the new one's without asking; see
  [Reading and writing the cluster](read-write.md#nothing-is-read-before-the-write).
- **Different layouts**: every field is at a different address, so never
  write one layout's whole EEPROM to a cluster of the other layout. The
  flasher does not check the cluster's layout and would write it anyway,
  putting every field in the wrong place. Instead:
  1. Read the new cluster and keep its tab in front.
  2. Make the old cluster's EEPROM the comparison (**File > Import as
     comparison...**).
  3. **Edit > Generate patch...** lists the fields that differ; tick the
     ones to carry over (for a replacement: the identity and immobiliser
     fields, the odometer with its checksum, the coding you want) and keep
     the patch in the project. It carries the comparison's values.
  4. **Edit > Apply patch...** and pick that patch, then save and write the
     tab to the new cluster.

  Patch entries are matched by field name, and a field has the same name in
  every ROM family, so the values land at the new cluster's own addresses.
  The firmware patch module is the exception: its name carries the ROM
  build, so it only ever applies to the same build.

See [Editing and saving](../../editing.md) for patches in general.
