"""
Exercises — extend the simulation yourself.

Each function below is a test case. Run this file and every exercise reports
PASS/FAIL against an explicit expectation, rather than printing a value and
leaving you to eyeball it.

Run:  python exercises.py
      python exercises.py 3        (run only exercise 3)
"""

import sys
import time

import can

import ecu_server
import isotp_layer
from isotp_layer import now
from ecu_server import EcuServer
from tester_client import Tester, NegativeResponse, UdsError

PASS = 0
FAIL = 0
_channel = 0


def check(condition, description):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {description}")
    else:
        FAIL += 1
        print(f"  [FAIL] {description}")


def expect_nrc(fn, nrc, description):
    """Run fn and assert it raises exactly the expected negative response."""
    global PASS, FAIL
    try:
        fn()
        FAIL += 1
        print(f"  [FAIL] {description} — expected NRC 0x{nrc:02X}, got success")
    except NegativeResponse as e:
        if e.nrc == nrc:
            PASS += 1
            print(f"  [PASS] {description} — NRC 0x{nrc:02X}")
        else:
            FAIL += 1
            print(f"  [FAIL] {description} — expected 0x{nrc:02X}, got 0x{e.nrc:02X}")
    except UdsError as e:
        FAIL += 1
        print(f"  [FAIL] {description} — {e}")


def setup(trace=False, tester_cls=Tester, **ecu_kwargs):
    """Fresh ECU + tester on their own virtual channel.

    Each call uses a NEW channel name: python-can's virtual bus is global to
    the process, so reusing one name lets frames from a finished exercise leak
    into the next one.

    `tester_cls` builds the tester here rather than letting the caller attach a
    second one to the same bus — two IsoTpSockets reading one bus consume each
    other's frames, since bus.recv() hands a message to whoever asks first.
    """
    global _channel
    _channel += 1
    name = f"ex{_channel}"
    bus_ecu = can.interface.Bus(name, interface="virtual")
    bus_tst = can.interface.Bus(name, interface="virtual")
    isotp_layer.reset_trace_clock()
    ecu = EcuServer(bus_ecu, trace=trace, **ecu_kwargs)
    tst = tester_cls(bus_tst, trace=trace)
    time.sleep(0.2)
    return ecu, tst, bus_ecu, bus_tst


def teardown(ecu, tst, bus_ecu, bus_tst):
    """Stop both endpoints AND shut the buses down.

    Without the shutdown, python-can prints 'VirtualBus was not properly shut
    down' and the sockets stay registered on the channel.
    """
    tst.stop()
    ecu.stop()
    time.sleep(0.1)
    bus_ecu.shutdown()
    bus_tst.shutdown()


KEY = lambda seed: bytes((b ^ 0x5A) for b in seed)


# ======================================================================
# EXERCISE 1 — S3 session timeout
# ======================================================================
def ex1_session_timeout():
    """
    Half one: enter Extended, stay silent past S3, expect a fall back to
    Default. Half two: do it again but send TesterPresent every 2 s, and
    expect the session to be held.
    """
    ecu, tst, b1, b2 = setup()
    try:
        # ---- half one: silence lets the session lapse ----
        tst.session(0x03)
        check(tst.read_did(0xF186) == b"\x03", "entered Extended session")
        print(f"  going silent for {ecu_server.S3_TIMEOUT + 1:.0f} s...")
        time.sleep(ecu_server.S3_TIMEOUT + 1.0)
        check(tst.read_did(0xF186) == b"\x01",
              "silence past S3 falls back to Default")

        # ---- half two: TesterPresent holds it open ----
        tst.session(0x03)
        held_for = 8.0
        deadline = now() + held_for
        pings = 0
        while now() < deadline:
            time.sleep(2.0)
            tst.tester_present()
            pings += 1
        print(f"  sent {pings} TesterPresent over {held_for:.0f} s")
        check(tst.read_did(0xF186) == b"\x03",
              "TesterPresent every 2 s holds the session open")

        # TesterPresent goes out with the suppressPosResponse bit set, so the
        # ECU must stay silent — the ping alone held the session, no reply
        # traffic was involved.
        check(tst.tester_present(suppress=True) is None,
              "suppressed TesterPresent gets no response")
    finally:
        teardown(ecu, tst, b1, b2)


# ======================================================================
# EXERCISE 2 — security access lockout
# ======================================================================
def ex2_security_lockout():
    """
    Three wrong keys: NRC 0x35, 0x35, then 0x36. Immediately after, the delay
    penalty returns 0x37 — even for a plain seed request.
    """
    ecu, tst, b1, b2 = setup()
    try:
        tst.session(0x03)
        tst.session(0x02)

        expected = [0x35, 0x35, 0x36]
        for attempt, nrc in enumerate(expected, start=1):
            tst.request([0x27, 0x11])                       # seed
            expect_nrc(lambda: tst.request([0x27, 0x12, 0, 0, 0, 0]),
                       nrc, f"attempt {attempt}: wrong key")

        expect_nrc(lambda: tst.request([0x27, 0x11]),
                   0x37, "seed request during the delay penalty")

        # The penalty covers the key step too, not just the seed step.
        expect_nrc(lambda: tst.request([0x27, 0x12, 0, 0, 0, 0]),
                   0x37, "key attempt during the delay penalty")

        # Even a correct key is refused while the penalty stands — it is a
        # time penalty, not a bad-key counter.
        expect_nrc(lambda: tst.security_access(0x11, KEY),
                   0x37, "correct key also refused during the penalty")
        check(ecu.security_unlocked_level is None, "ECU stayed locked")
    finally:
        teardown(ecu, tst, b1, b2)


# ======================================================================
# EXERCISE 3 — block sequence counter wrap
# ======================================================================
def ex3_bsc_wrap():
    """
    Transfer more than 256 blocks and confirm the counter goes
    01 .. FF -> 00 -> 01, not back to 01.

    A tiny max_block_length keeps this quick: 4 payload bytes per block, so
    260 blocks is barely 1 KB of firmware.
    """
    # SID + BSC + 4 payload bytes
    ecu, tst, b1, b2 = setup(max_block_length=0x0006)
    try:
        tst.session(0x03)
        tst.session(0x02)
        tst.security_access(0x11, KEY)
        tst.routine(0x01, 0xFF00)                       # erase

        blocks = 260                                    # past the wrap
        payload_per_block = tst.request_download(0xA0000000, blocks * 4) - 2
        check(payload_per_block == 4, "block length excludes SID and BSC")

        firmware = bytes((i * 11) & 0xFF for i in range(blocks * 4))
        seen = []
        bsc = 1
        offset = 0
        while offset < len(firmware):
            tst.transfer_data(bsc, firmware[offset:offset + payload_per_block])
            seen.append(bsc)
            offset += payload_per_block
            bsc = (bsc + 1) & 0xFF

        check(len(seen) == blocks, f"transferred {blocks} blocks")
        check(seen[:3] == [0x01, 0x02, 0x03], "counter starts at 01")
        check(seen[254] == 0xFF, "block 255 carries counter FF")
        check(seen[255] == 0x00, "the block after FF carries 00, not 01")
        check(seen[256] == 0x01, "and then continues at 01")
        check(ecu.bytes_received == len(firmware),
              "ECU accepted every block across the wrap")

        # A counter that skips is still rejected, even right after the wrap.
        expect_nrc(lambda: tst.transfer_data((bsc + 5) & 0xFF, b"\x00" * 4),
                   0x73, "skipped counter still rejected after the wrap")

        tst.transfer_exit()
    finally:
        teardown(ecu, tst, b1, b2)


# ======================================================================
# EXERCISE 4 — the P2* accumulation bug
# ======================================================================
class BrokenTester(Tester):
    """A tester with the classic bug: it ACCUMULATES elapsed time across 0x78
    responses instead of restarting the timer on each one.

    Every individual wait here is legal. The total is what kills it — which is
    why the bug survives code review and only shows up against an ECU whose
    routine happens to run long.
    """

    def _wait_response(self, sid):
        # ONE deadline for the whole exchange. The correct implementation
        # gives each 0x78 a fresh P2* window instead.
        deadline = now() + self.p2
        extended = False
        self.pending_count = 0

        for _ in range(self.max_pending):
            remaining = deadline - now()
            if remaining <= 0:
                raise UdsError(f"timeout waiting for response to 0x{sid:02X}")
            resp = self.sock.recv(timeout=remaining)
            if resp is None:
                raise UdsError(f"timeout waiting for response to 0x{sid:02X}")

            if resp[0] == 0x7F and len(resp) >= 3:
                if resp[2] == 0x78:
                    self.pending_count += 1
                    if not extended:
                        # Budget stretched to P2* exactly ONCE, measured from
                        # the original request. Every later 0x78 eats into the
                        # same budget rather than renewing it.
                        deadline = deadline - self.p2 + self.p2_star
                        extended = True
                    continue
                raise NegativeResponse(resp[1], resp[2])

            if resp[0] != sid + 0x40:
                raise UdsError(f"unexpected response 0x{resp[0]:02X}")
            return resp

        raise UdsError("too many pending responses")


def ex4_pending_bug():
    """
    Run the same long erase against both testers. The correct one passes, the
    accumulating one raises a false timeout.

    40 pending responses at 160 ms is ~6.4 s — past the 5 s P2*, but every
    individual gap is well inside it.
    """
    pending = 40
    expected_s = pending * 0.16
    print(f"  erase sends {pending} x 0x78 at 160 ms = ~{expected_s:.1f} s "
          f"(P2* is 5.0 s per response)")

    # ---- the correct tester ----
    ecu, tst, b1, b2 = setup(erase_pending_count=pending)
    try:
        tst.max_pending = pending + 10
        tst.session(0x03)
        tst.session(0x02)
        tst.security_access(0x11, KEY)

        t0 = now()
        tst.routine(0x01, 0xFF00)
        elapsed = now() - t0
        print(f"  correct tester: completed in {elapsed:.1f} s "
              f"after {tst.pending_count} pending responses")
        check(elapsed > tst.p2_star,
              "the erase really did outlast a single P2* window")
        check(tst.pending_count == pending, "saw every pending response")

        # The ECU must not drop its own session while it is busy answering.
        check(ecu.session == ecu_server.SESSION_PROGRAMMING,
              "ECU held the session across the long routine")
        check(ecu.security_unlocked_level is not None,
              "ECU held the security unlock across the long routine")
    finally:
        teardown(ecu, tst, b1, b2)

    # ---- the broken tester ----
    ecu, broken, b1, b2 = setup(erase_pending_count=pending,
                                tester_cls=BrokenTester)
    try:
        broken.max_pending = pending + 10
        broken.session(0x03)
        broken.session(0x02)
        broken.security_access(0x11, KEY)

        t0 = now()
        try:
            broken.routine(0x01, 0xFF00)
            check(False, "broken tester should have timed out but did not")
        except UdsError as e:
            elapsed = now() - t0
            print(f"  broken tester:  gave up after {elapsed:.1f} s and "
                  f"{broken.pending_count} pending responses — {e}")
            check(True, "accumulating tester reports a false timeout")
            check(elapsed < expected_s,
                  "it failed BEFORE the ECU had finished — a false negative")
    finally:
        teardown(ecu, broken, b1, b2)


# ======================================================================
# EXERCISE 5 — Flow Control STmin
# ======================================================================
def ex5_stmin_effect():
    """
    Measure multi-frame read time at three STmin settings, then extrapolate to
    a 1 MB image.

    STmin is what the RECEIVER asks for in its Flow Control frame, so the
    tester sets the pace of the frames the ECU sends back.
    """
    ecu, tst, b1, b2 = setup()
    try:
        tst.session(0x03)

        did = 0xF1A0
        payload_len = len(tst.read_did(did))
        # First Frame carries 6 bytes, every Consecutive Frame carries 7.
        # +3 for the 0x62 SID and the echoed DID.
        cf_count = max(0, -(-(payload_len + 3 - 6) // 7))
        print(f"  DID 0x{did:04X} is {payload_len} bytes "
              f"-> {cf_count} consecutive frames per read")

        results = {}
        for st_min in (0x00, 0x0A, 0x14):
            tst.set_st_min(st_min)
            reads = 3
            t0 = now()
            for _ in range(reads):
                tst.read_did(did)
            per_read = (now() - t0) / reads
            results[st_min] = per_read
            print(f"  STmin 0x{st_min:02X} ({st_min:3d} ms): "
                  f"{per_read*1000:8.2f} ms per read")

        check(results[0x14] > results[0x00],
              "a larger STmin makes the same read slower")
        check(results[0x0A] > results[0x00],
              "STmin 0x0A is slower than back-to-back")

        # Cost of one gap, derived from the two extremes.
        measured_gap = (results[0x14] - results[0x00]) / max(cf_count, 1)
        print(f"  measured cost per CF gap at STmin 0x14: "
              f"{measured_gap*1000:.1f} ms (nominal 20 ms)")

        print("\n  Extrapolating to a 1 MB image at 7 bytes per consecutive frame:")
        frames_1mb = (1024 * 1024) // 7
        for st_min in (0x00, 0x0A, 0x14):
            seconds = frames_1mb * (st_min / 1000.0)
            print(f"    STmin 0x{st_min:02X}: {frames_1mb} frames x {st_min} ms "
                  f"= {seconds/60:6.1f} min of pure inter-frame delay")
        worst_minutes = frames_1mb * 0.020 / 60
        check(worst_minutes > 45,
              f"at STmin 0x14 a 1 MB image spends {worst_minutes:.0f} min "
              "purely on inter-frame delay")
        print("  This is why flashing specifications argue about STmin.")
    finally:
        teardown(ecu, tst, b1, b2)


# ======================================================================
# EXERCISE 6 — InputOutputControlByIdentifier (0x2F)
# ======================================================================
def ex6_add_io_control():
    """
    0x2F is implemented in ecu_server.py. This checks all four requirements:
    take control, release control, refuse while the vehicle is moving, and
    release by itself when the tester goes silent.
    """
    ecu, tst, b1, b2 = setup()
    did = 0x4101                                   # cooling fan duty cycle
    try:
        # ---- not available in the Default session ----
        expect_nrc(lambda: tst.io_control(did, 0x03, 0x64),
                   0x7F, "0x2F rejected in the Default session")

        tst.session(0x03)

        # ---- controlParameter 03: shortTermAdjustment ----
        resp = tst.io_control(did, 0x03, 0x64)
        check(resp[:4] == bytes([0x6F, 0x41, 0x01, 0x03]),
              "0x2F 03 echoes the DID and control parameter")
        check(ecu.io_control.get(did) == 0x64, "ECU holds the forced value")
        check(tst.read_did(did) == b"\x64", "the forced value reads back")

        # ---- controlParameter 00: returnControlToECU ----
        tst.io_control(did, 0x00)
        check(did not in ecu.io_control, "0x2F 00 releases control")
        check(tst.read_did(did) == b"\x00", "the output went back to default")

        # ---- refuse while the vehicle is moving ----
        ecu.vehicle_speed = 30
        expect_nrc(lambda: tst.io_control(did, 0x03, 0x64),
                   0x22, "control refused while the vehicle is moving")
        check(did not in ecu.io_control, "no control taken on the refusal")
        ecu.vehicle_speed = 0

        # ---- a DID that does not support IO control ----
        expect_nrc(lambda: tst.io_control(0xF190, 0x03, 0x01),
                   0x31, "0x2F on a non-controllable DID rejected")

        # ---- TesterPresent holds control open ----
        tst.io_control(did, 0x03, 0x50)
        hold_for = ecu_server.IO_CONTROL_TIMEOUT + 1.5
        deadline = now() + hold_for
        while now() < deadline:
            time.sleep(1.0)
            tst.tester_present()
        check(ecu.io_control.get(did) == 0x50,
              f"control held for {hold_for:.1f} s while pinging TesterPresent")

        # ---- silence releases it, without waiting for S3 ----
        print(f"  going silent for {ecu_server.IO_CONTROL_TIMEOUT + 1.0:.1f} s "
              f"(S3 is {ecu_server.S3_TIMEOUT:.0f} s, so the session survives)...")
        time.sleep(ecu_server.IO_CONTROL_TIMEOUT + 1.0)
        check(ecu.io_control == {},
              "ECU released control by itself after the tester went silent")
        check(ecu.session == ecu_server.SESSION_EXTENDED,
              "and did it without dropping the session — IO timeout < S3")
        check(tst.read_did(did) == b"\x00", "the output is back under ECU control")
    finally:
        teardown(ecu, tst, b1, b2)


# ======================================================================

EXERCISES = [
    ("EX1  session timeout", ex1_session_timeout),
    ("EX2  security lockout", ex2_security_lockout),
    ("EX3  BSC wrap", ex3_bsc_wrap),
    ("EX4  P2* pending handling", ex4_pending_bug),
    ("EX5  STmin effect", ex5_stmin_effect),
    ("EX6  IO control", ex6_add_io_control),
]


def main():
    global FAIL
    wanted = [a for a in sys.argv[1:] if a.isdigit()]
    selected = ([EXERCISES[int(n) - 1] for n in wanted if 1 <= int(n) <= len(EXERCISES)]
                if wanted else EXERCISES)

    for name, fn in selected:
        print(f"\n=== {name} " + "=" * max(0, 48 - len(name)))
        try:
            fn()
        except Exception as e:
            FAIL += 1
            print(f"  [FAIL] {name} raised {type(e).__name__}: {e}")
        time.sleep(0.3)

    print("\n" + "=" * 62)
    print(f"  RESULT   passed: {PASS}   failed: {FAIL}")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
