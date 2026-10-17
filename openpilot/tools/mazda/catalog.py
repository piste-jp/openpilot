#!/usr/bin/env python3
"""Catalog the unknown signals and messages of the Mazda DBC from real drives.

For every signal whose name doesn't say what it is (NEW_SIGNAL_*, *_MAYBE, BIT*, ...), and every
signal of a message nobody named yet, show what it does on the drives: value range, how often it
changes, what kind of signal it looks like, and which known signals it moves with. Messages seen on
the bus that the DBC doesn't have at all are listed too.
"""
import argparse
import re
from collections import defaultdict

import numpy as np

from common import can_events

DBC_NAME = "mazda_2017"

UNKNOWN_SIGNAL = re.compile(r"NEW_SIGNAL|MAYBE|UNKNOWN|STATIC|^BIT\d|^SIG|RELATED|counter_or|^CTR_[A-Z]_|^MSG_\d", re.IGNORECASE)
UNKNOWN_MESSAGE = re.compile(r"^NEW_MSG|^MSG_\d|_MAYBE|^last_byte", re.IGNORECASE)

# known signals to compare against: (message, signal, label)
REFERENCES = [
  ("ENGINE_DATA", "SPEED", "speed"),
  ("ENGINE_DATA", "RPM", "rpm"),
  ("ENGINE_DATA", "PEDAL_GAS", "gas pedal"),
  ("BRAKE", "BRAKE_PRESSURE", "brake pressure"),
  ("PEDALS", "BRAKE_ON", "brake pedal on"),
  ("STEER", "STEER_ANGLE", "steering angle"),
  ("BRAKE", "VEHICLE_ACC_X", "accel x"),
  ("BRAKE", "VEHICLE_ACC_Y", "accel y"),
  ("GEAR", "GEAR_BOX", "gear"),
  ("GEAR", "MANUAL_MODE", "manual shift"),
  ("CRZ_CTRL", "CRZ_AVAILABLE", "acc on"),
  ("CRZ_CTRL", "CRZ_ACTIVE", "acc engaged"),
  ("CRZ_INFO", "CTS_MODE", "cts mode"),
  ("CRZ_EVENTS", "CRZ_SPEED", "acc set speed"),
  ("BLINK_INFO", "LEFT_BLINK", "left blinker"),
  ("BLINK_INFO", "RIGHT_BLINK", "right blinker"),
  ("BLINK_INFO", "HIGH_BEAMS", "high beams"),
  ("CHECK_AND_TEMP", "COOLANT_TEMP", "coolant temp"),
  ("SEATBELT", "DRIVER_SEATBELT", "seatbelt"),
  ("DOORS", "FL", "door FL"),
]


def decode(sig, dat: bytes) -> float:
  raw = sig.get_raw_value(dat)
  if sig.is_signed and raw >> (sig.size - 1):
    raw -= 1 << sig.size
  return raw * sig.factor + sig.offset


def kind(raw: np.ndarray, size: int) -> str:
  values = np.unique(raw)
  if len(values) == 1:
    return "constant"
  if len(values) == 2:
    return "flag"
  steps = np.diff(raw) % (1 << size)
  steps = steps[steps != 0]
  if len(steps) and np.mean(steps == 1) > 0.95 and len(values) >= 4:
    return "counter"
  if len(values) <= 8:
    return "enum"
  return "value"


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("logdirs", nargs="+", help="directories with rlog_<n>.zst segments")
  parser.add_argument("--bus", type=int, default=0)
  parser.add_argument("--rate", type=float, default=10., help="samples per second")
  parser.add_argument("--out", default="unknown_signals.md")
  args = parser.parse_args()

  from opendbc.can.dbc import DBC
  dbc = DBC(DBC_NAME)

  last: dict[int, bytes] = {}
  counts: dict[int, int] = defaultdict(int)
  payloads: dict[int, set] = defaultdict(set)
  samples: list[dict[int, bytes]] = []
  duration = 0.
  for logdir in args.logdirs:
    last.clear()
    next_sample, t_end = 0., 0.
    for t, ev in can_events(logdir):
      for m in ev.can:
        if m.src == args.bus:
          dat = bytes(m.dat)
          last[m.address] = dat
          counts[m.address] += 1
          if len(payloads[m.address]) < 5000:
            payloads[m.address].add(dat)
      if t >= next_sample:
        samples.append(dict(last))
        next_sample = t + 1. / args.rate
      t_end = t
    duration += t_end

  def series(msg, sig):
    return np.array([decode(sig, s[msg.address]) if msg.address in s else np.nan for s in samples])

  refs = {}
  for msg_name, sig_name, label in REFERENCES:
    msg = dbc.name_to_msg.get(msg_name)
    if msg is not None and sig_name in msg.sigs:
      refs[label] = series(msg, msg.sigs[sig_name])

  lines = [f"# Unknown signals of {DBC_NAME}", "",
           f"{len(args.logdirs)} drive(s), {duration / 60:.0f} min, bus {args.bus}, sampled at {args.rate:g} Hz.", "",
           "- **kind**: constant / flag (2 values) / enum (up to 8) / counter (+1 steps) / value",
           "- **changes/min**: how often the sampled value changes",
           "- **moves with**: known signals with the highest |correlation| (only for flag, enum and value)", ""]

  for addr in sorted(dbc.msgs):
    msg = dbc.msgs[addr]
    if counts.get(addr, 0) == 0:
      continue
    unknown_msg = bool(UNKNOWN_MESSAGE.search(msg.name))
    sigs = [s for s in msg.sigs.values() if unknown_msg or UNKNOWN_SIGNAL.search(s.name)]
    if not sigs:
      continue
    rate = counts[addr] / duration if duration else 0.
    lines += [f"## {msg.name} ({addr:#x}, {rate:.1f} Hz, {len(payloads[addr])}{'+' if len(payloads[addr]) >= 5000 else ''} distinct payloads)", "",
              "| signal | bits | kind | values | range | changes/min | moves with |", "|---|---|---|---|---|---|---|"]
    for sig in sorted(sigs, key=lambda s: s.start_bit):
      x = series(msg, sig)
      ok = ~np.isnan(x)
      x = x[ok]
      if not len(x):
        continue
      raw = np.array([sig.get_raw_value(s[addr]) for s in samples if addr in s])
      k = kind(raw, sig.size)
      changes = np.count_nonzero(np.diff(x)) / (duration / 60) if duration else 0.
      values = np.unique(x)
      shown = ", ".join(f"{v:g}" for v in values[:6]) + (" ..." if len(values) > 6 else "")
      related = ""
      if k in ("flag", "enum", "value") and np.std(x) > 0:
        corr = []
        for label, ref in refs.items():
          r = ref[ok]
          m = ~np.isnan(r)
          if m.sum() > 100 and np.std(r[m]) > 0:
            c = np.corrcoef(x[m], r[m])[0, 1]
            if abs(c) >= 0.3:
              corr.append((abs(c), f"{label} {c:+.2f}"))
        related = ", ".join(label for _, label in sorted(corr, reverse=True)[:3])
      lines.append(f"| {sig.name} | {sig.start_bit}\\|{sig.size} | {k} | {shown} | {x.min():g} .. {x.max():g} | {changes:.1f} | {related} |")
    lines.append("")

  missing = sorted(a for a in counts if a not in dbc.msgs)
  if missing:
    lines += ["## Messages not in the DBC", "", "| address | Hz | distinct payloads |", "|---|---|---|"]
    for addr in missing:
      lines.append(f"| {addr:#x} | {counts[addr] / duration:.1f} | {len(payloads[addr])}{'+' if len(payloads[addr]) >= 5000 else ''} |")
    lines.append("")

  with open(args.out, "w") as f:
    f.write("\n".join(lines))
  print(f"wrote {args.out}")


if __name__ == "__main__":
  main()
