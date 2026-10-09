"""
Full ECU flashing sequence plus a set of negative test cases.

Run:  python run_flashing.py
      python run_flashing.py --quiet     (hide the frame trace)
"""

import sys
import time
import can

import isotp_layer
from isotp_layer import now
from ecu_server import EcuServer
from tester_client import Tester, NegativeResponse, UdsError

TRACE = "--quiet" not in sys.argv

PASS = 0
FAIL = 0


def step(title):
    isotp_layer.trace_print(f"\n--- {title}")


def check(condition, description):
    global PASS, FAIL
    if condition:
        PASS += 1
        isotp_layer.trace_print(f"  [PASS] {description}")
    else:
        FAIL += 1
        isotp_layer.trace_print(f"  [FAIL] {description}")


def expect_nrc(fn, nrc, description):
    """Run fn and assert it raises the expected negative response."""
    global PASS, FAIL
    try:
        fn()
        FAIL += 1
        isotp_layer.trace_print(f"  [FAIL] {description} — expected NRC 0x{nrc:02X}, got success")
    except NegativeResponse as e:
        if e.nrc == nrc:
            PASS += 1
            isotp_layer.trace_print(f"  [PASS] {description} — NRC 0x{nrc:02X}")
        else:
            FAIL += 1
            isotp_layer.trace_print(f"  [FAIL] {description} — expected 0x{nrc:02X}, got 0x{e.nrc:02X}")
    except UdsError as e:
        FAIL += 1
        isotp_layer.trace_print(f"  [FAIL] {description} — {e}")


def main():
    bus_ecu = can.interface.Bus("sim", interface="virtual", receive_own_messages=False)
    bus_tst = can.interface.Bus("sim", interface="virtual", receive_own_messages=False)

    isotp_layer.reset_trace_clock()

    ecu = EcuServer(bus_ecu, trace=TRACE)
    tst = Tester(bus_tst, trace=TRACE)
    time.sleep(0.2)

    key_fn = lambda seed: bytes((b ^ 0x5A) for b in seed)

    # ==================================================================
    # NEGATIVE TESTS FIRST — these are what interviewers ask about
    # ==================================================================

    step("Negative: TransferData before RequestDownload -> NRC 0x24")
    expect_nrc(lambda: tst.transfer_data(0x01, b"\x00" * 8),
               0x24, "0x36 without preceding 0x34")

    step("Negative: read a DID that does not exist -> NRC 0x31")
    expect_nrc(lambda: tst.read_did(0xF1FF), 0x31, "unknown DID rejected")

    step("Negative: enter Programming session directly from Default -> NRC 0x7E")
    expect_nrc(lambda: tst.session(0x02), 0x7E,
               "Programming session not reachable from Default")

    # ==================================================================
    # PHASE A — PRE-PROGRAMMING  (still running the application)
    # ==================================================================

    step("A1. Enter Extended session (0x10 03)")
    tst.session(0x03)
    check(tst.read_did(0xF186) == b"\x03", "F186 confirms Extended session")
    print(f"       P2 = {tst.p2*1000:.0f} ms, P2* = {tst.p2_star*1000:.0f} ms")

    step("A2. Read identification before flashing")
    part = tst.read_did(0xF187)
    version_before = tst.read_did(0xF189)
    vin = tst.read_did(0xF190)
    print(f"       Part number : {part.decode()}")
    print(f"       SW version  : {version_before.decode()}")
    print(f"       VIN         : {vin.decode()}")
    check(len(vin) == 17, "VIN is 17 characters")

    step("A3. Check programming preconditions (0x31 01 0201)")
    tst.routine(0x01, 0x0201)

    step("A4. Disable DTC setting (0x85 02) — BEFORE leaving the application")
    tst.request([0x85, 0x02])

    step("A5. Disable normal communication (0x28 03 01) — BEFORE leaving")
    tst.request([0x28, 0x03, 0x01])
    print("       Both must happen while the ECU still runs the application,")
    print("       otherwise other nodes log 'lost communication' DTCs.")

    # ==================================================================
    # PHASE B — ENTER BOOTLOADER
    # ==================================================================

    step("B1. Enter Programming session (0x10 02)")
    tst.session(0x02)
    check(tst.read_did(0xF186) == b"\x02", "F186 confirms Programming session")

    step("B2. Negative: RequestDownload before unlocking -> NRC 0x33")
    expect_nrc(lambda: tst.request_download(0xA0000000, 4096),
               0x33, "0x34 rejected while locked")

    step("B3. Negative: wrong key -> NRC 0x35")
    seed_resp = tst.request([0x27, 0x11])
    expect_nrc(lambda: tst.request([0x27, 0x12, 0x00, 0x00, 0x00, 0x00]),
               0x35, "invalid key rejected")

    step("B4. Security access with the correct key (0x27 11 / 12)")
    tst.security_access(0x11, key_fn)
    check(ecu.security_unlocked_level == 0x12, "ECU reports unlocked")

    # ==================================================================
    # PHASE C — TRANSFER
    # ==================================================================

    step("C1. Erase memory (0x31 01 FF00) — watch the repeated 0x78")
    t_start = now()
    tst.routine(0x01, 0xFF00)
    elapsed = now() - t_start
    print(f"       took {elapsed*1000:.0f} ms across "
          f"{tst.pending_count} pending responses")
    check(tst.pending_count > 0, "ECU sent responsePending during erase")
    check(elapsed > tst.p2,
          "total time exceeded P2 — a naive tester would have timed out here")

    step("C2. RequestDownload (0x34)")
    firmware = bytes((i * 7) & 0xFF for i in range(2500))
    max_block = tst.request_download(0xA0000000, len(firmware))
    payload_per_block = max_block - 2      # minus SID and BSC
    print(f"       maxNumberOfBlockLength = {max_block} "
          f"-> {payload_per_block} payload bytes per 0x36")
    check(payload_per_block == 1024, "block length excludes SID and BSC")

    step("C3. TransferData (0x36) with block sequence counter")
    bsc = 1
    offset = 0
    blocks = 0
    while offset < len(firmware):
        chunk = firmware[offset:offset + payload_per_block]
        tst.transfer_data(bsc, chunk)
        offset += len(chunk)
        bsc = (bsc + 1) & 0xFF          # 01..FF -> 00 -> 01
        blocks += 1
    print(f"       {blocks} blocks, {len(firmware)} bytes")
    check(ecu.bytes_received == len(firmware), "ECU received the whole image")

    step("C4. Negative: wrong block sequence counter -> NRC 0x73")
    expect_nrc(lambda: tst.transfer_data(0x99, b"\x00" * 16),
               0x73, "out-of-order BSC rejected")

    step("C5. RequestTransferExit (0x37)")
    tst.transfer_exit()

    step("C6. Check programming dependencies (0x31 01 FF01)")
    tst.routine(0x01, 0xFF01)

    # ==================================================================
    # PHASE D — POST-PROGRAMMING
    # ==================================================================

    step("D1. ECU reset (0x11 01) — FIRST, so it boots the new software")
    tst.ecu_reset(0x01)
    time.sleep(0.2)

    step("D2. Back to Extended session, then restore communication and DTCs")
    tst.session(0x03)
    tst.request([0x28, 0x00, 0x01])
    tst.request([0x85, 0x01])
    print("       Restoring before the reset would be pointless —")
    print("       the reset clears that state anyway.")

    step("D3. Clear DTCs generated during flashing (0x14 FF FF FF)")
    tst.request([0x14, 0xFF, 0xFF, 0xFF])

    step("D4. Verify the new software version")
    version_after = tst.read_did(0xF189)
    print(f"       before: {version_before.decode()}   "
          f"after: {version_after.decode()}")
    check(version_after != version_before, "software version changed")

    step("D5. Security is locked again after reset -> NRC 0x33")
    expect_nrc(lambda: tst.write_did(0xF187, b"TEST"),
               0x33, "write rejected after reset")

    # ==================================================================

    print("\n" + "=" * 62)
    print(f"  RESULT   passed: {PASS}   failed: {FAIL}")
    print("=" * 62)

    tst.stop()
    ecu.stop()
    time.sleep(0.2)
    # python-can warns 'VirtualBus was not properly shut down' otherwise, and
    # the endpoints stay registered on the channel.
    bus_ecu.shutdown()
    bus_tst.shutdown()
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
