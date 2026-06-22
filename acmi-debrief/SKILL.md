---
name: acmi-debrief
description: >
  Turn a Tacview ACMI flight recording into a verified after-action debrief of an
  air-combat engagement — rendered as a gripping first-person story, a clinical
  AAR, or an in-character commander's debrief. Use this skill whenever the user
  has a .acmi or .zip.acmi file (from IL-2 Sturmovik, DCS World, MSFS, X-Plane,
  or any Tacview source) and wants to know what happened in a sortie, who they
  killed, how a dogfight or strafing run went, or wants a debrief / war story /
  mission recap from flight-sim telemetry. Trigger even when the user doesn't say
  "ACMI" — phrases like "debrief my flight", "what happened in that engagement",
  "tell the story of this dogfight", "did I get that kill", "analyze my Tacview
  track", or pointing at a Tracks folder all apply. Also use to triage a folder
  of recordings to find the one with a real engagement.
---

# ACMI Combat Debrief

Reconstructs an air-combat engagement from a Tacview ACMI flight recording and
renders it as a debrief. The pipeline is split deliberately:

1. **Deterministic extraction** (`scripts/acmi_debrief.py`) parses the recording,
   rebuilds the geometry, attributes kills, and emits a structured **beat sheet**
   (JSON). This is the ground truth.
2. **Narration** (you, the model) reads the beat sheet and writes the prose.

The split exists to enforce one rule, which is the whole point of the skill:

> ## The accuracy contract
> The story is a *rendering* of true events, never a license to add events. Every
> beat you narrate — the bounce, the break, the overshoot, the kill — must trace
> to a number in the beat sheet. Make the real geometry vivid; do not invent a
> tracer that grazed the canopy if no round came that close, a wingman who wasn't
> there, or a kill the data doesn't support. If the sortie was a dry no-score
> sweep, say so. A narrator that only sounds good on heroic footage is a liar
> waiting to happen; this one tells the truth about a boring sortie too.

Note: most sim ACMI exports (IL-2 especially) carry **no weapon-fire or Event
data**, so kills are *inferred from geometry* — a bandit destroyed while you were
in lethal range and tracking from its rear hemisphere. State this inference
honestly; don't claim gun-camera certainty you don't have.

---

## Workflow

### Step 1 — Locate the file(s)
Uploaded files are under `/mnt/user-data/uploads/`. A user's own recordings live
in their sim's Tracks folder (e.g. `...\IL-2 Sturmovik Battle of Stalingrad\data\Tracks\`).
Both `.acmi` (plain text) and `.zip.acmi` (zipped) are valid; unzip the latter
first (`unzip -p file.zip.acmi`).

### Step 2 — Triage if there's more than one
Don't narrate blind. Scan the folder and rank by engagement intensity:
```
python3 scripts/acmi_debrief.py --triage /path/to/folder
```
This ranks every recording by confirmed kills, merges inside 1 km, and closest
approach. Pick the richest one to narrate. If the whole folder is quiet sweeps,
tell the user — that's a real answer, and suggest they fly a short 1v1 for a
clean demo.

### Step 3 — Extract the beat sheet for the chosen file
```
python3 scripts/acmi_debrief.py path/to/file.acmi --summary
```
`--summary` prints a human-readable précis first, then the full JSON beat sheet.
Read it carefully before writing a word of prose.

### Step 4 — Render in the mode(s) the user asked for
Default to offering all three if unspecified. Ground every beat in the JSON.
Write the result to a markdown file in `/mnt/user-data/outputs/` and present it.

---

## Reading the beat sheet

Top level: `sim_date`, `duration_s`, `player` (aircraft, callsign, coalition,
and a `service`/`presenter` flavor), `forces` (counts + rosters), and
`engagement`.

`engagement` carries the story:
- `player_survived` (and `player_shot_down_at_s` if not) — the arc's ending.
- `kills[]` — each with `victim`, `time_s`, `min_range_m`, `confidence`
  (`confirmed` = you were the closest claimant; `contested` = a friendly was
  closer), `tracking_aspect_min_deg` (≈0 means you got dead astern), and a
  second-by-second `track[]` plus `entry`/`merge` beats. **The `track` is your
  source for tension** — read range, altitude, both speeds, and aspect over time
  to see the bounce, the break, the closure, the overshoot.
- `threats_on_player[]` — when a bandit was on *your* six. This is the danger;
  use it, especially if the player was shot down.
- `enemy_losses_total` / `friendly_losses_total` — the wider furball around the
  player's personal fight.

### Aspect convention (standard BFM)
`aspect_deg` is measured from the **target's tail**: **0° = dead astern** (on his
six), 90° = abeam, 180° = head-on. Low aspect through a closure = a clean
pursuit-curve tracking shot. Aspect swinging high at the merge = you closed too
fast and overshot into his forward quarter (often still a kill, but a control
note worth making).

---

## The three render modes

All three render the *same* beat sheet. Pick voice, not facts.

**`story`** — First-person ("you"), present or tight past, cockpit POV only (no
God's-eye). Pace mirrors the fight: clipped fragments in the merge, room to
breathe in the setup. Give the bandit agency. End on the reversal/kill the
geometry actually shows. ~150–250 words.

**`clinical`** — Structured AAR: Entry conditions, Execution, Outcome,
Assessment, Note. Ego-free, organized around *what happened / why / what to fix*.
Cite the numbers. Real fighter debriefs are blunt; the bluntness is the value.

**`commander`** — The engagement delivered aloud by the player's own CO at the
plotting board. **Pick the service from `player.coalition`** (the beat sheet
provides `presenter`): Axis → Luftwaffe *Staffelkapitän*; Allies + RAF-family
aircraft → RAF *Squadron Leader*; Allies + US aircraft → USAAF *Squadron CO*.
Praise then correction then bottom line, the order a real CO uses. Period texture
in the airmanship vocabulary only — **no political or ideological content**, just
an experienced officer talking tactics.

If the user wants a file with several modes, stack them under one header with the
verified data table on top (see the engine's beat sheet for the numbers), so the
reader can check any beat against the source.

---

## Known ACMI gotchas (why the parser is built the way it is)

These are real defects discovered against live IL-2 data. Don't "simplify" them
out. Full notes in `references/acmi_format.md`.

1. **Same Name, many objects.** A flight of four "P-47D-22" share one Name. Track
   by hex id, never by Name, or you cross-wire aircraft.
2. **End-of-tape mass despawn.** When the recording stops, every surviving object
   gets a `-` removal at `tmax`. Those are despawns, not kills — ignore removals
   within ~3 s of `tmax`.
3. **Recycled object ids.** After an object is removed, its hex id gets reused for
   a *new* object (a downed plane's id becomes a Shrapnel object). The parser
   segments each id by generation ("hexid#gen", split on every removal) so a reuse
   can't clobber the earlier object's type or splice two tracks. This one silently
   eats kills if unhandled.
4. **Aspect sign.** Raw geometry gives angle off the target's *nose*; invert once
   so 0° = astern everywhere downstream.
5. **No weapon data.** IL-2 exports no Event/fire lines; kills are geometric
   inferences. Narrate them as such.

---

## Tuning knobs (top of the script)
`LETHAL_RANGE` (300 m), `LETHAL_ASPECT` (60°), `NEAR_RANGE` (800 m),
`MERGE_RANGE` (1000 m), `DESPAWN_GUARD` (3 s). Loosen `LETHAL_RANGE` for
cannon-armed heavies, tighten for rifle-caliber WWI guns.
