/* OpenHardware - a bare-metal RP2350 blink, on the chip's Hazard3 half.
 *
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 the OpenHardware authors. See LICENSE.
 *
 * The sibling of `tests/cortexm0/blink/blink.c`, the RP2040's, and the
 * shape is the same on purpose: release the IO banks from reset, give the
 * pad to the processors, and toggle it. Reading the two side by side shows
 * what moved between the parts: every SIO offset past GPIO_OUT, and one
 * register the RP2040 does not have at all -- the pad's isolation latch.
 *
 * ## No GPIO is typed here
 *
 * `BLINK_GPIO` comes from the command line, and the build in
 * `tests/webui/test_xiao_rp2350_board.py` reads it out of
 * `webui/boards/rp2350.py`'s `HEADER`
 * -- the XIAO RP2350's `D3`, which `tools/import_pindefs.py` read out of the
 * vendor's board-support packages. The committed `blink.bin` was built that
 * way, and the test that rebuilds it byte for byte is what holds the two
 * together.
 *
 * ## Addresses, from pico-sdk 2.3.0 (98a542c, the commit arduino-pico 33201a6
 * pins as its submodule), src/rp2350/hardware_regs/include/hardware/regs/
 *
 *     addressmap.h:21   REG_ALIAS_CLR_BITS (0x3 << 12)
 *     addressmap.h:42   SRAM_END           0x20082000
 *     addressmap.h:47   RESETS_BASE        0x40020000
 *     addressmap.h:48   IO_BANK0_BASE      0x40028000
 *     addressmap.h:50   PADS_BANK0_BASE    0x40038000
 *     addressmap.h:105  SIO_BASE           0xd0000000
 *     resets.h:17       RESETS_RESET_OFFSET        0x0
 *     resets.h:156      RESETS_RESET_PADS_BANK0_BITS 0x200
 *     resets.h:177      RESETS_RESET_IO_BANK0_BITS   0x40
 *     io_bank0.h:55     IO_BANK0_GPIO0_CTRL_OFFSET 0x004, eight apart (:193)
 *     io_bank0.h:146    ..._FUNCSEL_VALUE_SIO_0    0x05
 *     pads_bank0.h:30   PADS_BANK0_GPIO0_OFFSET    0x004, four apart (:109)
 *     pads_bank0.h:38   PADS_BANK0_GPIO0_ISO_BITS  0x100
 *     sio.h:310         SIO_GPIO_OUT_XOR_OFFSET    0x028
 *     sio.h:456         SIO_GPIO_OE_SET_OFFSET     0x038
 *
 * Each can be overridden with -D, and one build does: the lockstep test
 * moves every base into rvcpp's testbench RAM, because rvcpp maps nothing
 * at these addresses. The image committed beside this file overrides none.
 *
 * ## What it does not do, and why
 *
 * It does not wait on RESETS.RESET_DONE after releasing the two banks, as
 * the RP2040's blink does. RESET_DONE reads as the inverse of RESET, which
 * is a mirror, and `core/riscv32` has no way to map one -- so the board
 * leaves it unmapped and a read of it faults rather than answering a value
 * nothing computes. The datasheet frames the wait as for "a component that
 * requires initialisation before use" (RP2350 Datasheet 80d627281ed5,
 * section 7.5.2, PDF p.459); this image's next store to either bank is
 * several instructions after the release.
 *
 * Compiled -march=rv32imac: no Zbb and no Zbkb, the two groups of the
 * Hazard3's string `core/riscv32` does not model.
 */

#ifndef BLINK_GPIO
#error "BLINK_GPIO is the XIAO RP2350's D3, read from webui/boards/rp2350.py's HEADER by the test that builds this"
#endif

#ifndef RESETS_BASE
#define RESETS_BASE     0x40020000u
#endif
#ifndef IO_BANK0_BASE
#define IO_BANK0_BASE   0x40028000u
#endif
#ifndef PADS_BANK0_BASE
#define PADS_BANK0_BASE 0x40038000u
#endif
#ifndef SIO_BASE
#define SIO_BASE        0xd0000000u
#endif
#ifndef STACK_TOP
#define STACK_TOP       0x20082000u
#endif

#define ALIAS_CLR         0x3000u
#define RESET_IO_BANK0    0x40u
#define RESET_PADS_BANK0  0x200u
#define FUNCSEL_SIO       0x05u
#define PAD_ISO           0x100u

#define REG(a) (*(volatile unsigned int *)(a))

#define RESETS_RESET_CLR  (RESETS_BASE + 0x0u + ALIAS_CLR)
#define GPIO_CTRL         (IO_BANK0_BASE + 0x004u + 8u * (BLINK_GPIO))
#define PAD               (PADS_BANK0_BASE + 0x004u + 4u * (BLINK_GPIO))
#define GPIO_OUT_XOR      (SIO_BASE + 0x028u)
#define GPIO_OE_SET       (SIO_BASE + 0x038u)

int main(void);

/* The minimum RISC-V IMAGE_DEF, word for word from RP2350 Datasheet
 * 80d627281ed5, section 5.9.5.2, Table 504 (PDF p.391): without a valid
 * IMAGE_DEF in the first 4 kB of flash the boot ROM does not boot an image
 * at all (section 5.9.5, PDF p.390). It names no entry point, and for that
 * case the same page says "the bootrom will enter the binary at its lowest
 * address, which is the default behaviour on RISC-V" -- which is `_start`,
 * and which is where `core/riscv32/machine.py` enters a raw image. So the
 * boot ROM this repository does not model would hand over at the same
 * instruction this one starts at. `blink.ld` puts the block after the code. */
__attribute__((section(".image_def"), used))
static const unsigned int image_def[5] = {
    0xffffded3u,  /* PICOBIN_BLOCK_MARKER_START */
    0x11010142u,  /* IMAGE_TYPE: EXE, RISC-V, RP2350 */
    0x000001ffu,  /* LAST, size 1 */
    0x00000000u,  /* link to self: a loop of this one block */
    0xab123579u,  /* PICOBIN_BLOCK_MARKER_END */
};

/* The entry point, and the whole of what a crt0 would do here: an RV32 part
 * loads no stack pointer from anywhere, so the image sets its own. `naked`
 * because a prologue would use the stack this is setting up. */
__attribute__((naked, section(".text.start"))) void _start(void) {
    __asm__ volatile(
        "li sp, %0\n"
        "j  main\n"
        :: "i"(STACK_TOP)
    );
}

int main(void) {
    /* Release IO_BANK0 and PADS_BANK0 through RESETS' atomic clear alias. */
    REG(RESETS_RESET_CLR) = RESET_IO_BANK0 | RESET_PADS_BANK0;

    /* Give the pad to the processors: FUNCSEL is NULL out of reset, and SIO
     * drives a GPIO only where it is selected. */
    REG(GPIO_CTRL) = FUNCSEL_SIO;

    /* Then, with the muxing set up, open the isolation latch, which every
     * pad comes out of reset holding closed. */
    REG(PAD) &= ~PAD_ISO;

    REG(GPIO_OE_SET) = 1u << (BLINK_GPIO);

    for (;;) {
        REG(GPIO_OUT_XOR) = 1u << (BLINK_GPIO);
        for (volatile unsigned int i = 0; i < 100; i++) {
        }
    }
}
