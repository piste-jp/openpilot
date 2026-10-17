#!/usr/bin/env python3
"""List the bits that change only a few times in a time window.

Good for stationary procedures (switch a light, the A/C, a door on and off) where each action flips a
few bits. Each bit is named by the DBC signal that covers it, or (undefined).
"""
import argparse
from collections import defaultdict

from catalog import DBC_NAME
from common import can_events

OBD_ADDRS = (0x7e0, 0x7e8)


def bit_names(dbc) -> dict[tuple[int, int], str]:
  """(address, DBC bit number) -> MESSAGE.SIGNAL"""
  names = {}
  for msg in dbc.msgs.values():
    for sig in msg.sigs.values():
      bit = sig.start_bit
      for _ in range(sig.size):
        names[(msg.address, bit)] = f"{msg.name}.{sig.name}"
        if sig.is_little_endian:
          bit += 1
        else:
          bit = bit - 1 if bit % 8 else bit + 15
  return names


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("logdir", help="directory with rlog_<n>.zst segments")
  parser.add_argument("start", type=float, help="window start in seconds")
  parser.add_argument("end", type=float, help="window end in seconds")
  parser.add_argument("max_changes", type=int, nargs="?", default=6, help="only bits that changed at most this often")
  args = parser.parse_args()

  from opendbc.can.dbc import DBC
  names = bit_names(DBC(DBC_NAME))

  last: dict[int, int] = {}
  transitions = defaultdict(list)
  for t, ev in can_events(args.logdir):
    if t > args.end:
      break
    for m in ev.can:
      if m.src != 0 or m.address in OBD_ADDRS:
        continue
      value = int.from_bytes(bytes(m.dat).ljust(8, b"\0")[:8], "big")
      prev = last.get(m.address)
      if prev is not None and t >= args.start and prev != value:
        flipped = prev ^ value
        for i in range(64):
          if flipped >> (63 - i) & 1:
            transitions[(m.address, i)].append((t, value >> (63 - i) & 1))
      last[m.address] = value

  rows = []
  for (addr, i), changes in transitions.items():
    if len(changes) <= args.max_changes:
      byte, bit = divmod(i, 8)
      dbc_bit = byte * 8 + 7 - bit
      rows.append((changes[0][0], addr, byte, 7 - bit, names.get((addr, dbc_bit), "(undefined)"),
                   " ".join(f"{t:.1f}s->{v}" for t, v in changes)))
  for _, addr, byte, bit, name, changes in sorted(rows):
    print(f"{addr:#05x} byte{byte} bit{bit}  {name:40s} {changes}")


if __name__ == "__main__":
  main()
