#!/usr/bin/env python3
"""Show when a message's payload changes, next to the known signals that changed at the same time."""
import argparse
import re
from collections import defaultdict

import numpy as np

from catalog import DBC_NAME, UNKNOWN_MESSAGE, UNKNOWN_SIGNAL, decode
from common import can_events


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("logdir", help="directory with rlog_<n>.zst segments")
  parser.add_argument("addrs", help="comma separated hex addresses, e.g. 425,4f7")
  parser.add_argument("--max", type=int, default=40, help="changes to show per message")
  parser.add_argument("--window", type=float, default=0.6, help="seconds around a change to look for known events")
  args = parser.parse_args()

  from opendbc.can.dbc import DBC
  dbc = DBC(DBC_NAME)
  targets = [int(a, 16) for a in args.addrs.split(",")]

  # small known signals (flags and enums) whose transitions mark events
  known = defaultdict(list)
  for msg in dbc.msgs.values():
    if UNKNOWN_MESSAGE.search(msg.name):
      continue
    for sig in msg.sigs.values():
      if sig.size <= 4 and not UNKNOWN_SIGNAL.search(sig.name) and not re.search("CTR|CHK|CHECKSUM|COUNTER", sig.name):
        known[msg.address].append((msg.name, sig))

  prev_value: dict[tuple[str, str], float] = {}
  events: list[tuple[float, str]] = []
  changes = defaultdict(list)
  last: dict[int, bytes] = {}
  for t, ev in can_events(args.logdir):
    for m in ev.can:
      if m.src != 0:
        continue
      dat = bytes(m.dat)
      if m.address in targets:
        if m.address in last and last[m.address] != dat:
          changes[m.address].append((t, last[m.address], dat))
        last[m.address] = dat
      for msg_name, sig in known.get(m.address, []):
        v = decode(sig, dat)
        k = (msg_name, sig.name)
        if k in prev_value and prev_value[k] != v:
          events.append((t, f"{msg_name}.{sig.name} {prev_value[k]:g}->{v:g}"))
        prev_value[k] = v

  event_times = np.array([e[0] for e in events])
  for addr in targets:
    print(f"== {addr:#x}: {len(changes[addr])} changes")
    for t, before, after in changes[addr][:args.max]:
      diff = " ".join(f"b{j}:{before[j]:02x}->{after[j]:02x}" for j in range(min(len(before), len(after))) if before[j] != after[j])
      near = [events[i][1] for i in np.where(np.abs(event_times - t) < args.window)[0]][:6]
      print(f"  {t:8.2f}s  {diff:40s} | {'; '.join(near)}")


if __name__ == "__main__":
  main()
