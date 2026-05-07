#!/usr/bin/env python3
"""
LiteX SFL loader over CSR-based UART (RemoteClient).

Why this exists:
- `litex_term --kernel` is designed for real serial ports and can be unreliable/very slow when
  tunneled through Etherbone + crossover UART (it uses a PTY bridge that does not apply TX flow-control).
- This script talks directly to the CSR UART registers with TXFULL/RXEMPTY polling.

It implements the subset needed to load a single binary and jump to it:
- Wait for BIOS SFL magic request: "sL5DdSMmkekro\n"
- Send magic ack:               "z6IHG7cYDID6o\n"
- Send LOAD frames with CRC16 and wait for 'K' acks
- Send JUMP frame and wait for ack
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass

from litex import RemoteClient


SFL_MAGIC_REQ = b"sL5DdSMmkekro\n"
SFL_MAGIC_ACK = b"z6IHG7cYDID6o\n"

SFL_PROMPT_REQ = b"F7:    boot from serial\n"
SFL_PROMPT_ACK = b"\x06"

SFL_CMD_LOAD = b"\x01"
SFL_CMD_JUMP = b"\x02"

SFL_ACK_SUCCESS = b"K"
SFL_ACK_CRCERROR = b"C"
SFL_ACK_ERROR = b"E"

SFL_PAYLOAD_MAX = 255


CRC16_TABLE = [
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7,
    0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF,
    0x1231, 0x0210, 0x3273, 0x2252, 0x52B5, 0x4294, 0x72F7, 0x62D6,
    0x9339, 0x8318, 0xB37B, 0xA35A, 0xD3BD, 0xC39C, 0xF3FF, 0xE3DE,
    0x2462, 0x3443, 0x0420, 0x1401, 0x64E6, 0x74C7, 0x44A4, 0x5485,
    0xA56A, 0xB54B, 0x8528, 0x9509, 0xE5EE, 0xF5CF, 0xC5AC, 0xD58D,
    0x3653, 0x2672, 0x1611, 0x0630, 0x76D7, 0x66F6, 0x5695, 0x46B4,
    0xB75B, 0xA77A, 0x9719, 0x8738, 0xF7DF, 0xE7FE, 0xD79D, 0xC7BC,
    0x48C4, 0x58E5, 0x6886, 0x78A7, 0x0840, 0x1861, 0x2802, 0x3823,
    0xC9CC, 0xD9ED, 0xE98E, 0xF9AF, 0x8948, 0x9969, 0xA90A, 0xB92B,
    0x5AF5, 0x4AD4, 0x7AB7, 0x6A96, 0x1A71, 0x0A50, 0x3A33, 0x2A12,
    0xDBFD, 0xCBDC, 0xFBBF, 0xEB9E, 0x9B79, 0x8B58, 0xBB3B, 0xAB1A,
    0x6CA6, 0x7C87, 0x4CE4, 0x5CC5, 0x2C22, 0x3C03, 0x0C60, 0x1C41,
    0xEDAE, 0xFD8F, 0xCDEC, 0xDDCD, 0xAD2A, 0xBD0B, 0x8D68, 0x9D49,
    0x7E97, 0x6EB6, 0x5ED5, 0x4EF4, 0x3E13, 0x2E32, 0x1E51, 0x0E70,
    0xFF9F, 0xEFBE, 0xDFDD, 0xCFFC, 0xBF1B, 0xAF3A, 0x9F59, 0x8F78,
    0x9188, 0x81A9, 0xB1CA, 0xA1EB, 0xD10C, 0xC12D, 0xF14E, 0xE16F,
    0x1080, 0x00A1, 0x30C2, 0x20E3, 0x5004, 0x4025, 0x7046, 0x6067,
    0x83B9, 0x9398, 0xA3FB, 0xB3DA, 0xC33D, 0xD31C, 0xE37F, 0xF35E,
    0x02B1, 0x1290, 0x22F3, 0x32D2, 0x4235, 0x5214, 0x6277, 0x7256,
    0xB5EA, 0xA5CB, 0x95A8, 0x8589, 0xF56E, 0xE54F, 0xD52C, 0xC50D,
    0x34E2, 0x24C3, 0x14A0, 0x0481, 0x7466, 0x6447, 0x5424, 0x4405,
    0xA7DB, 0xB7FA, 0x8799, 0x97B8, 0xE75F, 0xF77E, 0xC71D, 0xD73C,
    0x26D3, 0x36F2, 0x0691, 0x16B0, 0x6657, 0x7676, 0x4615, 0x5634,
    0xD94C, 0xC96D, 0xF90E, 0xE92F, 0x99C8, 0x89E9, 0xB98A, 0xA9AB,
    0x5844, 0x4865, 0x7806, 0x6827, 0x18C0, 0x08E1, 0x3882, 0x28A3,
    0xCB7D, 0xDB5C, 0xEB3F, 0xFB1E, 0x8BF9, 0x9BD8, 0xABBB, 0xBB9A,
    0x4A75, 0x5A54, 0x6A37, 0x7A16, 0x0AF1, 0x1AD0, 0x2AB3, 0x3A92,
    0xFD2E, 0xED0F, 0xDD6C, 0xCD4D, 0xBDAA, 0xAD8B, 0x9DE8, 0x8DC9,
    0x7C26, 0x6C07, 0x5C64, 0x4C45, 0x3CA2, 0x2C83, 0x1CE0, 0x0CC1,
    0xEF1F, 0xFF3E, 0xCF5D, 0xDF7C, 0xAF9B, 0xBFBA, 0x8FD9, 0x9FF8,
    0x6E17, 0x7E36, 0x4E55, 0x5E74, 0x2E93, 0x3EB2, 0x0ED1, 0x1EF0,
]


def crc16(data: bytes) -> int:
    crc = 0
    for d in data:
        crc = CRC16_TABLE[((crc >> 8) ^ d) & 0xFF] ^ ((crc << 8) & 0xFFFF_FFFF)
    return crc & 0xFFFF


@dataclass
class CSRUART:
    rxtx: any
    txfull: any
    rxempty: any

    def write_byte(self, b: int, timeout_s: float = 1.0, post_delay_s: float = 0.0) -> None:
        deadline = time.time() + timeout_s
        while self.txfull.read():
            if time.time() > deadline:
                raise TimeoutError("TX full timeout")
            time.sleep(0.0005)
        self.rxtx.write(b & 0xFF)
        if post_delay_s:
            time.sleep(post_delay_s)

    def read_byte(self, timeout_s: float = 1.0) -> int:
        deadline = time.time() + timeout_s
        while self.rxempty.read():
            if time.time() > deadline:
                raise TimeoutError("RX empty timeout")
            time.sleep(0.0005)
        return int(self.rxtx.read() & 0xFF)

    def write(self, data: bytes, post_delay_s: float = 0.0) -> None:
        for ch in data:
            self.write_byte(ch, post_delay_s=post_delay_s)

    def read_exact(self, n: int, timeout_s: float = 1.0) -> bytes:
        out = bytearray()
        for _ in range(n):
            out.append(self.read_byte(timeout_s=timeout_s))
        return bytes(out)

    def drain(self, max_bytes: int = 4096) -> bytes:
        """Best-effort drain of currently buffered RX bytes."""
        out = bytearray()
        for _ in range(max_bytes):
            if self.rxempty.read():
                break
            out.append(int(self.rxtx.read() & 0xFF))
        return bytes(out)


def get_uart(bus: RemoteClient, name: str) -> CSRUART:
    # litex_term's CrossoverUART maps "<name>_rxtx", "<name>_txfull", "<name>_rxempty"
    def reg(suffix: str):
        return getattr(bus.regs, f"{name}_{suffix}")

    return CSRUART(
        rxtx=reg("rxtx"),
        txfull=reg("txfull"),
        rxempty=reg("rxempty"),
    )


def sfl_send_frame(uart: CSRUART, cmd: bytes, payload: bytes, ack_timeout_s: float, tx_post_delay_s: float, frame_post_delay_s: float) -> None:
    if len(payload) > SFL_PAYLOAD_MAX:
        raise ValueError("payload too large")
    pkt = bytes([len(payload)]) + crc16(cmd + payload).to_bytes(2, "big") + cmd + payload
    uart.write(pkt, post_delay_s=tx_post_delay_s)
    # Give BIOS some time to parse/process on slow links.
    time.sleep(frame_post_delay_s)

    # On some transports the console stream can interleave with SFL acks.
    # Keep reading until we see a known ack byte or we time out.
    deadline = time.time() + ack_timeout_s
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError("ack wait timeout")
        try:
            b = bytes([uart.read_byte(timeout_s=max(0.001, remaining))])
        except TimeoutError:
            # No bytes yet.
            continue
        if b == SFL_ACK_SUCCESS:
            return
        if b == SFL_ACK_CRCERROR:
            raise RuntimeError("device reported CRC error")
        if b == SFL_ACK_ERROR:
            raise RuntimeError("device reported generic error")
        # Ignore unrelated bytes (console output).


def main() -> int:
    p = argparse.ArgumentParser(description="Load a binary over LiteX BIOS SFL using CSR UART (Etherbone/crossover).")
    p.add_argument("--csr-csv", default="scripts/csr.csv", help="Path to csr.csv matching the bitstream.")
    p.add_argument("--host", default="localhost", help="litex_server host (default: localhost).")
    p.add_argument("--base-address", default=None, help="CSR base override (rare).")
    p.add_argument("--uart-name", default="uart_xover", help="CSR UART prefix to use (default: uart_xover).")
    p.add_argument("--file", required=True, help="Binary to load (e.g. m2sdr_diag.bin).")
    p.add_argument("--address", default="0x40000000", help="Load address (default: 0x40000000).")
    p.add_argument("--jump", action="store_true", help="Jump to the load address after upload (default: false).")
    p.add_argument("--reset-cpu", action="store_true", help="Toggle CPU reset via ctrl_reset before waiting for magic.")
    p.add_argument("--reset-soc", action="store_true", help="Toggle SoC reset via ctrl_reset before waiting for magic.")
    p.add_argument("--wait-magic-timeout", type=float, default=10.0, help="Seconds to wait for SFL magic request.")
    p.add_argument("--ack-timeout", type=float, default=10.0, help="Seconds to wait for per-frame ack.")
    p.add_argument("--chunk", type=int, default=16, help="Bytes of data per SFL LOAD frame (smaller is more reliable on slow links).")
    p.add_argument("--tx-post-delay-ms", type=float, default=0.0, help="Optional delay after each transmitted byte (ms).")
    p.add_argument("--frame-post-delay-ms", type=float, default=5.0, help="Delay after each SFL frame before waiting for ack (ms).")
    p.add_argument("--retries", type=int, default=5, help="Retries per frame on ack timeout.")
    args = p.parse_args()

    load_addr = int(args.address, 0)
    path = args.file
    if not os.path.exists(path):
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    base_address = int(args.base_address, 0) if args.base_address is not None else None
    bus = RemoteClient(host=args.host, csr_csv=args.csr_csv, base_address=base_address)
    bus.open()
    try:
        uart = get_uart(bus, args.uart_name)
        tx_post_delay_s = max(0.0, args.tx_post_delay_ms) / 1000.0
        frame_post_delay_s = max(0.0, args.frame_post_delay_ms) / 1000.0

        # Optional reset: useful when a second litex_term cannot be kept open while loading.
        if args.reset_cpu or args.reset_soc:
            if not hasattr(bus.regs, "ctrl_reset"):
                raise RuntimeError("Requested reset but ctrl_reset CSR is not present in this design.")
            # ctrl_reset fields (from generated CSR): bit0 = soc_rst, bit1 = cpu_rst
            v = (1 if args.reset_soc else 0) | (2 if args.reset_cpu else 0)
            print(f"Toggling reset (value=0x{v:x})...")
            bus.regs.ctrl_reset.write(v)
            time.sleep(0.05)
            bus.regs.ctrl_reset.write(0)
            time.sleep(0.05)

        print(f"Waiting for BIOS SFL prompt/magic on {args.uart_name} (timeout {args.wait_magic_timeout:.1f}s)...")
        magic_buf = bytearray()
        prompt_buf = bytearray()
        deadline = time.time() + args.wait_magic_timeout
        while True:
            if time.time() > deadline:
                raise TimeoutError("did not see SFL magic request (try rebooting BIOS)")
            try:
                b = uart.read_byte(timeout_s=0.2)
            except TimeoutError:
                continue
            # Track both prompt and magic.
            prompt_buf.append(b)
            if len(prompt_buf) > len(SFL_PROMPT_REQ):
                prompt_buf = prompt_buf[-len(SFL_PROMPT_REQ):]
            if bytes(prompt_buf) == SFL_PROMPT_REQ:
                # BIOS is asking for serial-boot confirmation.
                uart.write(SFL_PROMPT_ACK, post_delay_s=tx_post_delay_s)
                prompt_buf.clear()

            magic_buf.append(b)
            if len(magic_buf) > len(SFL_MAGIC_REQ):
                magic_buf = magic_buf[-len(SFL_MAGIC_REQ):]
            if bytes(magic_buf) == SFL_MAGIC_REQ:
                break

        print("Magic request received. Sending magic ack.")
        uart.write(SFL_MAGIC_ACK, post_delay_s=tx_post_delay_s)
        # Drain any pending console output before starting the framed protocol.
        uart.drain()

        data = open(path, "rb").read()
        total = len(data)
        print(f"Uploading {path} to 0x{load_addr:08x} ({total} bytes)...")

        t0 = time.time()
        offset = 0
        chunk = max(1, min(int(args.chunk), SFL_PAYLOAD_MAX - 4))
        while offset < total:
            frame_data = data[offset: offset + chunk]
            payload = load_addr.to_bytes(4, "big") + frame_data
            sent = False
            last_err = None
            for _ in range(max(1, int(args.retries))):
                try:
                    sfl_send_frame(
                        uart, SFL_CMD_LOAD, payload,
                        ack_timeout_s=args.ack_timeout,
                        tx_post_delay_s=tx_post_delay_s,
                        frame_post_delay_s=frame_post_delay_s,
                    )
                    sent = True
                    break
                except TimeoutError as e:
                    last_err = e
                    # Re-send magic ack to re-sync in case the device missed it.
                    uart.write(SFL_MAGIC_ACK, post_delay_s=tx_post_delay_s)
                    uart.drain()
            if not sent:
                raise last_err if last_err is not None else TimeoutError("frame send failed")
            load_addr += len(frame_data)
            offset += len(frame_data)
            if (offset % 512) == 0 or offset == total:
                pct = (100 * offset) // total
                print(f"  {pct:3d}% ({offset}/{total})", end="\r", flush=True)

        dt = max(1e-9, time.time() - t0)
        print(f"\nUpload complete ({(total/dt)/1024:.1f} KiB/s).")

        if args.jump:
            jump_addr = int(args.address, 0)
            print(f"Jumping to 0x{jump_addr:08x}...")
            sfl_send_frame(
                uart, SFL_CMD_JUMP, jump_addr.to_bytes(4, "big"),
                ack_timeout_s=args.ack_timeout,
                tx_post_delay_s=tx_post_delay_s,
                frame_post_delay_s=frame_post_delay_s,
            )
            print("Done.")
        else:
            print("Upload done (no jump).")

    finally:
        bus.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

