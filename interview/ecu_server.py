"""
Simulated ECU (UDS server).

Implements enough of ISO 14229 to exercise a full flashing sequence,
including the behaviours that trip up real test scripts:
  - NRC 0x78 repeated during the erase routine
  - security access with attempt counter and delay penalty
  - block sequence counter wrap 01..FF -> 00 -> 01
  - session timeout (S3) falling back to Default
"""

import time
import threading

from isotp_layer import IsoTpSocket

# ---- sessions ----
SESSION_DEFAULT     = 0x01
SESSION_PROGRAMMING = 0x02
SESSION_EXTENDED    = 0x03

# ---- NRC ----
NRC_SERVICE_NOT_SUPPORTED          = 0x11
NRC_SUBFUNCTION_NOT_SUPPORTED      = 0x12
NRC_INCORRECT_LENGTH               = 0x13
NRC_CONDITIONS_NOT_CORRECT         = 0x22
NRC_REQUEST_SEQUENCE_ERROR         = 0x24
NRC_REQUEST_OUT_OF_RANGE           = 0x31
NRC_SECURITY_ACCESS_DENIED         = 0x33
NRC_INVALID_KEY                    = 0x35
NRC_EXCEED_ATTEMPTS                = 0x36
NRC_TIME_DELAY_NOT_EXPIRED         = 0x37
NRC_WRONG_BLOCK_SEQUENCE_COUNTER   = 0x73
NRC_RESPONSE_PENDING               = 0x78
NRC_SUBFUNC_NOT_SUPPORTED_SESSION  = 0x7E
NRC_SERVICE_NOT_SUPPORTED_SESSION  = 0x7F

S3_TIMEOUT = 5.0          # session timeout, seconds
MAX_BLOCK_LENGTH = 0x0402 # 1026 = SID + BSC + 1024 payload bytes
ERASE_PENDING_COUNT = 4   # how many 0x78 before the erase finishes


class EcuServer:
    def __init__(self, bus, rx_id=0x7E0, tx_id=0x7E8, trace=True):
        self.sock = IsoTpSocket(bus, tx_id=tx_id, rx_id=rx_id,
                                name="ECU", block_size=0, st_min=0x0A,
                                trace=trace)
        self.running = True

        self.session = SESSION_DEFAULT
        self.last_request_time = time.time()

        self.security_unlocked_level = None
        self.pending_seed = None
        self.failed_attempts = 0
        self.locked_until = 0.0

        self.download_active = False
        self.expected_bsc = 1
        self.bytes_received = 0
        self.download_size = 0
        self.memory_erased = False

        self.dids = {
            0xF186: bytes([SESSION_DEFAULT]),
            0xF187: b"1K0907115AA",
            0xF189: b"SW_V1.02",
            0xF18C: b"SN0012345678",
            0xF190: b"KMHJ281BUNA123456",      # VIN, 17 chars
            0xF195: b"SUP_V2.10",
        }

        self.dtcs = {
            0x123401: 0x2F,     # confirmed + pending + testFailed
            0xC10A87: 0x08,     # confirmed only
        }

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------

    def _loop(self):
        while self.running:
            req = self.sock.recv(timeout=0.2)

            # S3 session timeout — falls back to Default if the tester goes quiet
            if (self.session != SESSION_DEFAULT
                    and time.time() - self.last_request_time > S3_TIMEOUT):
                print("  ** ECU: S3 timeout, falling back to Default session")
                self.session = SESSION_DEFAULT
                self.dids[0xF186] = bytes([SESSION_DEFAULT])
                self.security_unlocked_level = None

            if req is None:
                continue

            self.last_request_time = time.time()
            self._dispatch(req)

    def _dispatch(self, req):
        sid = req[0]
        handler = {
            0x10: self._session_control,
            0x11: self._ecu_reset,
            0x14: self._clear_dtc,
            0x19: self._read_dtc,
            0x22: self._read_did,
            0x27: self._security_access,
            0x28: self._comm_control,
            0x2E: self._write_did,
            0x31: self._routine_control,
            0x34: self._request_download,
            0x36: self._transfer_data,
            0x37: self._transfer_exit,
            0x3E: self._tester_present,
            0x85: self._control_dtc_setting,
        }.get(sid)

        if handler is None:
            return self._nrc(sid, NRC_SERVICE_NOT_SUPPORTED)
        handler(req)

    # ------------------------------------------------------------------
    # helpers

    def _positive(self, data):
        self.sock.send(bytes(data))

    def _nrc(self, sid, code):
        self.sock.send(bytes([0x7F, sid, code]))

    def _suppress(self, sub):
        return bool(sub & 0x80)

    # ------------------------------------------------------------------
    # services

    def _session_control(self, req):
        if len(req) != 2:
            return self._nrc(0x10, NRC_INCORRECT_LENGTH)
        sub = req[1] & 0x7F

        if sub not in (SESSION_DEFAULT, SESSION_PROGRAMMING, SESSION_EXTENDED):
            return self._nrc(0x10, NRC_SUBFUNCTION_NOT_SUPPORTED)

        # Programming session is only reachable from Extended
        if sub == SESSION_PROGRAMMING and self.session != SESSION_EXTENDED:
            return self._nrc(0x10, NRC_SUBFUNC_NOT_SUPPORTED_SESSION)

        self.session = sub
        self.dids[0xF186] = bytes([sub])
        # changing session drops security — many OEMs behave this way
        self.security_unlocked_level = None

        if self._suppress(req[1]):
            return
        # P2 = 50 ms (unit 1 ms), P2* = 5000 ms (unit 10 ms)
        self._positive([0x50, sub, 0x00, 0x32, 0x01, 0xF4])

    def _ecu_reset(self, req):
        if len(req) != 2:
            return self._nrc(0x11, NRC_INCORRECT_LENGTH)
        self._positive([0x51, req[1] & 0x7F])
        time.sleep(0.05)
        print("  ** ECU: reset — all state cleared")
        self.session = SESSION_DEFAULT
        self.dids[0xF186] = bytes([SESSION_DEFAULT])
        self.security_unlocked_level = None
        self.download_active = False
        self.memory_erased = False

    def _tester_present(self, req):
        if self._suppress(req[1] if len(req) > 1 else 0):
            return
        self._positive([0x7E, 0x00])

    def _read_did(self, req):
        if len(req) < 3 or len(req) % 2 == 0:
            return self._nrc(0x22, NRC_INCORRECT_LENGTH)
        out = bytearray([0x62])
        for i in range(1, len(req), 2):
            did = (req[i] << 8) | req[i + 1]
            if did not in self.dids:
                return self._nrc(0x22, NRC_REQUEST_OUT_OF_RANGE)
            out += bytes([req[i], req[i + 1]]) + self.dids[did]
        self._positive(out)

    def _write_did(self, req):
        if self.security_unlocked_level is None:
            return self._nrc(0x2E, NRC_SECURITY_ACCESS_DENIED)
        if len(req) < 4:
            return self._nrc(0x2E, NRC_INCORRECT_LENGTH)
        did = (req[1] << 8) | req[2]
        if did not in self.dids:
            return self._nrc(0x2E, NRC_REQUEST_OUT_OF_RANGE)
        self.dids[did] = bytes(req[3:])
        self._positive([0x6E, req[1], req[2]])

    def _security_access(self, req):
        if len(req) < 2:
            return self._nrc(0x27, NRC_INCORRECT_LENGTH)
        sub = req[1]

        if time.time() < self.locked_until:
            return self._nrc(0x27, NRC_TIME_DELAY_NOT_EXPIRED)

        if sub % 2 == 1:                                  # requestSeed
            if self.security_unlocked_level == sub + 1:
                return self._positive([0x67, sub, 0, 0, 0, 0])  # already unlocked
            import os
            self.pending_seed = os.urandom(4)
            self.pending_level = sub
            return self._positive([0x67, sub] + list(self.pending_seed))

        # sendKey
        if self.pending_seed is None:
            return self._nrc(0x27, NRC_REQUEST_SEQUENCE_ERROR)
        expected = self.compute_key(self.pending_seed)
        if bytes(req[2:]) != expected:
            self.failed_attempts += 1
            if self.failed_attempts >= 3:
                self.locked_until = time.time() + 10.0
                self.failed_attempts = 0
                return self._nrc(0x27, NRC_EXCEED_ATTEMPTS)
            return self._nrc(0x27, NRC_INVALID_KEY)

        self.failed_attempts = 0
        self.security_unlocked_level = sub
        self.pending_seed = None
        self._positive([0x67, sub])

    @staticmethod
    def compute_key(seed: bytes) -> bytes:
        """Toy seed-key algorithm. Real OEM algorithms are secret."""
        return bytes((b ^ 0x5A) for b in seed)

    def _comm_control(self, req):
        if len(req) != 3:
            return self._nrc(0x28, NRC_INCORRECT_LENGTH)
        self._positive([0x68, req[1] & 0x7F])

    def _control_dtc_setting(self, req):
        if len(req) != 2:
            return self._nrc(0x85, NRC_INCORRECT_LENGTH)
        self._positive([0xC5, req[1] & 0x7F])

    def _clear_dtc(self, req):
        if len(req) != 4:
            return self._nrc(0x14, NRC_INCORRECT_LENGTH)
        self.dtcs.clear()
        self._positive([0x54])

    def _read_dtc(self, req):
        if len(req) < 2:
            return self._nrc(0x19, NRC_INCORRECT_LENGTH)
        if req[1] != 0x02:
            return self._nrc(0x19, NRC_SUBFUNCTION_NOT_SUPPORTED)
        mask = req[2] if len(req) > 2 else 0xFF
        out = bytearray([0x59, 0x02, 0xFF])
        for dtc, status in self.dtcs.items():
            if status & mask:
                out += bytes([(dtc >> 16) & 0xFF, (dtc >> 8) & 0xFF,
                              dtc & 0xFF, status])
        self._positive(out)

    def _routine_control(self, req):
        if len(req) < 4:
            return self._nrc(0x31, NRC_INCORRECT_LENGTH)
        sub = req[1]
        routine = (req[2] << 8) | req[3]

        if routine == 0xFF00:                             # EraseMemory
            if self.session != SESSION_PROGRAMMING:
                return self._nrc(0x31, NRC_SERVICE_NOT_SUPPORTED_SESSION)
            if self.security_unlocked_level is None:
                return self._nrc(0x31, NRC_SECURITY_ACCESS_DENIED)
            # This is the part that breaks naive test scripts:
            # repeated 0x78 while the erase runs.
            for _ in range(ERASE_PENDING_COUNT):
                self._nrc(0x31, NRC_RESPONSE_PENDING)
                time.sleep(0.16)
            self.memory_erased = True
            return self._positive([0x71, sub, req[2], req[3], 0x00])

        if routine == 0xFF01:                             # CheckDependencies
            return self._positive([0x71, sub, req[2], req[3], 0x00])

        if routine == 0x0201:                             # CheckPreconditions
            return self._positive([0x71, sub, req[2], req[3], 0x00])

        return self._nrc(0x31, NRC_REQUEST_OUT_OF_RANGE)

    def _request_download(self, req):
        if self.session != SESSION_PROGRAMMING:
            return self._nrc(0x34, NRC_SERVICE_NOT_SUPPORTED_SESSION)
        if self.security_unlocked_level is None:
            return self._nrc(0x34, NRC_SECURITY_ACCESS_DENIED)
        if not self.memory_erased:
            return self._nrc(0x34, NRC_REQUEST_SEQUENCE_ERROR)
        if len(req) < 4:
            return self._nrc(0x34, NRC_INCORRECT_LENGTH)

        alfid = req[2]
        addr_len = alfid & 0x0F
        size_len = (alfid >> 4) & 0x0F
        if len(req) != 3 + addr_len + size_len:
            return self._nrc(0x34, NRC_INCORRECT_LENGTH)

        size = int.from_bytes(req[3 + addr_len:3 + addr_len + size_len], "big")
        self.download_active = True
        self.download_size = size
        self.bytes_received = 0
        self.expected_bsc = 1
        self._positive([0x74, 0x20,
                        (MAX_BLOCK_LENGTH >> 8) & 0xFF, MAX_BLOCK_LENGTH & 0xFF])

    def _transfer_data(self, req):
        if not self.download_active:
            return self._nrc(0x36, NRC_REQUEST_SEQUENCE_ERROR)
        if len(req) < 2:
            return self._nrc(0x36, NRC_INCORRECT_LENGTH)

        bsc = req[1]
        if bsc != self.expected_bsc:
            # resending the same BSC is a legal retry, anything else is an error
            if bsc == ((self.expected_bsc - 1) & 0xFF):
                return self._positive([0x76, bsc])
            return self._nrc(0x36, NRC_WRONG_BLOCK_SEQUENCE_COUNTER)

        data = req[2:]
        if self.bytes_received + len(data) > self.download_size:
            return self._nrc(0x36, NRC_REQUEST_OUT_OF_RANGE)

        self.bytes_received += len(data)
        # 01 -> 02 -> ... -> FF -> 00 -> 01   (wraps to 00, not back to 01)
        self.expected_bsc = (self.expected_bsc + 1) & 0xFF
        self._positive([0x76, bsc])

    def _transfer_exit(self, req):
        if not self.download_active:
            return self._nrc(0x37, NRC_REQUEST_SEQUENCE_ERROR)
        self.download_active = False
        self.dids[0xF189] = b"SW_V2.00"       # new software after flashing
        self._positive([0x77])

    def stop(self):
        self.running = False
        self.sock.stop()
