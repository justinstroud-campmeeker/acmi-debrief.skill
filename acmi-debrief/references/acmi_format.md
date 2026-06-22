# ACMI 2.x Format Notes & Field Reference

Tacview's ACMI is plain UTF-8 text (often zipped as `.zip.acmi`). These notes
cover only what the debrief parser needs; the full spec is at
<https://www.tacview.net/documentation/acmi/>.

## File structure

```
FileType=text/acmi/tacview
FileVersion=2.1                       (or 2.2; same structure)
0,ReferenceTime=1944-10-06T08:04:45Z  (global props live on object id 0)
0,Author=majordomo
#0.00                                  (time frame, seconds since ReferenceTime)
1107ff,T=5.77|51.60|714|-21|3|-89,Name=...,Type=Air+FixedWing,Coalition=Axis
...
#0.50                                  (next frame)
1107ff,T=5.78|||-19||                  (only changed T components are present)
-1107ff                                (object removed: destroyed or out of range)
```

Line types:
- `#<seconds>` — a new time frame, seconds relative to `ReferenceTime`.
- `<hexid>,<prop>=<val>,...` — create/update an object. `hexid` is lowercase hex,
  no leading zeros. Object `0` is the global header.
- `-<hexid>` — remove an object from the world.

## The Transform property `T=`

Pipe-delimited, components omitted when unchanged:
`T = Longitude | Latitude | Altitude | Roll | Pitch | Yaw | U | V | Heading`

For aircraft, IL-2 emits the first six: `lon|lat|alt|roll|pitch|yaw`. All metric;
lon/lat in degrees, altitude in metres MSL, angles in degrees, yaw is true
heading. An empty field between pipes means "unchanged — carry the last value
forward" (e.g. `T=5.78|||-19||` updates only longitude and roll).

## Object identification

- `Name=` — aircraft type or label, e.g. `P-47D-22` or `Tempest Mk.V ser.2 - majordomo`.
  **Not unique** — a flight reuses one Name across many objects.
- `Type=` — `Air+FixedWing`, `Air+Rotorcraft`, `Ground+Vehicle`,
  `Weapon+Missile`, `Misc+Shrapnel`, etc. Filter aircraft on `FixedWing`/`Rotorcraft`.
- `Coalition=` — `Allies` / `Axis`. `Color=` — `Blue` / `Red`.
- `Pilot=` — present in some sources (DCS), usually absent in IL-2.

The local player: match the recording's `Author` header against an object `Name`
(IL-2 labels the player's plane with the callsign). Fallback: the one aircraft
whose Name isn't a generic `NN-NN` wingman tag.

## Gotchas (each one cost a real bug)

1. **Name collisions** → key everything by hex id.
2. **End-of-tape despawns** → on recording stop, every live object emits `-id` at
   `tmax`. A death within ~3 s of `tmax` is a despawn, not a kill.
3. **ID recycling** → after `-id`, that hex id is reused for a new object. Segment
   by generation (`hexid#gen`, bump on each removal) so a recycled id (often a
   `Misc+Shrapnel` from the wreck) can't overwrite the aircraft that just died or
   join two unrelated tracks. Symptom if unhandled: confirmed kills vanish because
   the victim's type gets clobbered to non-air and filtered out.
4. **No Event/weapon lines** in IL-2 exports → infer kills from geometry
   (victim removed while player in lethal range, tracking from rear hemisphere).
   DCS *does* export richer data, including real-time telemetry — worth special-
   casing later.
5. **Aspect sign** → angle measured from the line target→attacker relative to the
   target's heading gives angle off the *nose*; subtract from 180 so 0° = astern.

## Possible future enrichments
- IL-2 `missionReport(...).txt` logs (in `data/`, enabled under `[KEY = system]`)
  carry discrete hit/kill events with object IDs — a precise augment for the
  geometric kill inference (confirm trigger pulls and hits).
- DCS real-time telemetry (TCP, ACMI 2.x over the wire) for live debriefing.
- Energy charts (specific energy = alt + v²/2g) plotted over the engagement.
