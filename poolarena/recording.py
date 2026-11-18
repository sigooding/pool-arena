"""Recording sessions, and what you can learn from them afterwards.

The engine already knows everything worth keeping: where every ball was
before and after each shot, which ball was struck first, what dropped, and —
because the detector samples while the balls are rolling — the path each ball
actually took. None of that survived the process, so a night's play taught
nobody anything.

A recording is one file per game. It is deliberately plain JSON rather than a
database: a frame of pool is small, a night is a few hundred kilobytes, and
being able to open the file in a text editor is worth more than query speed
at this size.

The statistics are chosen to answer the question a player actually asks,
which is not "how many did I pot" but "where am I losing frames". Pot rate,
the fouls that cost the most, how far the cue ball travels (position play),
and the longest run are the four that tell you something you can act on.
"""
from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _now() -> float:
    return time.time()


@dataclass
class Recorder:
    """Writes one file per game, appending as it is played.

    Appending rather than writing at the end matters: a session that ends
    because somebody closed the laptop is still worth watching back.
    """

    directory: Path
    keep_traces: bool = True
    session: dict[str, Any] | None = None
    path: Path | None = None

    def start(self, game: Any, table: Any, ball_set: Any) -> dict[str, Any]:
        self.directory.mkdir(parents=True, exist_ok=True)
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.session = {
            "id": sid,
            "started": _now(),
            "finished": None,
            "game": game.name,
            "title": game.title,
            "players": [p.name for p in game.players],
            "ball_set": ball_set.name,
            "table": table.to_json(),
            "shots": [],
            "winner": None,
        }
        self.path = self.directory / f"{sid}.json"
        self._flush()
        return self.session

    def add_shot(self, record: dict[str, Any], events: Any) -> None:
        if self.session is None:
            return
        shot = dict(record)
        if self.keep_traces and getattr(events, "trace", None):
            # Rounded to the millimetre and thinned: at 30 fps a long shot is
            # hundreds of points per ball and nobody can see the difference.
            shot["trace"] = {
                str(n): [[round(x, 1), round(y, 1)] for x, y in pts[::2]]
                for n, pts in events.trace.items() if len(pts) > 1
            }
        shot["at"] = _now()
        self.session["shots"].append(shot)
        self._flush()

    def finish(self, winner: int | None = None) -> None:
        if self.session is None:
            return
        self.session["finished"] = _now()
        self.session["winner"] = winner
        self._flush()
        self.session = None
        self.path = None

    def _flush(self) -> None:
        if self.session and self.path:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.session))
            tmp.replace(self.path)


# --- reading them back ----------------------------------------------------
def list_sessions(directory: Path, limit: int = 60) -> list[dict[str, Any]]:
    """Summaries, newest first. Cheap enough to call on every page load."""
    if not directory.is_dir():
        return []
    out = []
    for f in sorted(directory.glob("*.json"), reverse=True)[:limit]:
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        shots = d.get("shots", [])
        out.append({
            "id": d.get("id", f.stem),
            "title": d.get("title", d.get("game", "game")),
            "game": d.get("game"),
            "players": d.get("players", []),
            "started": d.get("started"),
            "finished": d.get("finished"),
            "shots": len(shots),
            "winner": d.get("winner"),
            "duration": (d["finished"] - d["started"])
                        if d.get("finished") and d.get("started") else None,
        })
    return out


def load_session(directory: Path, session_id: str) -> dict[str, Any] | None:
    safe = Path(session_id).name                 # no traversal via the id
    f = directory / f"{safe}.json"
    if not f.is_file():
        return None
    try:
        d = json.loads(f.read_text())
    except Exception:
        return None
    d["stats"] = analyse(d)
    return d


def delete_session(directory: Path, session_id: str) -> bool:
    f = directory / f"{Path(session_id).name}.json"
    if f.is_file():
        f.unlink()
        return True
    return False


# --- across the whole night, and the ones before it ----------------------
def career(directory: Path, limit: int = 400) -> dict[str, Any]:
    """Totals per player name, across every recording.

    Names are matched as typed, which is crude but honest: there are no
    accounts here, and inventing identity matching would create confident
    nonsense the first time somebody types "sam" instead of "Sam". It
    lower-cases for matching and shows the spelling used most.
    """
    if not directory.is_dir():
        return {"players": [], "games": 0}
    tally: dict[str, dict[str, Any]] = {}
    games = 0
    for f in sorted(directory.glob("*.json"), reverse=True)[:limit]:
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if not d.get("shots"):
            continue
        games += 1
        stats = analyse(d)
        winner = d.get("winner")
        for i, p in enumerate(stats["players"]):
            if not p["shots"]:
                continue
            key = p["name"].strip().lower()
            t = tally.setdefault(key, {
                "name": p["name"], "spellings": {}, "games": 0, "wins": 0,
                "shots": 0, "pots": 0, "balls_potted": 0, "fouls": 0,
                "best_run": 0, "travel": [], "foul_kinds": {},
            })
            t["spellings"][p["name"]] = t["spellings"].get(p["name"], 0) + 1
            t["games"] += 1
            t["wins"] += 1 if winner == i else 0
            for k in ("shots", "pots", "balls_potted", "fouls"):
                t[k] += p[k]
            t["best_run"] = max(t["best_run"], p["best_run"])
            if p["avg_cue_travel_mm"]:
                t["travel"].append(p["avg_cue_travel_mm"])
            for kind, n in p["foul_kinds"].items():
                t["foul_kinds"][kind] = t["foul_kinds"].get(kind, 0) + n

    out = []
    for t in tally.values():
        travel = t.pop("travel")
        t["name"] = max(t.pop("spellings").items(), key=lambda kv: kv[1])[0]
        t["pot_rate"] = round(t["pots"] / t["shots"], 3) if t["shots"] else None
        t["foul_rate"] = round(t["fouls"] / t["shots"], 3) if t["shots"] else None
        t["avg_cue_travel_mm"] = round(sum(travel) / len(travel)) if travel else None
        t["worst_foul"] = (max(t["foul_kinds"].items(), key=lambda kv: kv[1])[0]
                           if t["foul_kinds"] else None)
        t["win_rate"] = round(t["wins"] / t["games"], 3) if t["games"] else None
        out.append(t)
    out.sort(key=lambda p: (-p["games"], p["name"]))
    return {"players": out, "games": games}


def unfinished(directory: Path) -> dict[str, Any] | None:
    """The most recent game that never ended, if there is one.

    Someone closes the laptop mid-frame far more often than they press a
    button marked "finish". The recording is already on disk shot by shot,
    so the scores can be handed straight back rather than lost.
    """
    if not directory.is_dir():
        return None
    for f in sorted(directory.glob("*.json"), reverse=True)[:20]:
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if d.get("finished") is None and d.get("shots"):
            return d
    return None


# --- what the numbers say -------------------------------------------------
def analyse(session: dict[str, Any]) -> dict[str, Any]:
    """Per-player figures aimed at "where am I losing frames".

    Deliberately not a wall of counters. Pot rate says whether you are
    making balls; the foul breakdown says how you are handing the table
    over; cue-ball travel is the closest single number to position play,
    because a player with good position moves the cue ball less and still
    has a shot; the longest run is the one everybody wants to know.
    """
    players: list[str] = session.get("players", [])
    per = {i: {
        "name": n, "shots": 0, "pots": 0, "balls_potted": 0, "fouls": 0,
        "safes": 0, "foul_kinds": {}, "cue_travel": [], "best_run": 0,
    } for i, n in enumerate(players)}

    run = {i: 0 for i in per}
    for shot in session.get("shots", []):
        i = shot.get("shooter", 0)
        p = per.get(i)
        if p is None:
            continue
        ev = shot.get("events", {})
        res = shot.get("result", {})
        potted = list(ev.get("pocketed") or [])
        p["shots"] += 1
        p["balls_potted"] += len(potted)

        if res.get("foul"):
            p["fouls"] += 1
            kind = str(res["foul"]).split("(")[0].strip()
            p["foul_kinds"][kind] = p["foul_kinds"].get(kind, 0) + 1
            run[i] = 0
        elif potted:
            p["pots"] += 1
            run[i] += len(potted)
            p["best_run"] = max(p["best_run"], run[i])
        else:
            p["safes"] += 1
            run[i] = 0

        before, after = shot.get("before", {}), shot.get("after", {})
        cb = next((b for b in before.get("balls", []) if b.get("number") == 0), None)
        ca = next((b for b in after.get("balls", []) if b.get("number") == 0), None)
        if cb and ca:
            p["cue_travel"].append(math.dist((cb["x"], cb["y"]), (ca["x"], ca["y"])))

    out = []
    for i, p in sorted(per.items()):
        travel = p.pop("cue_travel")
        p["avg_cue_travel_mm"] = round(sum(travel) / len(travel)) if travel else None
        p["pot_rate"] = round(p["pots"] / p["shots"], 3) if p["shots"] else None
        p["foul_rate"] = round(p["fouls"] / p["shots"], 3) if p["shots"] else None
        p["worst_foul"] = (max(p["foul_kinds"].items(), key=lambda kv: kv[1])[0]
                           if p["foul_kinds"] else None)
        out.append(p)

    return {
        "players": out,
        "shots": sum(p["shots"] for p in out),
        "insight": _insight(out),
    }


def _insight(players: list[dict[str, Any]]) -> str:
    """One sentence worth reading. Better than ten numbers nobody looks at."""
    ranked = [p for p in players if p["shots"] >= 4]
    if not ranked:
        return "Not enough shots yet to say anything useful."
    p = min(ranked, key=lambda q: q["pot_rate"] or 0)
    bits = []
    if p["pot_rate"] is not None:
        bits.append(f"{p['name']} potted on {round(p['pot_rate'] * 100)}% of shots")
    if p["worst_foul"]:
        bits.append(f"and gave the table away most often by {p['worst_foul']}")
    if p["avg_cue_travel_mm"]:
        bits.append(f"moving the cue ball {p['avg_cue_travel_mm']} mm a shot on average")
    return ", ".join(bits) + "."
