"""
ISO-TP (ISO 15765-2) transport layer — implemented from scratch.

Purpose: understand segmentation by writing it, not by importing it.

PCI types:
    0x0  Single Frame        0L <data>
    0x1  First Frame         1L LL <6 bytes>
    0x2  Consecutive Frame   2N <7 bytes>      N = sequence 0..F, wraps 2F -> 20
    0x3  Flow Control        3S BS ST
         S: 0=ContinueToSend 1=Wait 2=Overflow
         BS: block size, 0 = send everything
         ST: separation time, 00-7F = ms, F1-F9 = 100-900 us
"""

import time
import threading

# Every interval and deadline in this project uses perf_counter, never
# time.time(). On Windows time.time() ticks in 15.6 ms steps — coarser than the
# 50 ms P2 this code is supposed to enforce, and enough to measure a 3 ms
# multi-frame read as exactly 0.0 ms. perf_counter resolves to ~100 ns.
# It is monotonic and has no defined epoch, so it is only ever used for
# differences, which is all any timeout here needs.
now = time.perf_counter

PADDING = 0x55

_print_lock = threading.Lock()


def trace_print(text):
    """Serialise trace output so the two endpoints don't interleave."""
    with _print_lock:
        print(text, flush=True)

FC_CONTINUE = 0x00
FC_WAIT     = 0x01
FC_OVERFLOW = 0x02

# N_Cr: the longest gap ISO 15765-2 allows between consecutive frames of one
# message. It is a separate budget from the UDS-layer P2 — see recv().
N_CR = 1.0


def st_min_to_seconds(st: int) -> float:
    """Decode STmin byte into seconds. Two ranges — a classic exam question."""
    if 0x00 <= st <= 0x7F:
        return st / 1000.0                # 0-127 milliseconds
    if 0xF1 <= st <= 0xF9:
        return (st - 0xF0) * 100 / 1e6    # 100-900 microseconds
    return 0.127                          # reserved -> treat as max


class IsoTpSocket:
    """
    One ISO-TP endpoint: sends on tx_id, receives on rx_id.

    Deliberately simple and synchronous so the frame flow stays readable
    in the trace output.
    """

    def __init__(self, bus, tx_id, rx_id, name="", block_size=0, st_min=0x0A,
                 trace=True):
        self.bus = bus
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.name = name
        self.block_size = block_size    # what we request when WE receive
        self.st_min = st_min            # what we request when WE receive
        self.trace = trace

        self._rx_queue = []
        self._rx_lock = threading.Condition()
        self._fc_event = threading.Event()
        self._fc_data = None
        self._running = True

        self._rx_buffer = bytearray()
        self._rx_expected = 0
        self._rx_seq = 0
        self._rx_activity = 0.0     # when a frame of the in-progress message landed

        self._thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._thread.start()

    # ---------- low level ----------

    def _send_frame(self, data):
        payload = bytes(data) + bytes([PADDING] * (8 - len(data)))
        msg = __import__("can").Message(
            arbitration_id=self.tx_id, data=payload, is_extended_id=False
        )
        self.bus.send(msg)
        if self.trace:
            trace_print(f"  {now() - T0:7.3f}  {self.tx_id:03X}  "
                        f"{' '.join(f'{b:02X}' for b in payload)}"
                        f"   [{self.name}]")

    # ---------- receive side ----------

    def _rx_loop(self):
        while self._running:
            msg = self.bus.recv(timeout=0.05)
            if msg is None or msg.arbitration_id != self.rx_id:
                continue
            self._handle_frame(bytes(msg.data))

    def _handle_frame(self, data):
        pci_type = (data[0] >> 4) & 0x0F

        if pci_type == 0x0:                                  # Single Frame
            length = data[0] & 0x0F
            self._deliver(data[1:1 + length])

        elif pci_type == 0x1:                                # First Frame
            self._rx_expected = ((data[0] & 0x0F) << 8) | data[1]
            self._rx_buffer = bytearray(data[2:8])
            self._rx_seq = 1
            self._rx_activity = now()
            # answer with Flow Control
            self._send_frame([0x30 | FC_CONTINUE, self.block_size, self.st_min])

        elif pci_type == 0x2:                                # Consecutive Frame
            seq = data[0] & 0x0F
            if seq != (self._rx_seq & 0x0F):
                trace_print(f"  !! {self.name}: wrong CF sequence, "
                            f"expected {self._rx_seq & 0x0F:X} got {seq:X}")
                self._rx_buffer = bytearray()
                self._rx_expected = 0
                return
            self._rx_seq += 1
            self._rx_activity = now()
            self._rx_buffer += data[1:8]
            if len(self._rx_buffer) >= self._rx_expected:
                self._deliver(bytes(self._rx_buffer[:self._rx_expected]))
                self._rx_buffer = bytearray()
                self._rx_expected = 0

        elif pci_type == 0x3:                                # Flow Control
            self._fc_data = (data[0] & 0x0F, data[1], data[2])
            self._fc_event.set()

    def _deliver(self, payload):
        with self._rx_lock:
            self._rx_queue.append(bytes(payload))
            self._rx_lock.notify_all()

    def recv(self, timeout=1.0):
        """Return one complete UDS payload, or None on timeout.

        `timeout` budgets the wait until the message STARTS arriving — that is
        the P2 the UDS layer cares about. Once frames are flowing, the gap
        between them is governed by N_Cr instead, so a long multi-frame
        response is not killed by a 50 ms P2 while it is still streaming in.
        Applying P2 to full reassembly is the same class of mistake as
        accumulating it across 0x78 responses: the timer is being measured at
        the wrong boundary.
        """
        deadline = now() + timeout
        with self._rx_lock:
            while not self._rx_queue:
                if self._rx_expected and self._rx_activity:
                    deadline = max(deadline, self._rx_activity + N_CR)
                remaining = deadline - now()
                if remaining <= 0:
                    return None
                # Capped so the extension above is re-evaluated as frames land;
                # _deliver() notifies, but a mid-message frame does not.
                self._rx_lock.wait(min(remaining, 0.05))
            return self._rx_queue.pop(0)

    # ---------- transmit side ----------

    def send(self, payload):
        payload = bytes(payload)

        if len(payload) <= 7:
            self._send_frame([len(payload)] + list(payload))
            return True

        # First Frame
        self._fc_event.clear()
        self._send_frame([0x10 | ((len(payload) >> 8) & 0x0F),
                          len(payload) & 0xFF] + list(payload[0:6]))

        # wait for Flow Control (N_Bs, typically 1000 ms)
        if not self._fc_event.wait(1.0):
            print(f"  !! {self.name}: N_Bs timeout — no Flow Control received")
            return False

        fs, bs, st = self._fc_data
        if fs == FC_OVERFLOW:
            print(f"  !! {self.name}: receiver reported overflow, aborting")
            return False

        gap = st_min_to_seconds(st)
        index = 6
        seq = 1
        sent_in_block = 0

        while index < len(payload):
            chunk = payload[index:index + 7]
            self._send_frame([0x20 | (seq & 0x0F)] + list(chunk))
            index += 7
            seq += 1                      # wraps naturally via & 0x0F: 2F -> 20
            sent_in_block += 1
            if index < len(payload):
                time.sleep(gap)
            if bs and sent_in_block >= bs and index < len(payload):
                self._fc_event.clear()
                if not self._fc_event.wait(1.0):
                    print(f"  !! {self.name}: N_Bs timeout mid-block")
                    return False
                fs, bs, st = self._fc_data
                gap = st_min_to_seconds(st)
                sent_in_block = 0
        return True

    def stop(self):
        """Stop the receive loop and wait for it to exit.

        The caller usually shuts the bus down straight after, and a thread
        still sitting in bus.recv() would raise on a closed bus.
        """
        self._running = False
        self._thread.join(timeout=1.0)


T0 = now()


def reset_trace_clock():
    global T0
    T0 = now()
