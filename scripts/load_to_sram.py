#!/usr/bin/env python3
"""
Load a raw .bin into integrated SRAM via RemoteClient (Etherbone/PCIe) and optionally reset.

This avoids LiteX BIOS' SFL "serialboot" framing, which can be unreliable over Etherbone+crossover.

Typical use:
  1) Load:  python3 scripts/load_to_sram.py --csr-csv scripts/csr.csv --file app.bin --addr 0x10000000
  2) In BIOS: litex> boot 0x10000000
"""

from __future__ import annotations

import argparse
import os
import time

from litex import RemoteClient


def main() -> int:
    p = argparse.ArgumentParser(description="Write a binary to SRAM over RemoteClient.")
    p.add_argument("--csr-csv", default="scripts/csr.csv", help="csr.csv matching the bitstream.")
    p.add_argument("--host", default="localhost", help="litex_server host.")
    p.add_argument("--port", type=int, default=1234, help="litex_server TCP port.")
    p.add_argument("--file", required=True, help="Path to .bin file.")
    p.add_argument("--addr", default=None, help="Destination address. Default: main_ram base if present, else SRAM base.")
    p.add_argument("--endianness", default="little", choices=["little", "big"], help="Word endianness.")
    p.add_argument("--reset-cpu", action="store_true", help="Toggle CPU reset after upload (ctrl_reset bit1).")
    p.add_argument("--reset-soc", action="store_true", help="Toggle SoC reset after upload (ctrl_reset bit0).")
    p.add_argument("--verify", action="store_true", help="Read back and verify (slow).")
    p.add_argument("--chunk-words", type=int, default=4, help="Write burst length in 32-bit words (smaller is more reliable on UDP).")
    p.add_argument("--delay-ms", type=float, default=1.0, help="Delay between bursts in milliseconds (helps avoid UDP/Etherbone overruns).")
    args = p.parse_args()

    if not os.path.exists(args.file):
        raise SystemExit(f"File not found: {args.file}")

    data = open(args.file, "rb").read()
    # Pad to 32-bit words.
    if len(data) % 4:
        data += b"\x00" * (4 - (len(data) % 4))

    words = []
    for i in range(0, len(data), 4):
        words.append(int.from_bytes(data[i:i+4], byteorder=args.endianness))

    b = RemoteClient(host=args.host, port=args.port, csr_csv=args.csr_csv)
    b.open()
    try:
        # Default destination: main_ram if present, else sram.
        if args.addr is None:
            if hasattr(b, "mems") and hasattr(b.mems, "main_ram"):
                addr0 = int(b.mems.main_ram.base)
            elif hasattr(b, "mems") and hasattr(b.mems, "sram"):
                addr0 = int(b.mems.sram.base)
            else:
                addr0 = 0x10000000
        else:
            addr0 = int(args.addr, 0)

        print(f"Writing {len(words)*4} bytes to 0x{addr0:08x}...")
        t0 = time.time()
        for off in range(0, len(words), args.chunk_words):
            chunk = words[off:off + args.chunk_words]
            b.write(addr0 + 4*off, chunk)
            if args.delay_ms:
                time.sleep(max(0.0, args.delay_ms) / 1000.0)
            if (off % (args.chunk_words * 16)) == 0:
                pct = (100 * off) // max(1, len(words))
                print(f"  {pct:3d}% ({off*4}/{len(words)*4})", end="\r", flush=True)
        dt = max(1e-9, time.time() - t0)
        print(f"\nDone ({(len(words)*4/dt)/1024:.1f} KiB/s).")

        # Quick liveness check (best-effort) to detect if the link got wedged.
        if hasattr(b.regs, "ctrl_scratch"):
            b.regs.ctrl_scratch.write(0xfeedface)
            rd = b.regs.ctrl_scratch.read()
            if rd != 0xfeedface:
                print("WARNING: ctrl_scratch readback failed after upload (Etherbone may be unstable).")

        if args.verify:
            print("Verifying (readback)...")
            for off in range(0, len(words), args.chunk_words):
                chunk = b.read(addr0 + 4*off, length=min(args.chunk_words, len(words)-off))
                if isinstance(chunk, int):
                    chunk = [chunk]
                if chunk != words[off:off+len(chunk)]:
                    raise SystemExit(f"Verify failed at +0x{off*4:x}")
            print("Verify OK.")

        if args.reset_cpu or args.reset_soc:
            if not hasattr(b.regs, "ctrl_reset"):
                raise SystemExit("ctrl_reset CSR not present; cannot reset.")
            v = (1 if args.reset_soc else 0) | (2 if args.reset_cpu else 0)
            print(f"Toggling reset (value=0x{v:x})...")
            b.regs.ctrl_reset.write(v)
            time.sleep(0.05)
            b.regs.ctrl_reset.write(0)
            time.sleep(0.05)

    finally:
        b.close()

    print(f"Next: in BIOS run `boot 0x{addr0:08x}` (or your chosen address).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

