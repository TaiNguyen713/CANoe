# UDS Diagnostic Simulation

A UDS (ISO 14229) client and server running over a virtual CAN bus, with
ISO-TP (ISO 15765-2) segmentation implemented from scratch.

Built to practise the protocol behaviours that matter in system test:
response pending handling, security access lockout, block sequence counter
wrapping, and session timeout.

## Run

```bash
pip install python-can            # or: uv sync
python run_flashing.py            # full flashing sequence + negative tests
python run_flashing.py --quiet    # hide the frame trace
python exercises.py               # all six exercises
python exercises.py 3             # just exercise 3
```

The PyPI distribution is `python-can`; the import name `can` belongs to an
unrelated empty placeholder package.

No hardware and no vendor licence required — `python-can`'s virtual
interface carries the frames in process.

## Files

| File | Contents |
|---|---|
| `isotp_layer.py` | ISO-TP: Single/First/Consecutive/Flow Control frames, STmin, block size |
| `ecu_server.py` | Simulated ECU: 15 UDS services, session state machine, security access |
| `tester_client.py` | Tester: request/response with correct P2 and P2* handling |
| `run_flashing.py` | Full flashing sequence plus 8 negative test cases |
| `exercises.py` | Six exercises, each asserting PASS/FAIL |

## What the flashing sequence demonstrates

```
Phase A — pre-programming, still running the application
  10 03            enter Extended session
  22 F187/F189     read identification, verify the image matches this ECU
  31 01 0201       check programming preconditions
  85 02            disable DTC setting        <-- BEFORE leaving the app
  28 03 01         disable normal comms       <-- BEFORE leaving the app

Phase B — enter bootloader
  10 02            enter Programming session
  27 11 / 27 12    security access

Phase C — transfer
  31 01 FF00       erase memory (returns repeated 0x78)
  34               request download
  36 01, 36 02 ... transfer data, BSC wraps 01..FF -> 00 -> 01
  37               request transfer exit
  31 01 FF01       check programming dependencies

Phase D — post-programming
  11 01            ECU reset                  <-- FIRST, boots new software
  10 03            back to Extended
  28 00 01         restore communication
  85 01            restore DTC setting
  14 FF FF FF      clear DTCs from the flash process
  22 F189          verify the new software version
```

Two ordering points the simulation enforces:

**`0x85` and `0x28` must come before `0x10 02`.** Entering the programming
session stops the application messages immediately. If the network hasn't
been told beforehand, other nodes log lost-communication DTCs. The commands
only take effect while the ECU is still running the application.

**`0x11` reset must come before restoring communication and DTC setting.**
The ECU sits in the bootloader; only a reset boots the new image, and the
reset clears that state anyway.

## Behaviours worth studying

**Response pending (`0x78`).** The erase routine returns `0x78` four times
at 160 ms intervals before completing. `tester_client.py` restarts the
timeout on each one rather than accumulating elapsed time — accumulating is
the classic implementation bug that produces false timeouts even though every
individual wait is legal.

**Block sequence counter.** Wraps `01 → 02 → … → FF → 00 → 01`, not back to
`01`. Resending the same counter is treated as a legal retry; anything else
returns NRC `0x73`.

**maxNumberOfBlockLength.** The ECU reports `0x0402` = 1026, which includes
the SID and the BSC — so each `0x36` carries 1024 payload bytes, not 1026.

**Security access.** Seeds are random per request, three wrong keys trigger
NRC `0x36` followed by a delay penalty returning NRC `0x37`, and the unlock
is dropped on both session change and ECU reset.

**STmin.** Decoded from the Flow Control frame with both ranges: `00`–`7F`
in milliseconds, `F1`–`F9` in units of 100 microseconds. The receiver sets it,
so the tester dictates how fast the ECU may send — at `0x14` a 1 MB image
spends about 50 minutes on inter-frame delay alone.

**Which timer applies where.** P2 budgets the wait until a response *starts*
arriving. Once frames are flowing, the gap between them is N_Cr, not P2 —
otherwise a 515-byte multi-frame response dies against a 50 ms P2 while it is
still streaming in. Same class of mistake as accumulating P2* across `0x78`.

**S3 restarts when a request finishes, not when it arrives.** A routine that
answers `0x78` for six seconds is the tester waiting legally, not the tester
going quiet. Restarting the timer only on arrival makes the ECU drop its own
session — and the security unlock — in the middle of its own erase.

**Interval timing uses `perf_counter`, never `time.time()`.** On Windows
`time.time()` advances in 15.6 ms steps, which is coarser than the 50 ms P2
this code enforces and reports a 2 ms multi-frame read as exactly 0.0 ms.

## Negative test cases included

| Test | Expected |
|---|---|
| `0x36` before `0x34` | NRC `0x24` requestSequenceError |
| Unknown DID | NRC `0x31` requestOutOfRange |
| Programming session direct from Default | NRC `0x7E` |
| `0x34` while locked | NRC `0x33` securityAccessDenied |
| Wrong key | NRC `0x35` invalidKey |
| Out-of-order block sequence counter | NRC `0x73` |
| Write after reset | NRC `0x33` — unlock dropped |
| Silence past S3 | session falls back to Default |

## Sample trace

```
--- A1. Enter Extended session (0x10 03)
    0.201  7E0  02 10 03 55 55 55 55 55   [Tester]
    0.202  7E8  06 50 03 00 32 01 F4 55   [ECU]
```

The response carries the timing parameters: `00 32` is P2 = 50 ms in
milliseconds, `01 F4` is P2* = 5000 ms in units of 10 ms. Two different
units in the same message.

## Exercises

All six are implemented and assert their expectations — `python exercises.py`
reports 41 checks.

1. **Session timeout** — S3 fires after silence, and TesterPresent every 2 s
   holds the session open (sent with suppressPosResponse, so nothing replies)
2. **Security lockout** — the exact NRC at each attempt: `0x35`, `0x35`,
   `0x36`, then `0x37` for seed, key, and even a *correct* key: the lockout is
   a time penalty, not a bad-key counter
3. **Block sequence counter wrap** — 260 blocks confirm `FF → 00 → 01`, and a
   skipped counter is still rejected right after the wrap
4. **The P2\* accumulation bug** — `BrokenTester` accumulates elapsed time and
   reports a false timeout at 5.0 s against an erase that legally takes 6.4 s;
   the correct tester passes the same erase
5. **STmin** — measured at `0x00`, `0x0A` and `0x14` against a 512-byte DID,
   then extrapolated to a 1 MB image
6. **`0x2F` InputOutputControl** — take and release control, `NRC 0x22` while
   the vehicle is moving, and control released by the ECU itself after 3 s of
   silence, without waiting for S3 to drop the session
