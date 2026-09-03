# UDS Diagnostic Simulation

A UDS (ISO 14229) client and server running over a virtual CAN bus, with
ISO-TP (ISO 15765-2) segmentation implemented from scratch.

Built to practise the protocol behaviours that matter in system test:
response pending handling, security access lockout, block sequence counter
wrapping, and session timeout.

## Run

```bash
pip install python-can
python run_flashing.py            # full flashing sequence + negative tests
python run_flashing.py --quiet    # hide the frame trace
python exercises.py               # exercises to extend
```

No hardware and no vendor licence required — `python-can`'s virtual
interface carries the frames in process.

## Files

| File | Contents |
|---|---|
| `isotp_layer.py` | ISO-TP: Single/First/Consecutive/Flow Control frames, STmin, block size |
| `ecu_server.py` | Simulated ECU: 14 UDS services, session state machine, security access |
| `tester_client.py` | Tester: request/response with correct P2 and P2* handling |
| `run_flashing.py` | Full flashing sequence plus 8 negative test cases |
| `exercises.py` | Six exercises to extend the simulation |

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
in milliseconds, `F1`–`F9` in units of 100 microseconds.

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

1. Session timeout — prove S3 fires, then prove TesterPresent holds it off
2. Security lockout — assert the exact NRC at each attempt
3. Block sequence counter wrap past `0xFF`
4. Write a deliberately broken tester that accumulates timeout, and watch it fail
5. Measure how STmin changes transfer time, then extrapolate to a 1 MB image
6. Implement `0x2F` InputOutputControl, including releasing control when the
   tester goes silent
