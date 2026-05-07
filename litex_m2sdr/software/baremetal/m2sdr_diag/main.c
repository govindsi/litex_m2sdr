#include <stdint.h>

#include <generated/mem.h>
#include <generated/csr.h>
#include <generated/soc.h>

#include <hw/common.h>

// -------------------------------------------------------------------------------------------------
// Minimal console output
//
// LiteX libc/stdio routes printf() through the SoC's main UART CSRs (uart_*).
// On some LiteX-M2SDR builds, the interactive BIOS console is on the crossover UART (uart_xover_*),
// so printing through libc can appear "silent" even though the program is running.
// To keep this demo reliable, we write directly to the UART CSRs:
// - Prefer crossover UART if present (uart_xover_*).
// - Fallback to main UART (uart_*).
// -------------------------------------------------------------------------------------------------

static inline void diag_uart_putc(char c) {
#if defined(CSR_UART_XOVER_BASE)
    while (uart_xover_txfull_read()) {}
    uart_xover_rxtx_write((uint8_t)c);
#elif defined(CSR_UART_BASE)
    while (uart_txfull_read()) {}
    uart_rxtx_write((uint8_t)c);
#else
    (void)c;
#endif
    // Normalize LF for terminals.
    if (c == '\n') {
        diag_uart_putc('\r');
    }
}

static void diag_puts(const char *s) {
    while (*s) diag_uart_putc(*s++);
}

static void diag_puthex32(uint32_t v) {
    static const char h[] = "0123456789abcdef";
    for (int i = 7; i >= 0; i--) {
        diag_uart_putc(h[(v >> (i*4)) & 0xf]);
    }
}

static void delay_cycles(volatile uint32_t cycles) {
    while (cycles--) {
        __asm__ volatile("nop");
    }
}

static void print_yesno(const char *name, int v) {
    diag_puts("  ");
    diag_puts(name);
    // crude alignment
    int n = 0;
    for (const char *p = name; *p; p++) n++;
    for (int i = 0; i < (18 - n); i++) diag_uart_putc(' ');
    diag_puts(": ");
    diag_puts(v ? "yes\n" : "no\n");
}

static int have_block(uint32_t base) {
    (void)base;
    return 1;
}

static void print_enabled_blocks(void) {
    diag_puts("\nEnabled blocks (CSR presence):\n");

#ifdef CSR_PCIE_PHY_BASE
    print_yesno("pcie", 1);
#else
    print_yesno("pcie", 0);
#endif

#ifdef CSR_ETH_PHY_BASE
    print_yesno("ethernet", 1);
#else
    print_yesno("ethernet", 0);
#endif

#ifdef CSR_SATA_PHY_BASE
    print_yesno("sata", 1);
#else
    print_yesno("sata", 0);
#endif

#ifdef CSR_GPIO_BASE
    print_yesno("gpio", 1);
#else
    print_yesno("gpio", 0);
#endif

#ifdef CSR_CLK10_DISCIPLINE_BASE
    print_yesno("clk10_discipline", 1);
#else
    print_yesno("clk10_discipline", 0);
#endif

#ifdef CSR_TIME_GEN_BASE
    print_yesno("time_gen", 1);
#else
    print_yesno("time_gen", 0);
#endif

#ifdef CSR_AD9361_BASE
    print_yesno("ad9361", 1);
#else
    print_yesno("ad9361", 0);
#endif

#ifdef CSR_LEDS_BASE
    print_yesno("leds", 1);
#else
    print_yesno("leds", 0);
#endif

    (void)have_block;
}

static int test_ctrl_scratch(void) {
#ifdef CSR_CTRL_SCRATCH_ADDR
    const uint32_t pat = 0x12345678u;
    csr_wr_uint32(pat, CSR_CTRL_SCRATCH_ADDR);
    uint32_t rd = (uint32_t)csr_rd_uint32(CSR_CTRL_SCRATCH_ADDR);
    if (rd != pat) {
        diag_puts("  ctrl_scratch: FAIL (0x"); diag_puthex32(rd);
        diag_puts(" != 0x"); diag_puthex32(pat); diag_puts(")\n");
        return 0;
    }
    diag_puts("  ctrl_scratch: PASS (0x"); diag_puthex32(rd); diag_puts(")\n");
    return 1;
#else
    diag_puts("  ctrl_scratch: SKIP (no CSR)\n");
    return 1;
#endif
}

static int test_timer_tick(void) {
#ifdef CSR_TIMER0_VALUE_ADDR
    // LiteX timer value is latched; request an update before reading.
#ifdef CSR_TIMER0_EN_ADDR
    csr_wr_uint32(1u, CSR_TIMER0_EN_ADDR);
#endif
#ifdef CSR_TIMER0_UPDATE_VALUE_ADDR
    csr_wr_uint32(1u, CSR_TIMER0_UPDATE_VALUE_ADDR);
#endif
    uint32_t a = (uint32_t)csr_rd_uint32(CSR_TIMER0_VALUE_ADDR);
    for (volatile uint32_t i = 0; i < 50000; i++) {
        __asm__ volatile("nop");
    }
#ifdef CSR_TIMER0_UPDATE_VALUE_ADDR
    csr_wr_uint32(1u, CSR_TIMER0_UPDATE_VALUE_ADDR);
#endif
    uint32_t b = (uint32_t)csr_rd_uint32(CSR_TIMER0_VALUE_ADDR);
    if (a == b) {
        diag_puts("  timer0_value: FAIL (stuck at 0x"); diag_puthex32(a); diag_puts(")\n");
        return 0;
    }
    diag_puts("  timer0_value: PASS (0x"); diag_puthex32(a);
    diag_puts(" -> 0x"); diag_puthex32(b); diag_puts(")\n");
    return 1;
#else
    diag_puts("  timer0_value: SKIP (no CSR)\n");
    return 1;
#endif
}

static int test_led_force_on(void) {
#ifdef CSR_LEDS_OUT_ADDR
    diag_puts("  leds_out     : toggling (force on for ~short delay)\n");
    csr_wr_uint32(1u, CSR_LEDS_OUT_ADDR);
    for (volatile uint32_t i = 0; i < 2000000; i++) {
        __asm__ volatile("nop");
    }
    csr_wr_uint32(0u, CSR_LEDS_OUT_ADDR);
    return 1;
#else
    diag_puts("  leds_out     : SKIP (no CSR)\n");
    return 1;
#endif
}

int main(void) {
    diag_puts("\n=============================\n");
    diag_puts(" LiteX-M2SDR diag app\n");
    diag_puts("=============================\n");

#ifdef CONFIG_IDENTIFIER
    diag_puts("Identifier: "); diag_puts(CONFIG_IDENTIFIER); diag_puts("\n");
#endif

#ifdef CONFIG_CLOCK_FREQUENCY
    diag_puts("sys_clk   : 0x"); diag_puthex32((uint32_t)CONFIG_CLOCK_FREQUENCY); diag_puts(" Hz\n");
#endif

    diag_puts("ROM       : 0x"); diag_puthex32((uint32_t)ROM_BASE);
    diag_puts(" + 0x"); diag_puthex32((uint32_t)ROM_SIZE); diag_puts("\n");
    diag_puts("SRAM      : 0x"); diag_puthex32((uint32_t)SRAM_BASE);
    diag_puts(" + 0x"); diag_puthex32((uint32_t)SRAM_SIZE); diag_puts("\n");
#ifdef MAIN_RAM_BASE
    diag_puts("MAIN-RAM  : 0x"); diag_puthex32((uint32_t)MAIN_RAM_BASE);
    diag_puts(" + 0x"); diag_puthex32((uint32_t)MAIN_RAM_SIZE); diag_puts("\n");
#endif
    diag_puts("CSR       : 0x"); diag_puthex32((uint32_t)CSR_BASE);
#ifdef CSR_SIZE
    diag_puts(" + 0x"); diag_puthex32((uint32_t)CSR_SIZE);
#endif
    diag_puts("\n");

    print_enabled_blocks();

    diag_puts("\nSelf-tests:\n");
    int pass = 1;
    pass &= test_ctrl_scratch();
    pass &= test_timer_tick();
    pass &= test_led_force_on();

    diag_puts("\nResult: "); diag_puts(pass ? "PASS\n" : "FAIL\n");
    diag_puts("\nHeartbeat: printing every ~1s. Press reset to exit.\n");

    unsigned counter = 0;
    while (1) {
        counter++;
#ifdef CSR_LEDS_OUT_ADDR
        // Blink the "force on" compatibility bit to show liveness.
        csr_wr_uint32((counter & 1) ? 1u : 0u, CSR_LEDS_OUT_ADDR);
#endif
        diag_puts("[diag] alive 0x"); diag_puthex32(counter); diag_puts("\n");
#ifdef CONFIG_CLOCK_FREQUENCY
        delay_cycles((uint32_t)(CONFIG_CLOCK_FREQUENCY / 20)); // ~50ms
        delay_cycles((uint32_t)(CONFIG_CLOCK_FREQUENCY / 20)); // ~50ms
        delay_cycles((uint32_t)(CONFIG_CLOCK_FREQUENCY / 20)); // ~50ms
        delay_cycles((uint32_t)(CONFIG_CLOCK_FREQUENCY / 20)); // ~50ms
        delay_cycles((uint32_t)(CONFIG_CLOCK_FREQUENCY / 20)); // ~50ms
        delay_cycles((uint32_t)(CONFIG_CLOCK_FREQUENCY / 20)); // ~50ms
        delay_cycles((uint32_t)(CONFIG_CLOCK_FREQUENCY / 20)); // ~50ms
        delay_cycles((uint32_t)(CONFIG_CLOCK_FREQUENCY / 20)); // ~50ms
        delay_cycles((uint32_t)(CONFIG_CLOCK_FREQUENCY / 20)); // ~50ms
        delay_cycles((uint32_t)(CONFIG_CLOCK_FREQUENCY / 20)); // ~50ms
#else
        delay_cycles(5000000);
#endif
    }
}

