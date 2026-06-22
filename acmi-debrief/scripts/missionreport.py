#!/usr/bin/env python3
"""
missionreport.py — Parse IL-2 Sturmovik `missionReport(...).txt` event logs into
a player-centric engagement beat sheet, for debriefing when no Tacview .acmi track
exists (or to confirm/augment one that does).

Where the ACMI gives continuous geometry but no weapon data, these logs give the
opposite: authoritative discrete events — who hit whom, with what ammo, who killed
whom — plus position fixes at each kill. This script extracts that into the same
kind of beat sheet `acmi_debrief.py` emits, so the SKILL.md render modes (story /
clinical / commander) work on log-only sorties.

Usage:
  python3 missionreport.py report1.txt [report2.txt ...] [--summary]
  python3 missionreport.py --glob "missionReport(2026-06-22_13-45-00)*.txt"

Pass ALL chunks of one mission together — IL-2 splits a single mission's log into
numbered files ([0], [1], ... [n]); they must be parsed as one stream.

Format notes (see references/missionreport_format.md):
  * Lines: `T:<tick> AType:<n> <fields>`. Ticks run at 50/sec -> seconds = T/50.
  * AType 1=Hit (AMMO/AID/TID), 2=Damage, 3=Kill (AID/TID/POS), 4=ammo state,
    10=human player spawn (NAME/TYPE/PID), 12=object spawn (TYPE/COUNTRY/NAME/PID),
    15=version, 16=despawn, 18=bot group pos.
  * POS is (X, altitude, Z) in metres of IL-2 world space (Y is up).
  * The human player is usually NOT logged as a `BotPilot_*` spawn — detect them as
    the kill-scoring / most-hit object that isn't a bot, or via an AType:10 line.
"""

import sys, os, re, json, glob
from collections import defaultdict

TICK_HZ = 50.0


def parse_files(paths):
    spawns = {}          # id -> {type, country, name, pid, is_bot}
    player_decl = None   # from AType:10 if present: {id,name,type,pid}
    events = []          # (tick, atype, dict)
    header = {}

    spawn_re = re.compile(
        r'AType:1[02] ID:(\d+) TYPE:(.+?) COUNTRY:(\d+) NAME:(.+?) PID:(-?\d+)')
    a10_re = re.compile(
        r'AType:10 .*?PID:(\d+).*?NAME:(.+?) (?:TYPE:(.+?) )?')
    hit_re = re.compile(r'AType:1 AMMO:(\S+) AID:(\d+) TID:(\d+)')
    dmg_re = re.compile(r'AType:2 .*?AID:(\d+) TID:(\d+)')
    kill_re = re.compile(
        r'AType:3 AID:(\d+) TID:(\d+) POS\(([-\d.]+),([-\d.]+),([-\d.]+)\)')

    for path in paths:
        for raw in open(path, encoding="utf-8", errors="replace"):
            line = raw.strip()
            tm = re.match(r'T:(\d+)\s+AType:(\d+)', line)
            if not tm:
                continue
            tick, atype = int(tm.group(1)), int(tm.group(2))
            if atype == 0:           # mission header (map/date) if present
                for kv in re.findall(r'(\w+):(\S+)', line):
                    header.setdefault(kv[0], kv[1])
            elif atype in (10, 12):
                s = spawn_re.search(line)
                if s:
                    oid, typ, country, name, pid = s.groups()
                    is_bot = name.startswith(("BotPilot", "BotGunner", "Turret",
                                              "BotPilotNPC"))
                    spawns.setdefault(oid, {"type": typ, "country": country,
                                            "name": name, "pid": pid,
                                            "is_bot": is_bot})
                if atype == 10:
                    a = a10_re.search(line)
                    if a:
                        player_decl = {"pid": a.group(1), "name": a.group(2),
                                       "type": a.group(3) or "?"}
            elif atype == 1:
                h = hit_re.search(line)
                if h:
                    events.append((tick, 1, {"ammo": h.group(1),
                                             "aid": h.group(2), "tid": h.group(3)}))
            elif atype == 2:
                d = dmg_re.search(line)
                if d:
                    events.append((tick, 2, {"aid": d.group(1), "tid": d.group(2)}))
            elif atype == 3:
                k = kill_re.search(line)
                if k:
                    events.append((tick, 3, {"aid": k.group(1), "tid": k.group(2),
                                             "pos": (float(k.group(3)),
                                                     float(k.group(4)),
                                                     float(k.group(5)))}))
    return header, spawns, player_decl, events


def label(oid, spawns):
    s = spawns.get(oid)
    if not s:
        return f"id{oid}"
    return s["name"] if s["is_bot"] else s["type"]


def country_side(country):
    # IL-2 country codes: 101 USSR, 102 GB, 103 USA, 201 Germany, 202 Italy
    return {"101": "VVS", "102": "RAF", "103": "USAAF",
            "201": "Luftwaffe", "202": "Regia Aeronautica"}.get(country, "?")


def find_player(spawns, player_decl, events):
    if player_decl:
        # match declared PID to a spawn id sharing that pid, else use pid
        for oid, s in spawns.items():
            if s["pid"] == player_decl["pid"]:
                return oid
        return player_decl["pid"]
    # heuristic: kill-scoring non-bot
    kill_scorers = defaultdict(int)
    hit_counts = defaultdict(int)
    for tick, at, d in events:
        if at == 3:
            kill_scorers[d["aid"]] += 1
        if at == 1:
            hit_counts[d["aid"]] += 1
            hit_counts[d["tid"]] += 1
    for oid in sorted(kill_scorers, key=lambda x: -kill_scorers[x]):
        if not spawns.get(oid, {}).get("is_bot", False):
            return oid
    # fallback: most-involved non-bot object
    for oid in sorted(hit_counts, key=lambda x: -hit_counts[x]):
        if not spawns.get(oid, {}).get("is_bot", False):
            return oid
    return None


def analyze(paths):
    header, spawns, player_decl, events = parse_files(paths)
    player = find_player(spawns, player_decl, events)
    if not player:
        return {"error": "could not identify a player object in the logs"}

    kills, death = [], None
    hits_landed = defaultdict(int)
    hits_taken = defaultdict(int)
    ammo_used = defaultdict(int)
    fixes = []  # (sec, x, alt, z) position fixes for the player

    for tick, at, d in sorted(events, key=lambda x: (x[0], x[1])):
        sec = round(tick / TICK_HZ, 1)
        if at == 1:
            if d["aid"] == player:
                hits_landed[label(d["tid"], spawns)] += 1
                ammo_used[d["ammo"]] += 1
            elif d["tid"] == player:
                hits_taken[label(d["aid"], spawns)] += 1
        elif at == 3:
            if d["aid"] == player:
                kills.append({"t": sec, "victim": label(d["tid"], spawns),
                              "victim_country": spawns.get(d["tid"], {}).get("country"),
                              "pos": d["pos"]})
                fixes.append((sec, *d["pos"]))
            elif d["tid"] == player:
                death = {"t": sec, "killer": label(d["aid"], spawns),
                         "killer_id": d["aid"], "pos": d["pos"]}
                fixes.append((sec, *d["pos"]))

    fixes.sort()
    alt_start = fixes[0][2] if fixes else None
    alt_end = fixes[-1][2] if fixes else None

    pdecl_type = player_decl["type"] if player_decl else None
    pside = country_side(spawns.get(player, {}).get("country", "?"))
    # if player country unknown, infer side from ammo nationality
    if pside == "?" and ammo_used:
        if any("GER" in a for a in ammo_used): pside = "Luftwaffe"
        elif any("USA" in a for a in ammo_used): pside = "USAAF"
        elif any("RAF" in a or "GB" in a for a in ammo_used): pside = "RAF"

    presenter = {"Luftwaffe": "Staffelkapitan", "RAF": "Squadron Leader",
                 "USAAF": "Squadron CO", "VVS": "Komeskuie"}.get(pside, "CO")

    return {
        "source": [os.path.basename(p) for p in paths],
        "sim_date": header.get("GDate", header.get("DATE", "unknown")),
        "map": header.get("MAP", "unknown"),
        "player": {
            "id": player,
            "aircraft": pdecl_type or "unknown (not logged as a spawn)",
            "side": pside,
            "presenter": presenter,
        },
        "engagement": {
            "kills": kills,
            "kill_credits": len(kills),
            "distinct_victims": len({k["victim"] for k in kills}),
            "player_killed": death is not None,
            "death": death,
            "strikes_landed": sum(hits_landed.values()),
            "strikes_taken": sum(hits_taken.values()),
            "hits_by_target": dict(sorted(hits_landed.items(), key=lambda x: -x[1])),
            "hits_by_shooter": dict(sorted(hits_taken.items(), key=lambda x: -x[1])),
            "ammo_used": dict(sorted(ammo_used.items(), key=lambda x: -x[1])),
            "altitude_start_m": round(alt_start) if alt_start is not None else None,
            "altitude_end_m": round(alt_end) if alt_end is not None else None,
            "position_fixes": [{"t": f[0], "x": round(f[1]), "alt": round(f[2]),
                                "z": round(f[3])} for f in fixes],
        },
        "note": ("Kill counts are kill CREDITS; crew/gunner positions inflate them "
                 "above distinct airframes. No weapon-fire = N/A here: these ARE the "
                 "weapon events. Trajectory limited to position fixes at kill/death."),
    }


def print_summary(a):
    if "error" in a:
        print("ERROR:", a["error"]); return
    p, e = a["player"], a["engagement"]
    print(f"\nSource: {', '.join(a['source'])}")
    print(f"Player: object {p['id']}  | {p['aircraft']}  [{p['side']}]")
    print(f"Kills: {e['kill_credits']} credits ({e['distinct_victims']} distinct targets)"
          f"   Player killed: {e['player_killed']}")
    for k in e["kills"]:
        print(f"  KILL  t={k['t']:>6}s  {k['victim']}")
    if e["death"]:
        d = e["death"]
        print(f"  DIED  t={d['t']:>6}s  by {d['killer']} (id {d['killer_id']})")
    print(f"Gunnery: {e['strikes_landed']} landed / {e['strikes_taken']} taken")
    if e["ammo_used"]:
        print("  ammo:", ", ".join(f"{k}×{v}" for k, v in e["ammo_used"].items()))
    if e["altitude_start_m"] is not None:
        print(f"  altitude {e['altitude_start_m']}m -> {e['altitude_end_m']}m")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    if "--glob" in argv:
        i = argv.index("--glob")
        args = sorted(glob.glob(argv[i + 1]))
    if not args:
        print(__doc__); return 1
    a = analyze(sorted(args))
    if "--summary" in argv and "error" not in a:
        print_summary(a)
        print("\n--- JSON beat sheet ---")
    print(json.dumps(a, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
