# What the Acorn wiring sheets are for

Reader: someone at a bench with a host (Pi 5 + Waveshare PoE M.2 HAT+, or a Compute Blade),
an Acorn, two Molex Pico-EZmate cables whose six wires are ALL BLACK, Dupont housings and a crimper.

## Must be answerable from the picture alone, in under a minute

1. Which Acorn connector is P1 (JTAG) and which is P2 (I/O), where they are on the card, which end is pin 1.
2. Where the header is on the host, and which pin is which, using the numbers PRINTED ON THAT BOARD.
3. For each of the six wires of each cable: which header pin it goes to, or that it is cut.
4. Blade only: which header each cable goes to (P1: Extension Port, P2: UART), which wire carries the
   470 ohm resistor, which wires are cut back (J5, H5), and that pin 1 of each housing must be marked.
5. What must stay empty / never be connected (both VCC wires; the 5 V pins).
6. Which end drives each signal.
7. The openFPGALoader --pins string.

## Must be true of the drawing

- Board pictures are the real boards (photos), not art from memory. Every highlight sits on the real feature.
- The drawn header has the same orientation as the photo beside it; every pad is inside the header body.
- Every piece of text is inside its box, inside the canvas, and overlaps no other text and no wire.
  The generator measures text with the same advances it draws the glyph outlines with, and fails the build otherwise.
- One representation per thing: the header is drawn once (no separate "housing" copy).
- Any single wire can be followed end to end: two-bend routes, one lane each, crossings only at right angles,
  a signal tag at BOTH ends.
- Both sheets are laid out the same way: host photo on the left, then the drawn header(s), the plugs,
  and the Acorn on the right.
- The SVG loads nothing (no external or data: URIs), so it renders from its raw GitHub URL.

## Must not be on the drawing

- Paragraphs. Anything that needs a paragraph belongs on the docs page ([Acorn wiring](https://docs.fpgas.online/en/latest/boards/acorn/wiring.html)).
- Pin numbers from a scheme that is not printed on the board in the picture.
- Decorative board art, fake chips, fake LEDs.
