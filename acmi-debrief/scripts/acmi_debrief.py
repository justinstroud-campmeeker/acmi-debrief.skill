#!/usr/bin/env python3
"""
acmi_debrief.py — Parse Tacview ACMI flight recordings and extract a verified
"beat sheet" of an air-combat engagement for narration.

This script does the DETERMINISTIC half of the debrief pipeline: it parses the
recording, reconstructs the geometry, attributes kills, and emits a structured
JSON beat sheet. The PROSE half (story / clinical / commander renderings) is done
by Claude reading that beat sheet — see SKILL.md. The script never writes prose
and the prose must never invent events the script didn't find.

Modes:
  --triage <dir>      Scan every .acmi in a folder, rank by engagement intensity.
  <file.acmi>         Full analysis of one recording -> JSON beat sheet on stdout.
  --summary           With a single file, also print a human-readable summary.

Hard-won correctness notes (do not "simplify" these away):
  * Track objects by hex ID, never by Name. IL-2 reuses identical Names across a
    whole flight (four "P-47D-22"s, etc.); name-matching cross-wires aircraft.
  * Ignore object removals within DESPAWN_GUARD seconds of end-of-tape. When a
    recording stops, every surviving object gets a '-' removal at tmax. Those are
    despawns, not kills.
  * Aspect angle uses standard BFM convention: 0 deg = dead astern (on the
    target's six), 180 deg = head-on. (The raw geometry gives the angle off the
    target's nose; we invert it once, here, so every consumer is correct.)
  * IL-2's ACMI export carries no weapon-fire or Event lines, so kills are
    inferred from geometry + the victim's removal, not read from the file.
"""

import sys, os, re, json, math, glob

DESPAWN_GUARD   = 3.0     # s; removals within this of tmax are despawns, not deaths
LETHAL_RANGE    = 300.0   # m; player within this of a dying bandit -> candidate kill
LETHAL_ASPECT   = 60.0    # deg; and within this aspect (on the tail) to attribute
NEAR_RANGE      = 800.0   # m; "you were near" threshold for ambiguous attribution
MERGE_RANGE     = 1000.0  # m; counts as a pass/merge


# ---------------------------------------------------------------- parsing ----
def parse(path):
    """Parse an ACMI file into per-object tracks.

    Objects are keyed by a *logical* id "hexid#generation". ACMI recycles a hex
    id after the object is removed (e.g. a downed P-47's id gets reused for a
    Shrapnel object). Bumping the generation on every removal keeps each physical
    object distinct, so a later reuse can't clobber the earlier object's type or
    splice two flight paths together.
    """
    header = {}
    aircraft = {}        # logical_id -> {name, coalition, type, color}
    series = {}          # logical_id -> list of (t, lon, lat, alt, roll, pitch, yaw)
    death = {}           # logical_id -> t of removal
    state = {}           # logical_id -> [lon,lat,alt,roll,pitch,yaw] carry-forward
    gen = {}             # hexid -> current generation counter
    t = 0.0
    tmax = 0.0

    def key(hexid): return f"{hexid}#{gen.get(hexid, 0)}"
    def is_air(typ): return "FixedWing" in typ or "Rotorcraft" in typ

    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            c0 = line[0]
            if c0 == "#":
                try:
                    t = float(line[1:]); tmax = max(tmax, t)
                except ValueError:
                    pass
                continue
            if c0 == "-":
                hexid = line[1:].strip()
                k = key(hexid)
                if k not in death:
                    death[k] = t
                gen[hexid] = gen.get(hexid, 0) + 1   # next reuse = new object
                continue
            m = re.match(r'^([0-9a-fA-F]+),', line)
            if not m:
                continue
            hexid = m.group(1)
            if hexid == "0":                         # global header object
                for kv in line.split(",")[1:]:
                    if "=" in kv:
                        kk, vv = kv.split("=", 1)
                        header[kk.strip()] = vv.strip()
                continue
            k = key(hexid)
            tm = re.search(r'(?:^|,)T=([^,]*)', line)
            if k not in state:
                state[k] = [None] * 6
            if tm:
                for i, p in enumerate(tm.group(1).split("|")):
                    if i < 6 and p != "":
                        try: state[k][i] = float(p)
                        except ValueError: pass
            if "Name=" in line or "Type=" in line:
                nm = re.search(r'(?:^|,)Name=([^,]*)', line)
                ty = re.search(r'(?:^|,)Type=([^,]*)', line)
                co = re.search(r'(?:^|,)Coalition=([^,]*)', line)
                cl = re.search(r'(?:^|,)Color=([^,]*)', line)
                rec = aircraft.setdefault(k, {"name": "?", "coalition": "?",
                                              "type": "", "color": ""})
                if nm: rec["name"] = nm.group(1)
                if ty: rec["type"] = ty.group(1)
                if co: rec["coalition"] = co.group(1)
                if cl: rec["color"] = cl.group(1)
            rec = aircraft.get(k)
            if rec and is_air(rec["type"]):
                s = state[k]
                if s[0] is not None and s[1] is not None and s[2] is not None:
                    series.setdefault(k, []).append(
                        (t, s[0], s[1], s[2], s[3] or 0.0, s[4] or 0.0, s[5] or 0.0))

    aircraft = {k: a for k, a in aircraft.items()
                if is_air(a["type"]) and series.get(k)}
    death = {k: dt for k, dt in death.items() if k in aircraft}
    return header, aircraft, series, death, tmax


# ----------------------------------------------------------- geometry utils --
def make_geo(series):
    lats = [p[2] for s in series.values() for p in s[:1]]
    lat0 = sum(lats) / len(lats) if lats else 0.0
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(lat0))
    return m_lon, m_lat


def sampler(series, tmax):
    """1 Hz carry-forward position lookup per object."""
    S = {}
    for oid, s in series.items():
        out = {}; idx = 0; last = s[0]
        for sec in range(0, int(tmax) + 1):
            while idx < len(s) and s[idx][0] <= sec:
                last = s[idx]; idx += 1
            if s[0][0] <= sec <= s[-1][0] + 5:
                out[sec] = last
        S[oid] = out
    return S


class Geo:
    def __init__(self, S, m_lon, m_lat):
        self.S, self.mx, self.my = S, m_lon, m_lat

    def at(self, oid, sec):
        return self.S.get(oid, {}).get(sec)

    def rng(self, a, b, sec):
        pa, pb = self.at(a, sec), self.at(b, sec)
        if not pa or not pb: return None
        ax, ay, az = pa[1]*self.mx, pa[2]*self.my, pa[3]
        bx, by, bz = pb[1]*self.mx, pb[2]*self.my, pb[3]
        return math.dist((ax, ay, az), (bx, by, bz))

    def speed(self, oid, sec):
        p1, p2 = self.at(oid, sec-1), self.at(oid, sec)
        if not p1 or not p2: return None
        d = math.dist((p1[1]*self.mx, p1[2]*self.my), (p2[1]*self.mx, p2[2]*self.my))
        return d * 3.6  # km/h ground speed

    def aspect(self, attacker, target, sec):
        """Standard BFM aspect: 0 deg = attacker dead astern of target."""
        pa, pt = self.at(attacker, sec), self.at(target, sec)
        if not pa or not pt: return None
        dx = (pa[1]-pt[1]) * self.mx
        dy = (pa[2]-pt[2]) * self.my
        brg = math.degrees(math.atan2(dx, dy)) % 360      # bearing target->attacker
        off_nose = abs(((brg - pt[6] + 180) % 360) - 180)  # 0=ahead of tgt,180=astern
        return 180.0 - off_nose                            # invert -> 0=astern


# ----------------------------------------------------------- player & kills --
def find_player(header, aircraft):
    author = header.get("Author", "").strip().lower()
    if author:
        for oid, a in aircraft.items():
            if author and author in a["name"].lower():
                return oid
    # fallback: the one whose name isn't a generic "NN-NN" wingman tag
    for oid, a in aircraft.items():
        if not re.search(r'\b\d\d?-\d\d?\b', a["name"]):
            return oid
    return next(iter(aircraft), None)


def real_death(death, oid, tmax):
    return oid in death and death[oid] < tmax - DESPAWN_GUARD


def coalition_service(coalition, name):
    c = (coalition or "").lower()
    if c == "axis":
        return {"service": "Luftwaffe", "presenter": "Staffelkapitan",
                "enemy_word": "the Allies"}
    if c == "allies":
        # crude RAF vs USAAF guess from aircraft family
        n = name.lower()
        if any(k in n for k in ("spitfire", "tempest", "typhoon", "mosquito",
                                 "hurricane", "lancaster", "fokker", "se.5", "sopwith")):
            return {"service": "RAF", "presenter": "Squadron Leader",
                    "enemy_word": "the Luftwaffe"}
        return {"service": "USAAF", "presenter": "Squadron CO",
                "enemy_word": "the Luftwaffe"}
    return {"service": "Squadron", "presenter": "CO", "enemy_word": "the enemy"}


def analyze(path, want_summary=False):
    header, aircraft, series, death, tmax = parse(path)
    if not aircraft:
        return {"file": os.path.basename(path), "error": "no aircraft tracks found"}
    m_lon, m_lat = make_geo(series)
    S = sampler(series, tmax)
    geo = Geo(S, m_lon, m_lat)
    player = find_player(header, aircraft)
    pc = aircraft[player]["coalition"]
    enemies = [o for o in aircraft if aircraft[o]["coalition"] != pc and o != player]
    friends = [o for o in aircraft if aircraft[o]["coalition"] == pc and o != player]

    # closest approach + merge count
    merges = []
    for e in enemies:
        best = (1e9, None)
        for sec in range(0, int(tmax) + 1):
            r = geo.rng(player, e, sec)
            if r and r < best[0]:
                best = (r, sec)
        if best[1] is not None:
            merges.append((best[0], best[1], e))
    n_merge = sum(1 for r, _, _ in merges if r < MERGE_RANGE)
    min_enemy = min((r for r, _, _ in merges), default=None)

    # kill attribution
    kills = []
    for e in enemies:
        if not real_death(death, e, tmax):
            continue
        dt = int(death[e])
        best_r, best_t = 1e9, None
        track_aspect_min = 1e9          # best (lowest) aspect achieved while close
        for sec in range(max(0, dt - 15), dt + 1):
            r = geo.rng(player, e, sec)
            if not r:
                continue
            if r < best_r:
                best_r, best_t = r, sec
            if r < NEAR_RANGE:           # only judge aspect while in/near guns range
                a = geo.aspect(player, e, sec)
                if a is not None and a < track_aspect_min:
                    track_aspect_min = a
        # is another friendly a better claimant?
        rival = 1e9
        for f in friends:
            for sec in range(max(0, dt - 15), dt + 1):
                r = geo.rng(f, e, sec)
                if r and r < rival:
                    rival = r
        # attribute if you closed to guns range AND tracked from his rear hemisphere
        on_tail = track_aspect_min < LETHAL_ASPECT
        if best_r < LETHAL_RANGE and on_tail:
            confidence = "confirmed" if best_r < rival else "contested"
            k = build_kill(geo, aircraft, player, e, dt, best_r, best_t, confidence)
            k["tracking_aspect_min_deg"] = round(track_aspect_min)
            kills.append(k)

    # threats on the player (bandit on your six)
    threats = []
    for sec in range(0, int(tmax) + 1):
        for e in enemies:
            r = geo.rng(e, player, sec)
            if r and r < 400:
                asp = geo.aspect(e, player, sec)  # bandit astern of YOU
                if asp is not None and asp < 45:
                    threats.append({"t": sec, "bandit": aircraft[e]["name"],
                                    "range": round(r), "aspect": round(asp)})
    # collapse threat runs
    threats = collapse_runs(threats)

    out = {
        "file": os.path.basename(path),
        "sim_date": header.get("ReferenceTime", "?")[:10],
        "title": header.get("Title", ""),
        "author": header.get("Author", "?"),
        "duration_s": round(tmax),
        "player": {
            "id": player,
            "aircraft": aircraft[player]["name"].split(" - ")[0],
            "callsign": aircraft[player]["name"].split(" - ")[-1],
            "coalition": pc,
            **coalition_service(pc, aircraft[player]["name"]),
        },
        "forces": {
            "friendly": len(friends) + 1,
            "enemy": len(enemies),
            "roster_enemy": sorted({aircraft[o]["name"].split(" - ")[0] for o in enemies}),
            "roster_friendly": sorted({aircraft[o]["name"].split(" - ")[0]
                                       for o in friends}),
        },
        "engagement": {
            "merges_under_1km": n_merge,
            "closest_enemy_m": round(min_enemy) if min_enemy else None,
            "player_survived": not real_death(death, player, tmax),
            "kills": kills,
            "threats_on_player": threats,
            "enemy_losses_total": sum(1 for e in enemies if real_death(death, e, tmax)),
            "friendly_losses_total": sum(1 for f in friends if real_death(death, f, tmax)),
        },
    }
    if not out["engagement"]["player_survived"]:
        out["engagement"]["player_shot_down_at_s"] = round(death[player])
    return out


def build_kill(geo, aircraft, player, e, dt, best_r, best_t, confidence):
    """Extract the second-by-second beat sheet for one kill."""
    track = []
    for sec in range(max(0, dt - 30), dt + 1):
        r = geo.rng(player, e, sec)
        pp, tp = geo.at(player, sec), geo.at(e, sec)
        if not (r and pp and tp):
            continue
        track.append({
            "t": sec,
            "range_m": round(r),
            "your_alt_m": round(pp[3]),
            "tgt_alt_m": round(tp[3]),
            "your_kmh": round(geo.speed(player, sec) or 0),
            "tgt_kmh": round(geo.speed(e, sec) or 0),
            "aspect_deg": round(geo.aspect(player, e, sec) or 0),
        })
    # entry conditions (~30 s out) vs merge
    entry = track[0] if track else {}
    merge = min(track, key=lambda x: x["range_m"]) if track else {}
    return {
        "victim": aircraft[e]["name"].split(" - ")[0],
        "victim_full": aircraft[e]["name"],
        "victim_id": e,
        "time_s": dt,
        "min_range_m": round(best_r),
        "min_range_t": best_t,
        "confidence": confidence,
        "entry": entry,
        "merge": merge,
        "track": track,
    }


def collapse_runs(events, gap=4):
    if not events: return []
    runs = []; cur = [events[0]]
    for ev in events[1:]:
        if ev["t"] - cur[-1]["t"] <= gap:
            cur.append(ev)
        else:
            runs.append(cur); cur = [ev]
    runs.append(cur)
    out = []
    for run in runs:
        best = min(run, key=lambda x: x["range"])
        out.append({"t_start": run[0]["t"], "t_end": run[-1]["t"],
                    "closest_m": best["range"], "bandit": best["bandit"]})
    return out


# ------------------------------------------------------------------ triage ---
def triage(folder):
    rows = []
    for f in sorted(glob.glob(os.path.join(folder, "*.acmi"))):
        try:
            a = analyze(f)
        except Exception as ex:
            rows.append({"file": os.path.basename(f), "error": str(ex)}); continue
        if "error" in a:
            rows.append(a); continue
        eng = a["engagement"]
        score = (len([k for k in eng["kills"] if k["confidence"] == "confirmed"]) * 1000
                 + eng["merges_under_1km"] * 30
                 + (50000 - min(eng["closest_enemy_m"] or 50000, 50000)) / 1000)
        rows.append({"file": a["file"], "score": round(score),
                     "plane": a["player"]["aircraft"], "date": a["sim_date"],
                     "dur_min": round(a["duration_s"]/60),
                     "closest_km": round((eng["closest_enemy_m"] or 0)/1000, 1),
                     "merges": eng["merges_under_1km"],
                     "kills": len(eng["kills"]),
                     "survived": eng["player_survived"]})
    rows.sort(key=lambda r: r.get("score", -1), reverse=True)
    return rows


def print_triage(rows):
    print(f"{'SCORE':>6}  {'FILE':40} {'PLANE':18} {'CLOSEST':>8} {'MERGE':>5} {'KILL':>4}")
    print("-" * 92)
    for r in rows:
        if "error" in r:
            print(f"{'ERR':>6}  {r['file']:40} {r['error'][:30]}"); continue
        print(f"{r['score']:6d}  {r['file']:40} {r['plane']:18} "
              f"{r['closest_km']:6.1f}km {r['merges']:5d} {r['kills']:4d}   "
              f"{r['date']} {r['dur_min']}min "
              f"{'RTB' if r['survived'] else 'KIA'}")


def print_summary(a):
    p = a["player"]; e = a["engagement"]
    print(f"\n{a['file']}  ({a['sim_date']}, {a['duration_s']}s)")
    print(f"  Player: {p['aircraft']} \"{p['callsign']}\" [{p['coalition']} / {p['service']}]")
    print(f"  Forces: {a['forces']['friendly']} friendly vs {a['forces']['enemy']} enemy")
    print(f"  Survived: {e['player_survived']}   Merges <1km: {e['merges_under_1km']}"
          f"   Closest enemy: {e['closest_enemy_m']}m")
    print(f"  Losses: {e['enemy_losses_total']} enemy / {e['friendly_losses_total']} friendly")
    if e["kills"]:
        for k in e["kills"]:
            print(f"  KILL [{k['confidence']}]: {k['victim']} @ {k['time_s']}s "
                  f"(min {k['min_range_m']}m astern)")
    else:
        print("  No player kills detected.")
    if e["threats_on_player"]:
        for th in e["threats_on_player"]:
            print(f"  THREAT: {th['bandit']} on your six "
                  f"{th['t_start']}-{th['t_end']}s ({th['closest_m']}m)")


# -------------------------------------------------------------------- main ---
def main(argv):
    if len(argv) < 2:
        print(__doc__); return 1
    if argv[1] == "--triage":
        print_triage(triage(argv[2]))
        return 0
    path = argv[1]
    want_summary = "--summary" in argv
    a = analyze(path)
    if want_summary and "error" not in a:
        print_summary(a)
        print("\n--- JSON beat sheet ---")
    print(json.dumps(a, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
