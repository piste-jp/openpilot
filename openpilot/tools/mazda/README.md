# Mazda CAN analysis tools

Small scripts used to port the Mazda 6 Wagon 2022 (GJ5FW). What each signal turned out to be, and what is
still open, is tracked in [`signal_tracker.md`](signal_tracker.md). They work on local rlogs, so they don't
need comma connect and run fine on a Mac with the opendbc venv
(`opendbc_repo/.venv/bin/python`, with `PYTHONPATH` unset).

## Get the logs

```sh
./fetch_route.sh 0000018b--91b661fef8 /tmp/logs18b          # from `ssh comma4` by default
./fetch_route.sh 0000018b--91b661fef8 /tmp/logs18b mydevice  # or another ssh host
```

Segments land as `rlog_<n>.zst`. All scripts below take that directory.

## Timeline of the stock ACC

```sh
python timeline.py /tmp/logs18b
```

Prints a line whenever the stock ACC state (available / engaged / CTS mode) changes or a steering
wheel button is pressed, with the time in seconds since the start of the route. Use it to find the
time windows of the states you want to compare.

## Find the bits that tell two states apart

```sh
python findbits.py /tmp/logs18b --a 141.8-143.6,169.8-171.6 --b 162.1-163.7,166.0-169.8
```

Checks every bit of every message on bus 0 and 2, and prints the ones that are (almost) always one
value inside the `--a` windows and the other value inside the `--b` windows. This is how
`CRZ_INFO.CTS_MODE` was found. `--margin` trims each window to skip the transition itself.

## Compare two versions of the car code on a real drive

```sh
# carControl from the log, decoded with the car.capnp the drive was recorded with
python replay.py extract-cc /tmp/logs186 --car-capnp /path/to/old/opendbc/car/car.capnp

# run CarState + CarController of two opendbc checkouts on the same CAN and carControl
python replay.py run /tmp/logs186 --opendbc /path/to/old/opendbc_repo --platform MAZDA_6 --out old.pkl
python replay.py run /tmp/logs186 --opendbc ../../../opendbc_repo --platform MAZDA_6_WAGON_2022 --out new.pkl

python replay.py diff old.pkl new.pkl
```

`diff` lists every CarState field and CAN send that differs, with the time ranges where it does.
An old checkout is easy to get with `git -C opendbc_repo worktree add /tmp/opendbc_old <commit>`.

## Catalog the unknown signals

```sh
python catalog.py /tmp/logs186 /tmp/logs18b --out unknown_signals.md
```

Lists every DBC signal whose name doesn't say what it is (and every signal of an unnamed message):
value range, how often it changes, whether it looks like a flag, enum, counter or value, and which
known signals it moves with. Messages on the bus that the DBC doesn't have are listed at the end.
[`unknown_signals.md`](unknown_signals.md) is the catalog of two drives of the Mazda 6 Wagon 2022.

## What changed when a message changed

```sh
python changes.py /tmp/logs18b 425,4f7
```

For messages that rarely change (body and status messages), prints every payload change with the
known flags and enums that changed within `--window` seconds of it. This is how the turn signal
latch in 0x425 and the standstill bits in 0x47b were found.

## Bits that flipped during a stationary procedure

```sh
python rarebits.py /tmp/logs18f 25 100 6
```

Lists every bit that changed at most 6 times between 25 s and 100 s, with the times and the DBC signal
it belongs to. Doing one action every few seconds while parked (lights, A/C, rear defogger, hazards,
doors) makes each action show up as a group of bits flipping at the same time.
