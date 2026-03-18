# docs-site-steel-visual-pass
Date: 2026-03-19 02:25

## Что сделано
- Reworked `docs/index.md` from a generic docs homepage into a product-style landing built around a steel/minimal visual direction.
- Added a stronger hero, runtime cards, capability cards, use-case cards, and a guided quick-start block that matches the actual library positioning.
- Introduced thin mono SVG icons and scroll-reveal motion via `docs/assets/site.js`.
- Strengthened site chrome in `docs/assets/extra.css`: frosted header, steel surfaces, stronger card hierarchy, hover motion, and better desktop/mobile rhythm.
- Fixed a real mobile bug where hero content did not shrink correctly; the fix was `min-width: 0` on `.hero-grid > *` plus smaller mobile typography.

## Новые знания
- The visual upgrade only works if content and CSS are redesigned together; upgrading CSS alone leaves MkDocs looking mostly default.
- Avoid markdown tab syntax inside custom HTML sections on the homepage; MkDocs can leave literal `===` markers in the DOM there.
- For responsive hero grids, `min-width: 0` on grid children matters more than additional breakpoint rules when large headings/code cards are present.
- Full-page screenshots can make reveal-on-scroll sections look blank if elements stay hidden until intersection; viewport checks are more reliable for visual smoke.
