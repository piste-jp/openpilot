#!/usr/bin/env python3
"""Print the stock ACC state and the steering wheel button presses of a route over time."""
import argparse

from common import can_events

# CRZ_BTNS: (label, byte, bit). CANCEL is the physical button, CAN_OFF is what openpilot sends to cancel.
BUTTONS = [
  ("MRCC", 1, 7),
  ("CTS", 1, 3),
  ("SET+", 0, 4),
  ("SET-", 0, 5),
  ("RES", 0, 2),
  ("CANCEL", 0, 1),
  ("CAN_OFF", 0, 0),
  ("DIST-", 0, 7),
  ("DIST+", 0, 6),
]


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("logdir", help="directory with rlog_<n>.zst segments")
  args = parser.parse_args()

  from opendbc.can import CANParser
  cp = CANParser("mazda_2017", [("CRZ_CTRL", 0), ("CRZ_INFO", 0), ("CRZ_EVENTS", 0), ("ENGINE_DATA", 0), ("PEDALS", 0)], 0)

  prev_state = None
  prev_buttons: set[str] = set()
  for t, ev in can_events(args.logdir):
    cp.update([(ev.logMonoTime, [(m.address, bytes(m.dat), m.src) for m in ev.can])])

    buttons = prev_buttons
    for m in ev.can:
      if m.address == 0x9d and m.src == 0:
        dat = bytes(m.dat)
        buttons = {name for name, byte, bit in BUTTONS if dat[byte] >> bit & 1}

    state = (int(cp.vl["CRZ_CTRL"]["CRZ_AVAILABLE"]), int(cp.vl["CRZ_CTRL"]["CRZ_ACTIVE"]), int(cp.vl["CRZ_INFO"]["CTS_MODE"]))
    pressed = buttons - prev_buttons
    if state != prev_state or pressed:
      acc = f"available={state[0]} engaged={state[1]} cts={state[2]}"
      car = f"speed={cp.vl['ENGINE_DATA']['SPEED']:5.1f} set={cp.vl['CRZ_EVENTS']['CRZ_SPEED']:3.0f} brake={int(cp.vl['PEDALS']['BRAKE_ON'])}"
      print(f"{t:8.2f}s  {acc}  {car}  {' '.join(sorted(pressed))}")
      prev_state = state
    prev_buttons = buttons


if __name__ == "__main__":
  main()
