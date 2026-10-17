#!/usr/bin/env python3
"""Find the CAN bits that are one value during state A and the other during state B."""
import argparse
from collections import defaultdict

import numpy as np

from common import can_events, parse_windows


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("logdir", help="directory with rlog_<n>.zst segments")
  parser.add_argument("--a", required=True, help="time windows of state A in seconds, e.g. 141.8-143.6,169.8-171.6")
  parser.add_argument("--b", required=True, help="time windows of state B in seconds")
  parser.add_argument("--margin", type=float, default=0.5, help="seconds to skip at both ends of each window")
  parser.add_argument("--min-sep", type=float, default=0.9, help="minimum |P(bit=1 | A) - P(bit=1 | B)| to report")
  parser.add_argument("--buses", default="0,2")
  args = parser.parse_args()

  windows = {"a": parse_windows(args.a), "b": parse_windows(args.b)}
  buses = {int(b) for b in args.buses.split(",")}

  def state_at(t):
    for name, ws in windows.items():
      if any(start + args.margin <= t <= end - args.margin for start, end in ws):
        return name
    return None

  ones = defaultdict(lambda: {"a": np.zeros(64), "b": np.zeros(64)})
  counts = defaultdict(lambda: {"a": 0, "b": 0})
  lengths = {}
  for t, ev in can_events(args.logdir):
    state = state_at(t)
    if state is None:
      continue
    for m in ev.can:
      if m.src not in buses:
        continue
      dat = bytes(m.dat)
      key = (m.src, m.address)
      lengths[key] = len(dat)
      bits = np.unpackbits(np.frombuffer(dat.ljust(8, b"\0")[:8], dtype=np.uint8))
      ones[key][state] += bits
      counts[key][state] += 1

  found = []
  for key, n in counts.items():
    if min(n.values()) < 5:
      continue
    p_a = ones[key]["a"] / n["a"]
    p_b = ones[key]["b"] / n["b"]
    for i in range(lengths[key] * 8):
      sep = abs(p_a[i] - p_b[i])
      if sep >= args.min_sep:
        byte, bit = divmod(i, 8)
        found.append((sep, key, byte, 7 - bit, p_a[i], p_b[i], n["a"], n["b"]))

  print("sep    bus  addr   byte bit  dbc start bit  P(1|A)  P(1|B)  msgs A/B")
  for sep, (bus, addr), byte, bit, p_a, p_b, n_a, n_b in sorted(found, key=lambda f: -f[0]):
    print(f"{sep:.3f}  {bus}   {addr:#05x}  {byte}    {bit}    {byte * 8 + bit:3d}            {p_a:.3f}   {p_b:.3f}   {n_a}/{n_b}")


if __name__ == "__main__":
  main()
