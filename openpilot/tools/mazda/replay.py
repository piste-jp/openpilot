#!/usr/bin/env python3
"""Replay a drive's CAN and carControl through a Mazda CarInterface, and diff two replays."""
import argparse
import importlib.util
import os
import pickle
import shutil
import sys
import tempfile
from collections import defaultdict

from common import can_events, segment_paths

CC_FILE = "cc.pkl"

# Mazda fields before they were grouped into CarState.mazda
LEGACY_MAZDA_FIELDS = {"gearStep": "gearStep", "brakeLamp": "brakeLamp",
                       "mazdaVelocityControlMode": "velocityControlMode", "mazdaCtsMode": "ctsMode"}


def plan_target_kph(cc) -> float:
  if hasattr(cc, "mazda"):
    return cc.mazda.planTargetKph
  return getattr(cc, "mazdaPlanTargetKph", 0.)


def mazda_fields(cs) -> dict:
  if hasattr(cs, "mazda"):
    return {k: round(v, 3) if isinstance(v, float) else v for k, v in cs.mazda.to_dict().items()}
  return {new: getattr(cs, old) for old, new in LEGACY_MAZDA_FIELDS.items() if hasattr(cs, old)}


def extract_cc(args):
  """Decode carControl with the schema the drive was recorded with, one entry per CAN event."""
  import capnp
  import zstandard as zstd

  spec = importlib.util.find_spec("opendbc")
  assert spec is not None and spec.submodule_search_locations is not None
  car_dir = os.path.join(spec.submodule_search_locations[0], "car")

  with tempfile.TemporaryDirectory() as tmp:
    shutil.copy(args.car_capnp or os.path.join(car_dir, "car.capnp"), os.path.join(tmp, "car.capnp"))
    schema = open(os.path.join(car_dir, "rlog.capnp")).read().replace("reserved23 @23 :Void;", "carControl @23 :Car.CarControl;")
    open(os.path.join(tmp, "rlog.capnp"), "w").write(schema)
    capnp.remove_import_hook()
    log = capnp.load(os.path.join(tmp, "rlog.capnp"), imports=[tmp])

  cc_log, cc = [], None
  for path in segment_paths(args.logdir):
    dat = zstd.ZstdDecompressor().stream_reader(open(path, "rb").read()).read()
    for ev in log.Event.read_multiple_bytes(dat):
      try:
        which = ev.which()
      except capnp.KjException:
        continue
      if which == "carControl":
        c = ev.carControl
        cc = {
          "enabled": c.enabled, "latActive": c.latActive, "torque": c.actuators.torque,
          "cancel": c.cruiseControl.cancel, "resume": c.cruiseControl.resume,
          "visualAlert": str(c.hudControl.visualAlert), "planTargetKph": plan_target_kph(c),
        }
      elif which == "can":
        cc_log.append(cc)

  with open(os.path.join(args.logdir, CC_FILE), "wb") as f:
    pickle.dump(cc_log, f)
  print(f"{len(cc_log)} CAN events, {sum(1 for c in cc_log if c and c['enabled'])} with openpilot enabled")


def run(args):
  sys.path.insert(0, os.path.abspath(args.opendbc))
  from opendbc.car import structs
  from opendbc.car.can_definitions import CanData
  from opendbc.car.mazda.interface import CarInterface

  with open(os.path.join(args.logdir, CC_FILE), "rb") as f:
    cc_log = pickle.load(f)

  CP = CarInterface.get_params(args.platform, {0: {}, 1: {}, 2: {}}, [], False, False, False)
  CI = CarInterface(CP)

  cs_fields = ["steerFaultTemporary", "steerFaultPermanent", "invalidLkasSetting", "lowSpeedAlert"]
  rows = []
  for i, (t, ev) in enumerate(can_events(args.logdir)):
    cs = CI.update([(ev.logMonoTime, [CanData(m.address, bytes(m.dat), m.src) for m in ev.can])])

    sends = []
    d = cc_log[i]
    if d is not None:
      cc = structs.CarControl.new_message()
      cc.enabled = d["enabled"]
      cc.latActive = d["latActive"]
      cc.actuators.torque = d["torque"]
      cc.cruiseControl.cancel = d["cancel"]
      cc.cruiseControl.resume = d["resume"]
      cc.hudControl.visualAlert = d["visualAlert"]
      if hasattr(cc, "mazda"):
        cc.mazda.planTargetKph = d["planTargetKph"]
      elif hasattr(cc, "mazdaPlanTargetKph"):
        cc.mazdaPlanTargetKph = d["planTargetKph"]
      _, sends = CI.apply(cc.as_reader(), ev.logMonoTime)

    # fields this checkout's car.capnp doesn't have are left out
    row = {f: getattr(cs, f) for f in cs_fields if hasattr(cs, f)}
    row.update({f"mazda.{k}": v for k, v in mazda_fields(cs).items()})
    cruise = cs.cruiseState
    row.update(available=cruise.available, enabled=cruise.enabled, speed=round(cruise.speed, 4),
               speedCluster=round(cruise.speedCluster, 4),
               buttonEvents=[(str(b.type), b.pressed) for b in cs.buttonEvents],
               sends=sorted((s[0], bytes(s[1]).hex(), s[2]) for s in sends))
    rows.append((t, row))

  with open(args.out, "wb") as f:
    pickle.dump(rows, f)
  print(f"{len(rows)} frames -> {args.out}")


def diff(args):
  with open(args.a, "rb") as f:
    a = pickle.load(f)
  with open(args.b, "rb") as f:
    b = pickle.load(f)
  assert len(a) == len(b), "replays are of different drives"

  keys_a, keys_b = set(a[0][1]) if a else set(), set(b[0][1]) if b else set()
  for name, only in (("a", keys_a - keys_b), ("b", keys_b - keys_a)):
    if only:
      print(f"only in {name}, not compared: {', '.join(sorted(only))}")

  ranges: dict[str, list[list[float]]] = defaultdict(list)
  counts: dict[str, int] = defaultdict(int)
  for (t, ra), (_, rb) in zip(a, b, strict=True):
    for k in keys_a & keys_b:
      if ra[k] != rb[k]:
        counts[k] += 1
        # merge differences less than a second apart into one range
        if ranges[k] and t - ranges[k][-1][1] < 1.:
          ranges[k][-1][1] = t
        else:
          ranges[k].append([t, t])

  if not counts:
    print("identical")
  for k in sorted(counts):
    shown = ", ".join(f"{s:.1f}-{e:.1f}s" for s, e in ranges[k][:args.max_ranges])
    more = f" (+{len(ranges[k]) - args.max_ranges} more)" if len(ranges[k]) > args.max_ranges else ""
    print(f"{k}: {counts[k]} frames, {shown}{more}")


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  sub = parser.add_subparsers(dest="cmd", required=True)

  p = sub.add_parser("extract-cc", help="save carControl next to the logs, run this first")
  p.add_argument("logdir")
  p.add_argument("--car-capnp", help="car.capnp the drive was recorded with (default: this opendbc's)")
  p.set_defaults(func=extract_cc)

  p = sub.add_parser("run", help="replay through an opendbc checkout")
  p.add_argument("logdir")
  p.add_argument("--opendbc", required=True, help="opendbc_repo checkout to run")
  p.add_argument("--platform", required=True, help="e.g. MAZDA_6_WAGON_2022")
  p.add_argument("--out", required=True)
  p.set_defaults(func=run)

  p = sub.add_parser("diff", help="compare two replays")
  p.add_argument("a")
  p.add_argument("b")
  p.add_argument("--max-ranges", type=int, default=10)
  p.set_defaults(func=diff)

  args = parser.parse_args()
  args.func(args)


if __name__ == "__main__":
  main()
