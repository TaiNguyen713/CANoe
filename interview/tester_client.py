"""
UDS tester (client).

The important part is wait_response(): it RESTARTS the timer on every
0x78 instead of accumulating elapsed time. Accumulating is the classic
implementation bug — each individual wait is legal, but the total crosses
the timeout and the test reports a false failure.
"""

import time

from isotp_layer import IsoTpSocket

P2_DEFAULT      = 0.050     # 50 ms
P2_STAR_DEFAULT = 5.000     # 5000 ms
MAX_PENDING     = 30        # guard against an ECU that never finishes


class UdsError(Exception):
    pass


class NegativeResponse(UdsError):
    def __init__(self, sid, nrc):
        self.sid = sid
        self.nrc = nrc
        super().__init__(f"NRC 0x{nrc:02X} for service 0x{sid:02X} "
                         f"({NRC_NAMES.get(nrc, 'unknown')})")


NRC_NAMES = {
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLength",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x73: "wrongBlockSequenceCounter",
    0x78: "responsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}


class Tester:
    def __init__(self, bus, tx_id=0x7E0, rx_id=0x7E8, trace=True):
        self.sock = IsoTpSocket(bus, tx_id=tx_id, rx_id=rx_id,
                                name="Tester", block_size=0, st_min=0x0A,
                                trace=trace)
        self.p2 = P2_DEFAULT
        self.p2_star = P2_STAR_DEFAULT
        self.pending_count = 0

    def request(self, payload, expect_response=True):
        self.sock.send(bytes(payload))
        if not expect_response:
            return None
        return self._wait_response(payload[0])

    def _wait_response(self, sid):
        timeout = self.p2
        self.pending_count = 0

        for _ in range(MAX_PENDING):
            resp = self.sock.recv(timeout=timeout)
            if resp is None:
                raise UdsError(f"timeout waiting for response to 0x{sid:02X}")

            if resp[0] == 0x7F and len(resp) >= 3:
                if resp[2] == 0x78:
                    # RESTART the timer. Do not accumulate.
                    self.pending_count += 1
                    timeout = self.p2_star
                    continue
                raise NegativeResponse(resp[1], resp[2])

            if resp[0] != sid + 0x40:
                raise UdsError(f"unexpected response 0x{resp[0]:02X}")
            return resp

        raise UdsError("too many pending responses")

    # ---- convenience wrappers ----

    def session(self, session_type):
        resp = self.request([0x10, session_type])
        if len(resp) >= 6:
            self.p2 = ((resp[2] << 8) | resp[3]) / 1000.0
            self.p2_star = ((resp[4] << 8) | resp[5]) * 10 / 1000.0
        return resp

    def read_did(self, did):
        resp = self.request([0x22, (did >> 8) & 0xFF, did & 0xFF])
        return resp[3:]

    def write_did(self, did, data):
        return self.request([0x2E, (did >> 8) & 0xFF, did & 0xFF] + list(data))

    def security_access(self, level, key_fn):
        seed_resp = self.request([0x27, level])
        seed = seed_resp[2:]
        if all(b == 0 for b in seed):
            return True                       # already unlocked
        key = key_fn(seed)
        self.request([0x27, level + 1] + list(key))
        return True

    def routine(self, sub, routine_id, data=b""):
        return self.request([0x31, sub,
                             (routine_id >> 8) & 0xFF, routine_id & 0xFF]
                            + list(data))

    def request_download(self, address, size):
        req = [0x34, 0x00, 0x44]
        req += list(address.to_bytes(4, "big"))
        req += list(size.to_bytes(4, "big"))
        resp = self.request(req)
        lfid = (resp[1] >> 4) & 0x0F
        return int.from_bytes(resp[2:2 + lfid], "big")

    def transfer_data(self, bsc, data):
        return self.request([0x36, bsc] + list(data))

    def transfer_exit(self):
        return self.request([0x37])

    def tester_present(self, suppress=True):
        return self.request([0x3E, 0x80 if suppress else 0x00],
                            expect_response=not suppress)

    def ecu_reset(self, reset_type=0x01):
        return self.request([0x11, reset_type])

    def stop(self):
        self.sock.stop()
