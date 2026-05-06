## SoC Test Notes (CPU/BIOS Console)

This repository has optional build support for running the LiteX BIOS on an embedded soft-CPU and getting a console, without changing the default “minimal streaming/control SoC” behavior.

- **CPU/BIOS enablement**: `./litex_m2sdr.py` gained `--with-cpu` and related CPU sizing/selection flags (`--cpu-type`, `--cpu-variant`, `--integrated-rom-size`, `--integrated-sram-size`).
- **Console UART selection**: `--cpu-uart` selects where the BIOS console goes:
  - **`crossover`**: CSR-based UART that is accessed from the host through a LiteX host bridge (`litex_server` over PCIe/JTAG/UDP/UARTBone).
  - **`gpios`**: physical UART mapped to TP pads (TP1/TP2) so you can use a normal USB‑UART dongle without any host bridge.
- **CSR description file**: tools that talk to CSRs (e.g. `litex_term crossover`, `RemoteClient`) must use a `csr.csv` that matches the loaded bitstream. In this repo it is generated as **`scripts/csr.csv`**.
- **JTAGBone caveat**: if the JTAG-based host bridge is unstable, CSR reads will time out (e.g. `ctrl_scratch` readback returns `0x0`) and the crossover BIOS console will appear “blank”. In that case, prefer PCIeBone (when PCIe is connected/enumerated) or the physical UART option (`--cpu-uart=gpios`).

### Optional: build with an embedded CPU + LiteX BIOS console

By default, the LiteX-M2SDR SoC is built as a minimal control/streaming design (no embedded CPU).
If you want a **soft-CPU + BIOS** for quick experiments or a small bare-metal app, you can enable it with:

```bash
./litex_m2sdr.py --with-pcie --variant=baseboard --with-cpu --build --load
```

- The build enables a **VexRiscv** CPU by default (`--cpu-type vexriscv`) with an integrated ROM/SRAM and the LiteX BIOS.
- By default, the console uses LiteX's **crossover UART** (CSR-based), so it does not require dedicated UART pins (but it needs a working LiteX remote link).
- If you want a **physical UART** console (no PCIe/etherbone/JTAGBone needed), use `--cpu-uart=gpios` and connect a 3.3V USB-UART:
  - TX = TP1 (`E22`)
  - RX = TP2 (`D22`)
  - Baudrate = `115200`
- You can tune sizes with `--integrated-rom-size` / `--integrated-sram-size` (hex values accepted, e.g. `0x20000`).

### Build / load / flash (gateware)

All commands below are run from the `litex_m2sdr/` directory.

#### Build only

```bash
./litex_m2sdr.py --with-pcie --variant=baseboard --with-cpu --build
```

#### Load to FPGA SRAM (volatile)

If you already built:

```bash
./litex_m2sdr.py --with-pcie --variant=baseboard --with-cpu --load
```

Or build + load in one step:

```bash
./litex_m2sdr.py --with-pcie --variant=baseboard --with-cpu --build --load
```

#### Flash to SPI flash (persistent)

```bash
./litex_m2sdr.py --with-pcie --variant=baseboard --with-cpu --build --flash
```

### Connect to the BIOS console

#### Crossover UART (needs a working LiteX remote link)

Use `litex_term` with the remote transport you are using (PCIeBone/JTAGBone/Etherbone).
See the LiteX tools documentation for the exact `litex_term` invocation for your chosen transport.

Notes:
- `litex_term crossover` does **not** open `/dev/ttyUSB*`. It reads/writes the SoC’s `uart_xover_*` CSRs through `litex_server`.
- If you change your SoC configuration and rebuild, regenerate and use the matching `scripts/csr.csv`.

##### Test the crossover UART via JTAGBone

1. Start the server (leave it running):

```bash
litex_server --jtag --jtag-config=<path-to-openocd-cfg> --jtag-chain <n>
```

Where:
- `<path-to-openocd-cfg>` is your OpenOCD config for the JTAG adapter you are using.
- `<n>` must match the bitstream’s JTAGBone USER chain (default is `1`; if you built with a custom chain, use the same value).

2. Verify CSR read/write works (in another terminal):

```bash
python3 - <<'PY'
from litex import RemoteClient
b = RemoteClient(csr_csv="scripts/csr.csv", debug=True)
b.open()
b.regs.ctrl_scratch.write(0x12345678)
print("scratch:", hex(b.regs.ctrl_scratch.read()))
b.close()
PY
```

Expected: `scratch: 0x12345678`. If you get timeouts / `0x0`, the JTAGBone CSR tunnel is not working and the crossover console will not work either.

3. Open the BIOS console:

```bash
litex_term crossover --csr-csv scripts/csr.csv
```

#### Physical UART on TP1/TP2 (no host bridge required)

Connect a 3.3V USB-UART to the board:
- TX = TP1 (`E22`)
- RX = TP2 (`D22`)

Then open a terminal at 115200 baud (example):

```bash
picocom -b 115200 /dev/ttyUSB0
```

