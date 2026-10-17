import glob
import os


def segment_paths(logdir: str) -> list[str]:
  paths = glob.glob(os.path.join(logdir, "rlog_*.zst"))
  return sorted(paths, key=lambda p: int(os.path.basename(p)[len("rlog_"):-len(".zst")]))


def can_events(logdir: str):
  """Yield (seconds since the first CAN message, can event) for every CAN event of the route."""
  from opendbc.car.logreader import LogReader

  t0 = None
  for path in segment_paths(logdir):
    for ev in LogReader(path, only_union_types=True):
      if ev.which() != "can":
        continue
      if t0 is None:
        t0 = ev.logMonoTime
      yield (ev.logMonoTime - t0) / 1e9, ev


def parse_windows(arg: str) -> list[tuple[float, float]]:
  """'1.5-3,10-12.5' -> [(1.5, 3.0), (10.0, 12.5)]"""
  windows = []
  for part in arg.split(","):
    start, end = part.split("-")
    windows.append((float(start), float(end)))
  return windows
