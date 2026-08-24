/* OpenHardware - a bare-metal RP2040 that prints, for proving a UART works.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * No pico-sdk and no stdio, for the reason `../blink/blink.c` gives: the
 * vendor runtime calls into a boot ROM this project cannot ship. What is left
 * is the part that proves a UART: take it out of reset, set the baud divisors
 * and the line control, enable it, and push bytes at UARTDR while UARTFR says
 * the transmit FIFO has room.
 *
 * The order is the part worth reading. UARTEN goes on LAST, after the
 * divisors and LCR_H -- pico-sdk's uart.c:56 says "Any LCR writes need to take
 * place before enabling the UART", and the emulated data register discards
 * everything written while UARTEN is clear, exactly as the silicon does. A
 * program that printed before enabling would produce no output here, which is
 * the point: it produces none on the part either.
 */

#define RESETS          0x4000c000u
#define RESETS_RESET    (RESETS + 0x00u)
#define RESETS_DONE     (RESETS + 0x08u)
#define ALIAS_CLR       0x3000u

#define RESET_UART0     (1u << 22)

#define UART0           0x40034000u
#define UART_DR         (UART0 + 0x00u)
#define UART_FR         (UART0 + 0x18u)
#define UART_IBRD       (UART0 + 0x24u)
#define UART_FBRD       (UART0 + 0x28u)
#define UART_LCR_H      (UART0 + 0x2cu)
#define UART_CR         (UART0 + 0x30u)

#define FR_TXFF         (1u << 5)

#define LCR_H_WLEN_8    (3u << 5)   /* 8 data bits */
#define LCR_H_FEN       (1u << 4)   /* FIFOs enabled */

#define CR_UARTEN       (1u << 0)
#define CR_TXE          (1u << 8)

#define REG(a) (*(volatile unsigned int *)(a))

static void putc_raw(unsigned int c) {
    /* The spin pico-sdk's uart_putc_raw does. A TXFF that never cleared would
     * hang here on the second character, which is why the model's UARTFR is
     * pinned by a test rather than assumed. */
    while (REG(UART_FR) & FR_TXFF) {
    }
    REG(UART_DR) = c;
}

void _start(void) {
    REG(RESETS_RESET + ALIAS_CLR) = RESET_UART0;
    while ((REG(RESETS_DONE) & RESET_UART0) != RESET_UART0) {
    }

    /* 115200 baud from a 125 MHz peripheral clock: 125e6/(16*115200) = 67.817,
     * so IBRD 67 and FBRD round(0.817*64) = 52. The emulated UART does not
     * time anything, so these are written to be a real configuration rather
     * than because the model reads them. */
    REG(UART_IBRD) = 67u;
    REG(UART_FBRD) = 52u;
    REG(UART_LCR_H) = LCR_H_WLEN_8 | LCR_H_FEN;
    REG(UART_CR) = CR_UARTEN | CR_TXE;

    static const char message[] = "hello, world\n";
    for (const char *p = message; *p; p++) {
        putc_raw((unsigned int)*p);
    }

    for (;;) {
    }
}
