"""Command line entry point.

    python -m poolarena demo                 # no hardware: simulated table
    python -m poolarena run --source kinect  # the real thing
    python -m poolarena calibrate --source kinect
    python -m poolarena games
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import webbrowser
from pathlib import Path

from .ballset import get_ball_set
from .camera import CameraService, probe
from . import models as model_store
from .engine import Engine
from .geometry import Calibration, Table
from .rules import available
from .server.ws import Hub, serve
from .types import TableState

ROOT = Path(__file__).resolve().parent.parent
OVERLAY = ROOT / "overlay"
CONFIG = ROOT / "config"


def load_ball_set(args):
    """Command line wins, then the table config, then American."""
    if getattr(args, "ball_set", None):
        return get_ball_set(args.ball_set)
    cfg_path = Path(args.config) if args.config else CONFIG / "table.json"
    if cfg_path.exists():
        return get_ball_set(json.loads(cfg_path.read_text()).get("ball_set"))
    return get_ball_set(None)


def load_table(args) -> Table:
    cfg_path = Path(args.config) if args.config else CONFIG / "table.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text())
        t = Table(size=cfg.get("size", "8ft"),
                  length=cfg.get("length", 0), width=cfg.get("width", 0),
                  ball_radius=cfg.get("ball_radius", 28.6),
                  pocket_capture=cfg.get("pocket_capture", 70.0),
                  cloth=cfg.get("cloth", "#1B6E54"))
    else:
        t = Table(size=args.size)
    if getattr(args, "size", None) and args.size != t.size and not args.config:
        t = Table(size=args.size)
    if getattr(args, "cloth", None):
        t.cloth = args.cloth
    return t


def start_server(engine_hub: Hub, table: Table, port: int, open_browser: bool,
                 ball_set=None, camera: CameraService | None = None):
    bs = ball_set or get_ball_set(None)
    cam = camera or CameraService(table=table,
                                  calibration_path=CONFIG / "calibration.json")
    routes = {
        "/api/games": lambda: {"games": available(bs), "ball_set": bs.to_json()},
        "/api/table": lambda: table.to_json(),
        "/api/camera/status": cam.status,
        "/api/camera/snapshot": cam.snapshot_json,
    }
    weights_dir = ROOT / "weights"
    detector_cfg = CONFIG / "detector.json"

    def detector_status() -> dict:
        cfg = {}
        if detector_cfg.exists():
            cfg = json.loads(detector_cfg.read_text())
        return {
            "detector": cfg.get("detector", "color"),
            "weights": cfg.get("weights", ""),
            "installed": model_store.list_installed(weights_dir),
            "runtime": model_store.runtime().to_json(),
            "allowed_hosts": sorted(model_store.ALLOWED_HOSTS),
            "weights_dir": str(weights_dir),
        }

    def test_detector(m: dict) -> dict:
        frame = None
        blob, meta = (None, {})
        if cam.source is not None:
            blob, meta = cam.snapshot(warm=2)
        if blob is not None:
            import cv2
            import numpy as np
            frame = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_COLOR)
        return model_store.try_model(m.get("weights", ""), sample=frame)

    routes["/api/detector"] = detector_status

    posts = {
        "/api/camera/open": lambda m: cam.open(m.get("spec", "auto")),
        "/api/camera/close": lambda m: (cam.close(), {"ok": True})[1],
        "/api/camera/calibrate": lambda m: cam.calibrate(m.get("points"),
                                                         m.get("image_size")),
        "/api/detector/install_runtime": lambda m: model_store.install_runtime(),
        "/api/detector/install_model": lambda m: model_store.install_model(
            m.get("source", ""), weights_dir, m.get("name", "")),
        "/api/detector/select": lambda m: model_store.select_detector(
            detector_cfg, m.get("detector", "color"), m.get("weights", ""),
            float(m.get("conf", 0.4))),
        "/api/detector/test": test_detector,
        "/api/camera/markers": lambda m: cam.calibrate_markers(),
        "/api/camera/marker_sheet": lambda m: _marker_sheet(),
    }
    httpd = serve(engine_hub, OVERLAY, port=port, http_routes=routes,
                  post_routes=posts)
    url = f"http://localhost:{port}/"
    print(f"  projector   {url}")
    print(f"  scoreboard  {url}scoreboard.html")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return httpd


# --- demo ----------------------------------------------------------------
def cmd_demo(args) -> int:
    """Run the whole stack against the simulator.

    This is the development loop: every effect, every rule and the whole
    websocket path get exercised with no camera, no projector and no table.
    """
    from .sim import FakeTable, auto_shot

    table = load_table(args)
    ball_set = load_ball_set(args)
    hub = Hub()
    engine = Engine(table=table, hub=hub, ball_set=ball_set,
                    idle_after=args.idle_after,
                    projector=not args.no_projector,
                    log_path=Path(args.log) if args.log else None)
    start_server(hub, table, args.port, not args.no_browser, ball_set)

    sim = FakeTable(table=table, rng=random.Random(args.seed))
    sim.rack("9ball" if args.game == "9ball" else "8ball")
    engine.detector.reset(sim.state())
    engine.start_game(args.game, players=[p.strip() for p in args.players.split(",")])

    print(f"\n  demo running: {args.game}, {args.fps} fps, skill {args.skill}")
    print("  ctrl-c to stop\n")

    frame_time = 1.0 / args.fps

    def rack_for(game_name: str) -> None:
        sim.rack("9ball" if game_name == "9ball" else "8ball")

    def current_game() -> str:
        # Whatever is live, which may have been chosen from the tablet rather
        # than on the command line.
        return engine.game.name if engine.game else args.game

    def current_players() -> list[str]:
        if engine.game:
            return [p.name for p in engine.game.players]
        return [p.strip() for p in args.players.split(",")]

    try:
        # Give a browser a moment to connect so the opening effects are seen.
        deadline = time.time() + args.warmup
        while time.time() < deadline:
            engine.feed(sim.state())
            time.sleep(frame_time)

        shots = 0
        while args.shots == 0 or shots < args.shots:
            if sim.cue() is None:
                sim.spot_cue()
                engine.feed(sim.state())
            if len(sim.balls) <= 1:
                rack_for(current_game())
                engine.feed(sim.state())

            info = auto_shot(sim, skill=args.skill)
            if info.get("shot") == "none":
                rack_for(current_game())
                continue
            while sim.moving():
                engine.feed(sim.step_frame())
                time.sleep(frame_time)
            for _ in range(10):
                engine.feed(sim.step_frame())
                time.sleep(frame_time)
            shots += 1
            if engine.game and engine.game.over:
                print(f"  game over after {shots} shots")
                time.sleep(5)
                name, players = current_game(), current_players()
                rack_for(name)
                sim.spot_cue()
                engine.detector.reset(sim.state())
                engine.start_game(name, players=players)
            time.sleep(args.pause)
    except KeyboardInterrupt:
        print("\n  stopped")
    return 0


# --- live ----------------------------------------------------------------
def _marker_sheet() -> dict:
    """Write the printable marker sheet next to the config."""
    from .vision.markers import sheet
    out = sheet(CONFIG / "marker-sheet.png")
    return {"ok": True, "path": str(out),
            "note": "print it, cut out the four markers, and tape each one "
                    "flat on the cloth just inside the corner it names, with "
                    "its outer corner on the cushion corner"}


def cmd_markers(args) -> int:
    """Write the printable calibration markers."""
    from .vision.markers import sheet
    out = sheet(Path(args.out) if args.out else CONFIG / "marker-sheet.png")
    print(f"  wrote {out}\n")
    print("  Print it. Cut out the four markers. Tape each one FLAT on the")
    print("  cloth just inside the corner it names, with its outer corner on")
    print("  the cushion corner.\n")
    print("  Then: python -m poolarena calibrate --markers")
    print("  Leave them up and the camera re-calibrates itself if knocked.")
    return 0


def camera_specs(args) -> list[dict]:
    """Which cameras to use.

    One camera is the default and needs no configuration. A second is an
    option, not a rewrite: each camera keeps its own calibration and the
    fusion happens in table millimetres, so they need not match each other
    or even be the same kind of camera.

    Sources: `--source auto`, `--source "kinect,cam:1"`, or a
    `config/cameras.json` listing them with per-camera height and
    calibration.
    """
    cfg_path = CONFIG / "cameras.json"
    if getattr(args, "cameras", None):
        cfg_path = Path(args.cameras)
    if cfg_path.exists() and not getattr(args, "source", None):
        cams = json.loads(cfg_path.read_text()).get("cameras", [])
        if cams:
            return cams
    specs = [s.strip() for s in str(args.source or "auto").split(",") if s.strip()]
    out = []
    for i, spec in enumerate(specs):
        name = spec.replace(":", "") or f"cam{i}"
        calib = (Path(args.calibration) if len(specs) == 1
                 else CONFIG / f"calibration-{name}.json")
        entry = {"name": name, "source": spec, "calibration": str(calib),
                 "height_mm": getattr(args, "camera_height", 0.0) or 0.0}
        nadir = getattr(args, "camera_nadir", None)
        if nadir and len(specs) > 1:
            raise SystemExit(
                "--camera-nadir sets one position, but you have "
                f"{len(specs)} cameras and each sits somewhere different.\n"
                "List them in config/cameras.json instead — see "
                "config/cameras.json.example.")
        if nadir:
            try:
                x, y = (float(v) for v in str(nadir).split(","))
                entry["nadir"] = [x, y]
            except ValueError:
                raise SystemExit('--camera-nadir wants "X,Y" in table mm, '
                                 f'got {nadir!r}')
        out.append(entry)
    return out


def cmd_run(args) -> int:
    """Real camera, real table."""
    from .vision import open_source
    from .vision.detect import build_detector
    from .vision.multi import CameraView, MultiPipeline
    from .vision.pipeline import VisionPipeline

    table = load_table(args)
    specs = camera_specs(args)
    missing = [c for c in specs if not Path(c["calibration"]).exists()]
    if missing:
        for c in missing:
            print(f"no calibration for {c['name']} at {c['calibration']}",
                  file=sys.stderr)
        print(f"\nrun: python -m poolarena calibrate --source {specs[0]['source']}",
              file=sys.stderr)
        return 2

    ball_set = load_ball_set(args)
    det_cfg: dict = {}
    det_path = CONFIG / "detector.json"
    if det_path.exists():
        det_cfg = json.loads(det_path.read_text())
    det_cfg.setdefault("ball_set", ball_set.name)
    if args.weights:
        det_cfg = {"detector": "yolo", "weights": args.weights}
    detector = build_detector(det_cfg)

    hub = Hub()
    engine = Engine(table=table, hub=hub, ball_set=ball_set,
                    idle_after=args.idle_after,
                    projector=not args.no_projector,
                    log_path=Path(args.log) if args.log else None)
    start_server(hub, table, args.port, not args.no_browser, ball_set)

    views = []
    for c in specs:
        calib = Calibration.load(Path(c["calibration"]))
        pipe = VisionPipeline(table, calib, build_detector(det_cfg),
                              camera_height_mm=float(c.get("height_mm") or 0.0),
                              nadir=tuple(c["nadir"]) if c.get("nadir") else None,
                              name=c["name"])
        depth_calib = Path(c.get("depth_calibration")
                           or CONFIG / "calibration-depth.json")
        if args.depth_balls and depth_calib.exists():
            from .vision.depth import DepthBallFinder
            from .vision.multi import ColourAndDepth
            finder = DepthBallFinder(table=table,
                                     calibration=Calibration.load(depth_calib))
            pipe = ColourAndDepth(table, pipe, finder, name=c["name"])
            print(f"  depth       finding balls too ({depth_calib.name})")
        elif args.depth_balls:
            print(f"  depth       asked for, but no {depth_calib} — "
                  f"calibrate the depth camera first", file=sys.stderr)
        views.append(CameraView(c["name"], open_source(c["source"]), pipe))
        print(f"  camera      {c['name']:<10} {c['source']:<12} "
              f"rms {calib.error_mm:.1f} mm"
              + (f", parallax corrected for {c['height_mm']:.0f} mm"
                 if c.get("height_mm") else ""))
    rig = MultiPipeline(table, views)
    print(f"  balls       {ball_set.title}")
    print(f"  cloth       {table.cloth}")
    print(f"  game        {args.game}\n")

    engine.start_game(args.game, players=[p.strip() for p in args.players.split(",")])

    if args.learn_cloth:
        rig.learn_cloth()
        print("  learned the empty cloth")
    try:
        while True:
            engine.feed(rig.read())
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        engine.close()
        rig.close()
    return 0


# --- calibrate -----------------------------------------------------------
def cmd_calibrate(args) -> int:
    from .vision import open_source
    from .vision.calibrate import calibrate_from_frame

    table = load_table(args)
    source = open_source(args.source)
    frame = None
    for _ in range(30):            # let auto-exposure settle before grabbing
        got = source.read()
        if got and got[0] is not None:
            frame = got[0]
    source.close()
    if frame is None:
        print("no frame from source", file=sys.stderr)
        return 2

    out = Path(args.calibration)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.markers:
        from .vision.markers import calibrate as marker_calibrate
        calib, res = marker_calibrate(frame, table)
        if calib is None:
            names = ", ".join(res.to_json()["missing_names"])
            print(f"found {len(res.found)} of 4 markers — missing {names}",
                  file=sys.stderr)
            print("check they are flat, unobstructed and inside the frame",
                  file=sys.stderr)
            return 2
        calib.save(out)
        print(f"saved {out} from four markers, rms {calib.error_mm:.2f} mm")
        print("leave the markers up and the camera can re-calibrate itself")
        return 0

    calib = calibrate_from_frame(frame, table, out)
    print(f"saved {out}  rms {calib.error_mm:.2f} mm")
    if calib.error_mm > 15:
        print("warning: over 15 mm — re-click the corners, and check the camera "
              "is not moving between frames")
    return 0


# --- replay --------------------------------------------------------------
def cmd_replay(args) -> int:
    """Replay a shot log through a game, which is how rules get regression-tested."""
    table = load_table(args)
    ball_set = load_ball_set(args)
    hub = Hub()
    engine = Engine(table=table, hub=hub, ball_set=ball_set)
    start_server(hub, table, args.port, not args.no_browser, ball_set)
    engine.start_game(args.game, players=[p.strip() for p in args.players.split(",")])

    records = [json.loads(l) for l in Path(args.log).read_text().splitlines() if l.strip()]
    print(f"  replaying {len(records)} shots")
    for rec in records:
        for key in ("before", "after"):
            st = rec[key]
            from .types import Ball, Kind
            state = TableState(
                balls=[Ball(b["number"], b["x"], b["y"], Kind(b.get("kind", "unknown")),
                            b.get("r", 28.6), b.get("confidence", 1.0))
                       for b in st["balls"]],
                ts=st["ts"], settled=st.get("settled", True),
                obstructed=st.get("obstructed", False))
            engine.feed(state)
        time.sleep(args.pause)
    return 0


def cmd_games(args) -> int:
    bs = load_ball_set(args)
    print(f"  ball set: {bs.title}\n")
    for g in available(bs):
        mark = " " if g["supported"] else "x"
        note = "" if g["supported"] else "   (needs numbered balls)"
        print(f" {mark} {g['name']:<10} {g['title']:<18} "
              f"{g['min_players']}-{g['max_players']}p  {g['description']}{note}")
    return 0


def cmd_effects(args) -> int:
    src = (OVERLAY / "src" / "effects.js").read_text()
    block = src.split("export const EFFECTS = {", 1)[1].split("};", 1)[0]
    for line in block.strip().splitlines():
        name = line.strip().split(":")[0]
        if name:
            print(f"  {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Shared options live on a parent parser so they work on either side of the
    # subcommand: "demo --port 9000" and "--port 9000 demo" both run.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="table config json")
    common.add_argument("--size", default="8ft", help="7ft|8ft|8ft-pro|9ft|10ft|snooker")
    common.add_argument("--no-projector", action="store_true",
                        help="scoring only. The guides are drawn on the "
                             "scoreboard's table view instead of the cloth.")
    common.add_argument("--idle-after", type=float, default=90.0,
                        help="seconds of a still, empty table before the "
                             "attract mode starts; 0 turns it off")
    common.add_argument("--cloth", default=None,
                        help="cloth colour as hex, e.g. #8FB7D9 for pale blue; "
                             "the projected palette is chosen from it")
    common.add_argument("--ball-set", default=None,
                        help="american (numbered 1-15) | english (reds and yellows)")
    common.add_argument("--port", type=int, default=8777)
    common.add_argument("--no-browser", action="store_true")
    common.add_argument("--game", default="8ball")
    common.add_argument("--players", default="Player 1, Player 2")
    common.add_argument("--log", help="append shot records here (jsonl)")

    p = argparse.ArgumentParser(prog="poolarena", description=__doc__,
                                parents=[common],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", parents=[common],
                       help="run against the simulator, no hardware")
    d.add_argument("--fps", type=float, default=30.0)
    d.add_argument("--skill", type=float, default=0.78)
    d.add_argument("--shots", type=int, default=0, help="0 = forever")
    d.add_argument("--pause", type=float, default=1.6, help="seconds between shots")
    d.add_argument("--warmup", type=float, default=2.0)
    d.add_argument("--seed", type=int, default=None)
    d.set_defaults(func=cmd_demo)

    r = sub.add_parser("run", parents=[common], help="live camera")
    r.add_argument("--source", default=None,
                   help="auto|kinect|cam:0|video:path. Comma-separate for two "
                        "cameras, e.g. \"kinect,cam:1\". Defaults to auto, or "
                        "to config/cameras.json when that exists.")
    r.add_argument("--cameras", help="a cameras.json listing several cameras")
    r.add_argument("--camera-height", type=float, default=0.0,
                   help="height of the camera above the cloth in mm. Enables "
                        "parallax correction; leave unset if unsure.")
    r.add_argument("--depth-balls", action="store_true",
                   help="also find balls in the Kinect's depth stream. Depth "
                        "ignores shadows, glare and cloth colour entirely, so "
                        "it locates balls where colour struggles; colour still "
                        "names them. Needs config/calibration-depth.json.")
    r.add_argument("--camera-nadir",
                   help="\"X,Y\" in table mm: the spot on the cloth directly "
                        "under the lens. Needed when the camera is off to one "
                        "side, which it must be if a light hangs over the table.")
    r.add_argument("--calibration", default=str(CONFIG / "calibration.json"))
    r.add_argument("--weights", help="YOLO weights, switches the detector")
    r.add_argument("--learn-cloth", action="store_true",
                   help="treat the first frame as an empty table")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("calibrate", parents=[common], help="click the four cushion corners")
    c.add_argument("--source", default="auto")
    c.add_argument("--calibration", default=str(CONFIG / "calibration.json"))
    c.add_argument("--markers", action="store_true",
                   help="calibrate from four printed markers instead of four "
                        "clicks. More accurate, repeatable, and it lets the "
                        "camera re-calibrate itself if knocked.")
    c.set_defaults(func=cmd_calibrate)

    mk = sub.add_parser("markers", parents=[common],
                        help="write the printable calibration markers")
    mk.add_argument("--out", help="where to write the sheet")
    mk.set_defaults(func=cmd_markers)

    rp = sub.add_parser("replay", parents=[common], help="replay a shot log")
    rp.add_argument("log")
    rp.add_argument("--pause", type=float, default=0.8)
    rp.set_defaults(func=cmd_replay)

    sub.add_parser("games", parents=[common], help="list game modes").set_defaults(func=cmd_games)
    sub.add_parser("effects", parents=[common], help="list projector effects").set_defaults(func=cmd_effects)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
