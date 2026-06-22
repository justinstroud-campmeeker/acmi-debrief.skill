# ACMI Debrief

**Turn a Tacview flight recording into a verified after-action debrief — as a gripping first-person story, a clinical AAR, or your CO's voice at the plotting board.**

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![Skill](https://img.shields.io/badge/Claude-Agent%20Skill-d97757)
![License](https://img.shields.io/badge/license-MIT-green)

`acmi-debrief` reads a `.acmi` flight recording (from **IL-2 Sturmovik**, **DCS World**, **MSFS**, **X-Plane**, or any Tacview source), reconstructs the geometry of an air-combat engagement, works out what actually happened — who you killed, who was on your six, how the merge went — and narrates it back to you. It's an [Agent Skill](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) for Claude, but the analysis engine also runs standalone from the command line.

---

## Why it exists

A flight recorder knows everything — every position, heading, and speed, ten times a second — but it tells you none of it. Reading an `.acmi` in Tacview is a chore; turning it into a story you'd actually retell is impossible by hand. This skill does both halves: a deterministic engine that extracts the **ground truth** of the engagement, and a narration layer that renders it in the voice you want.

The design rests on one rule:

> **The story is a rendering of true events, never a license to add events.**
> Every beat — the bounce, the break, the overshoot, the kill — traces to a number in the data. If the sortie was a dry no-score sweep, it says so. A narrator that only sounds good on heroic footage is a liar waiting to happen.

---

## Example

Point it at a folder and it finds your best fight:

```
$ acmi_debrief.py --triage ~/IL-2/data/Tracks

 SCORE  FILE                                  PLANE          CLOSEST MERGE KILL
------------------------------------------------------------------------------
  1440  sortie_1944-07-05.acmi                Me 410 A-1       0.0km    13    1   RTB
   200  sortie_1917-07-05.acmi                SPAD 7.C1        0.4km     5    0   RTB
    42  sweep_1944-10-06.acmi                 Tempest Mk.V     7.7km     0    0   RTB
```

Then debrief the winner — here, the same engagement in **story** and **commander** voice, both built from one verified data table:

> You see him before he sees you — a lone Thunderbolt, fat and confident, three hundred on the clock down on the deck. The 410 is a heavy beast; in a turning fight that Jug would carve you apart. So you don't turn. You trade your height for speed and come down behind him like a dropped anvil…

> *Staffelkapitän, at the plotting board:* "You did **not** turn — and I want every other 410 driver in this room to hear it. From a kilometre and a quarter down to forty-six metres, and he was a dead man the whole time and never knew it. Now the part you won't like. Forty-six metres. You blew straight through him…"

| Time | Range | Your alt | Your speed | Target speed | Aspect* |
|-----:|------:|---------:|-----------:|-------------:|--------:|
| 544s | 1,263 m | 272 m | 456 km/h | ~300 km/h | 22° |
| 569s | **46 m** | 165 m | 429 km/h | 134 km/h | 125° |
| 574s | — | — | — | **0 (impact)** | — |

<sub>*Aspect from the target's tail: 0° = dead astern. Low through the pursuit, swinging high at the overshoot.*</sub>

---

## Requirements

- **Python 3.8+** — standard library only, **zero pip installs**.
- A Tacview-format recording (`.acmi` or `.zip.acmi`).
- To use it *as a skill*: Claude Code, Claude Desktop, the Claude Agent SDK, or any other agent that reads the `SKILL.md` format. (The CLI works on its own with no agent at all.)

---

## Installation

### As a Claude skill (recommended)

Skills live in a `skills/` directory and are auto-discovered — clone this repo's folder straight into it.

**Personal** (available in every project):

```bash
git clone https://github.com/justinstroud-campmeeker/acmi-debrief.git ~/.claude/skills/acmi-debrief
```

**Project-scoped** (committed with a repo, shared with collaborators):

```bash
git clone https://github.com/justinstroud-campmeeker/acmi-debrief.git .claude/skills/acmi-debrief
```

On Windows the personal path is `%USERPROFILE%\.claude\skills\acmi-debrief`. The paths are otherwise identical across macOS, Linux, and Windows.

> ⚠️ The skill must sit at `…/skills/acmi-debrief/SKILL.md` — exactly one folder deep. Nesting it deeper is the most common reason a skill won't load.

Start a **new** Claude session after installing so the skill is discovered, then just ask in natural language (see Usage). On **claude.ai**, zip the `acmi-debrief/` folder and upload it under *Settings → Capabilities → Skills* instead.

### As a standalone CLI (no agent required)

```bash
git clone https://github.com/justinstroud-campmeeker/acmi-debrief.git
cd acmi-debrief
python3 scripts/acmi_debrief.py --triage /path/to/Tracks
```

---

## Generating recordings

### IL-2 Sturmovik: Great Battles

Tacview recording is off by default. Edit `…\IL-2 Sturmovik Battle of Stalingrad\data\startup.cfg` and set:

```
[KEY = track_record]
    tacviewrecord = 1
[END]
```

Then press **LCtrl+R** in flight to record. Files land in `…\data\Tracks\` as `.acmi`. (Make sure that folder exists — some builds don't auto-create it.)

### DCS World / MSFS / X-Plane

Record through Tacview's normal export for your sim. Any ACMI 2.x file works; DCS additionally exposes richer data the engine can take advantage of later (see Roadmap).

---

## Usage

### Through Claude (natural language)

Once installed, the skill triggers on intent — no commands to memorize:

- *"Debrief my last IL-2 flight — the .acmi is in my Tracks folder."*
- *"Scan these recordings and find the one with a real dogfight."*
- *"Tell the story of this engagement, then give me the clinical version."*
- *"Did I actually get that kill, or did my wingman?"*

Claude runs the engine, reads the structured beat sheet, and writes the debrief — defaulting to a markdown file you can keep.

### Through the CLI

```bash
# Rank every recording in a folder by how much actually happened
python3 scripts/acmi_debrief.py --triage /path/to/Tracks

# Full analysis of one file: human summary + JSON beat sheet
python3 scripts/acmi_debrief.py path/to/flight.acmi --summary

# Just the machine-readable beat sheet (pipe into jq, etc.)
python3 scripts/acmi_debrief.py path/to/flight.acmi
```

The CLI produces the **data**; the narrative voices are generated by Claude reading that data via the skill.

---

## The three voices

All three render the *same* extracted facts — you pick the register, not the content.

| Mode | Voice | Use it for |
|------|-------|------------|
| **story** | First-person, cockpit POV, present tense | The war story you'd retell |
| **clinical** | Structured AAR — entry / execution / outcome / assessment | Finding your mistakes |
| **commander** | Your CO debriefing you aloud, service-accurate | Immersion, with a kick in the pants |

`commander` mode reads the player's coalition and picks the presenter automatically — Luftwaffe *Staffelkapitän*, RAF *Squadron Leader*, or USAAF *Squadron CO* — with period airmanship vocabulary and no ideological content; just an officer talking tactics.

---

## Supported simulators

Anything that exports **Tacview ACMI 2.x**. Tested extensively against IL-2 Great Battles (including Flying Circus WWI content). DCS, MSFS, and X-Plane recordings parse through the same pipeline; sim-specific quirks are handled where known.

A note on honesty: most sim exports (IL-2 in particular) contain **no weapon-fire data**, so kills are *inferred from geometry* — a bandit destroyed while you were in lethal range and tracking from its rear hemisphere. The skill states this inference plainly rather than claiming gun-camera certainty.

---

## ACMI quirks handled

These are real defects found against live data, each of which silently corrupts a naive parser:

- **Name collisions** — a flight of four identically-named `P-47D-22`s. Everything is keyed by hex ID, never by name.
- **End-of-tape despawns** — when recording stops, every surviving object emits a removal at the final timestamp. Those are despawns, not kills, and are filtered.
- **Recycled object IDs** — after an object dies, its hex ID gets reused for a new object (a downed plane's ID becomes a `Shrapnel` object). Each ID is segmented by generation so a reuse can't clobber the aircraft that just died. *This one eats confirmed kills if unhandled.*
- **Aspect sign** — inverted once at the source so 0° always means dead astern downstream.

Full notes in [`references/acmi_format.md`](references/acmi_format.md).

---

## Repository layout

```
acmi-debrief/
├── SKILL.md                     # Skill instructions (triggering, workflow, render modes)
├── scripts/
│   └── acmi_debrief.py          # Parser + analyzer + beat-sheet emitter (stdlib only)
└── references/
    └── acmi_format.md           # ACMI 2.x format notes & the gotcha catalog
```

---

## Roadmap

- **Hit confirmation** from IL-2's `missionReport(...).txt` logs — turning geometric kill *inference* into kill *confirmation* by reading actual hit events.
- **DCS real-time telemetry** (TCP ACMI stream) for live, in-mission debriefing.
- **Energy charts** — specific energy plotted across the engagement.
- **Multi-kill sorties** and section/flight-level summaries.

---

## Contributing

Issues and PRs welcome — especially sample `.acmi` files from simulators other than IL-2, which are the best way to harden the parser against new ACMI dialects.

---

## License

MIT — see [`LICENSE`](LICENSE). *(Add a LICENSE file before publishing.)*

---

## Acknowledgements

Built on the open [Tacview ACMI format](https://www.tacview.net/documentation/acmi/). Not affiliated with Raia Software (Tacview), 1C Game Studios (IL-2), or Eagle Dynamics (DCS). Kills are reconstructed from telemetry geometry and represent a best-effort inference, not an official scoring authority — fly accordingly.
