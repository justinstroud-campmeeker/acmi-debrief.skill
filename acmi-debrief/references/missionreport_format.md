# IL-2 Sturmovik `missionReport` Log Format

IL-2 Great Battles writes plain-text mission event logs to `data/` (filenames
`missionReport(<date>)[n].txt`) when text logging is enabled under `[KEY = system]`
in `startup.cfg`. A single mission is split across numbered chunks `[0]`, `[1]`, …
— parse them together as one stream. These are the logs the community stats tools
(il2-stats etc.) consume.

## Line grammar

```
T:<tick> AType:<code> <space-separated KEY:VALUE fields and POS(x,y,z)>
```

- **T** is a tick counter at **50 ticks/second** → seconds = `T / 50`.
- **POS(X, Y, Z)** is IL-2 world space in **metres**: X = east, **Y = altitude**,
  Z = north. (Note Y is the vertical axis — different from ACMI's lon|lat|alt.)
- IDs are decimal. An aircraft has a plane object plus child objects (pilot bot,
  gunner bots, turrets), each with its own ID and a `PID` pointing at its parent.

## AType event codes (those this skill uses)

| AType | Meaning | Key fields |
|------:|---------|-----------|
| 0 | Mission start / header | `MAP`, `GDate`, `GTime`, mission name |
| 1 | **Hit** | `AMMO:` round type, `AID:` shooter, `TID:` target |
| 2 | **Damage** | `AID:`, `TID:`, damage value, `POS` |
| 3 | **Kill** | `AID:` killer, `TID:` victim, `POS` |
| 4 | Ammo / loadout state | `PLID`, `PID`, `BUL`, `SH`, `BOMB`, `RCT`, `POS` |
| 5 / 6 | Took off / Landed | `PID`, `POS` |
| 10 | **Human player spawn** | `PID`, `NAME` (callsign), `TYPE` (aircraft), login |
| 12 | Object spawn | `ID`, `TYPE`, `COUNTRY`, `NAME`, `PID` |
| 15 | Log version | `VER` |
| 16 | Despawn / bot deinit | `BOTID`, `POS` |
| 18 | Bot group position | `BOTID`, `PARENTID`, `POS` |

Codes not listed (7, 8, 11, 13, 17, 19, 20…) cover round/objective/influence
bookkeeping the debrief doesn't need.

## Country codes

`101` USSR · `102` Great Britain · `103` USA · `201` Germany · `202` Italy.

## Identifying the human player

Best: an `AType:10` line — it carries the player's callsign, aircraft `TYPE`, and
`PID` directly. It lives in the `[0]` chunk at mission start, so it's only present
if early chunks are supplied.

Fallback (used when `[0]` is missing): the player object is the one that scores
kills (`AType:3 AID:`) and/or takes the most hits but is **not** a spawned bot —
bots are named `BotPilot_*`, `BotGunner_*`, `BotPilotNPC_*`, or `Turret_*`. The
player's own plane is typically not emitted as a spawn at all, so "scores kills but
has no `BotPilot` spawn" is a reliable signature. Side can then be inferred from the
nationality embedded in the ammo names (`BULLET_GER_*`, `BULLET_USA_*`, …).

## Gotchas

- **Kill credits ≠ airframes.** Shooting one multi-crew bomber can emit several
  `AType:3` events — the pilot, an NPC co-pilot, individual gunners. Report
  `kill_credits` and `distinct_victims` separately and narrate the difference.
- **No continuous track.** Hits (`AType:1`) carry no position; only kills, spawns,
  ammo-states, and bot-position lines do. So trajectory is a handful of *fixes*
  (mainly at kills/death), not a path. Good enough for altitude trend and attack
  direction; not for turn-by-turn BFM.
- **Ammo `explosion`** appears alongside the projectile types — it's the HE/blast
  component of a strike, so don't double-count it as a separate weapon.
- **Multi-chunk.** Always glob all `[n]` chunks of one mission; kills and spawns
  are scattered across them.

## Pairing with ACMI

The two sources are complementary: ACMI = continuous geometry, no weapon data;
missionReport = authoritative weapon/kill events, sparse geometry. Matching kills
across them (by tick→second and by the `AType:3` POS) upgrades a geometric kill
inference to a confirmed, ammo-counted, shooter-attributed kill. The coordinate
systems differ (ACMI geographic lon/lat vs IL-2 local metres), so automatic spatial
fusion needs a transform; time alignment plus the kill ordering is usually enough to
pair them by hand.
