"""
Exercises — extend the simulation yourself.

Each function below is a test case you write. Run this file, see what fails,
and add the missing behaviour to ecu_server.py or tester_client.py.

Run:  python exercises.py
"""

import time

import can

import isotp_layer
from ecu_server import EcuServer
from tester_client import Tester, NegativeResponse, UdsError


def setup(trace=False):
    bus_ecu = can.interface.Bus("ex", interface="virtual")
    bus_tst = can.interface.Bus("ex", interface="virtual")
    isotp_layer.reset_trace_clock()
    ecu = EcuServer(bus_ecu, trace=trace)
    tst = Tester(bus_tst, trace=trace)
    time.sleep(0.2)
    return ecu, tst


KEY = lambda seed: bytes((b ^ 0x5A) for b in seed)


# ======================================================================
# EXERCISE 1 — S3 session timeout
# ======================================================================
def ex1_session_timeout():
    """
    Enter Extended session, stay silent for 6 seconds, then check that the
    ECU has fallen back to Default.

    Then repeat with TesterPresent every 2 seconds and check the session
    is held.

    TODO: implement the second half.
    """
    ecu, tst = setup()
    tst.session(0x03)
    print("  entered Extended, going silent for 6 s...")
    time.sleep(6.0)
    session = tst.read_did(0xF186)
    print(f"  session after silence: 0x{session[0]:02X} "
          f"({'Default — correct' if session[0] == 1 else 'WRONG'})")

    # TODO: enter Extended again, send tester_present() every 2 s for 8 s,
    #       then verify F186 still reads 0x03.

    tst.stop(); ecu.stop()


# ======================================================================
# EXERCISE 2 — security access lockout
# ======================================================================
def ex2_security_lockout():
    """
    Send a wrong key three times. Expect NRC 0x35, 0x35, then 0x36.
    Then immediately try again and expect NRC 0x37.

    TODO: assert the exact NRC at each step instead of just printing.
    """
    ecu, tst = setup()
    tst.session(0x03)
    tst.session(0x02)

    for attempt in range(1, 4):
        tst.request([0x27, 0x11])
        try:
            tst.request([0x27, 0x12, 0x00, 0x00, 0x00, 0x00])
            print(f"  attempt {attempt}: unexpectedly accepted")
        except NegativeResponse as e:
            print(f"  attempt {attempt}: NRC 0x{e.nrc:02X}")

    try:
        tst.request([0x27, 0x11])
        print("  after lockout: seed request accepted (should be 0x37)")
    except NegativeResponse as e:
        print(f"  after lockout: NRC 0x{e.nrc:02X}")

    tst.stop(); ecu.stop()


# ======================================================================
# EXERCISE 3 — block sequence counter wrap
# ======================================================================
def ex3_bsc_wrap():
    """
    Transfer enough blocks that the BSC wraps past 0xFF.
    Confirm it goes 01 .. FF -> 00 -> 01, NOT back to 01.

    Hint: with 1024 bytes per block you need > 256 KB of firmware.
    Reduce MAX_BLOCK_LENGTH in ecu_server.py to make this fast.

    TODO: implement.
    """
    print("  TODO — see docstring")


# ======================================================================
# EXERCISE 4 — the P2* accumulation bug
# ======================================================================
def ex4_pending_bug():
    """
    Prove to yourself why accumulating time is wrong.

    Set ERASE_PENDING_COUNT in ecu_server.py to 40. Each 0x78 arrives
    160 ms apart, so the total is ~6.4 s — over the 5 s P2*.

    A tester that RESTARTS the timer passes.
    A tester that ACCUMULATES fails.

    Then write a broken_wait_response() that accumulates, and watch it fail.

    TODO: implement broken_wait_response and compare.
    """
    ecu, tst = setup()
    tst.session(0x03)
    tst.session(0x02)
    tst.security_access(0x11, KEY)

    t0 = time.time()
    tst.routine(0x01, 0xFF00)
    print(f"  erase completed in {(time.time()-t0)*1000:.0f} ms "
          f"after {tst.pending_count} pending responses")
    print("  a tester that accumulated elapsed time would have timed out")

    tst.stop(); ecu.stop()


# ======================================================================
# EXERCISE 5 — Flow Control STmin
# ======================================================================
def ex5_stmin_effect():
    """
    Measure how STmin changes multi-frame transfer time.

    Change st_min in the Tester's IsoTpSocket (tester_client.py) between
    0x00, 0x0A and 0x14, then read a long DID and measure.

    Then calculate: at 7 bytes per CF, how long would 1 MB take at each
    setting? This is the flashing-time question.

    TODO: implement the measurement loop.
    """
    ecu, tst = setup()
    tst.session(0x03)
    t0 = time.time()
    for _ in range(5):
        tst.read_did(0xF190)
    print(f"  5 x VIN read took {(time.time()-t0)*1000:.0f} ms")
    print("  now change st_min in tester_client.py and compare")
    tst.stop(); ecu.stop()


# ======================================================================
# EXERCISE 6 — add a new service
# ======================================================================
def ex6_add_io_control():
    """
    Implement 0x2F InputOutputControlByIdentifier in ecu_server.py.

    Requirements to satisfy:
      - controlParameter 03 (shortTermAdjustment) sets a value
      - controlParameter 00 (returnControlToECU) releases it
      - reject with NRC 0x22 if a simulated vehicle speed is above 0
      - if the tester goes silent for 3 s while control is active,
        the ECU must release control by itself

    That last one is the test case that separates senior candidates.

    TODO: implement in ecu_server.py, then write the test here.
    """
    print("  TODO — see docstring")


# ======================================================================

if __name__ == "__main__":
    for name, fn in [
        ("EX2  security lockout", ex2_security_lockout),
        ("EX4  P2* pending handling", ex4_pending_bug),
        ("EX5  STmin effect", ex5_stmin_effect),
        ("EX3  BSC wrap", ex3_bsc_wrap),
        ("EX6  IO control", ex6_add_io_control),
    ]:
        print(f"\n=== {name} " + "=" * (48 - len(name)))
        try:
            fn()
        except Exception as e:
            print(f"  error: {e}")
        time.sleep(0.3)

    print("\n=== EX1  session timeout (takes 6 s) " + "=" * 24)
    ex1_session_timeout()
