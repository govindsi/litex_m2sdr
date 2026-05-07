## `m2sdr_diag` (bare-metal BIOS-loadable demo)

This is a tiny bare-metal application meant to be **loaded from LiteX BIOS**. It prints some SoC diagnostics and runs a few safe self-tests:

- CSR access sanity (`ctrl_scratch` read/write)
- timer tick sanity (`timer0_value` changes)
- LED “force on” toggle via `leds_out` (if present)

### Build

Build against a specific SoC build directory (the one that contains `software/include/generated/variables.mak`):

```bash
cd litex_m2sdr/software/baremetal/m2sdr_diag
make BUILD_DIR=../../../../build/<your_build_name>
```

Output: `m2sdr_diag.bin`

### Load and run

Use `litex_term` to load the binary via the BIOS “serial boot” protocol over your console transport.
See the LiteX wiki for details on boot methods:

- [`Load Application Code To CPU`](https://github.com/enjoy-digital/litex/wiki/Load-Application-Code-To-CPU)

