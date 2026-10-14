---
name: pptx-render-via-powerpoint
description: No LibreOffice on this Mac — render .pptx for visual QA by scripting Microsoft PowerPoint to export PDF into the Office group container using an HFS path.
metadata:
  node_type: memory
  type: project
  originSessionId: 018e4980-6889-43c2-ac84-50a22aaabb94
  modified: 2026-10-13T22:04:55.395Z
---

This Mac has no LibreOffice, pdftoppm, python-pptx or markitdown, and the Inter font isn't installed; Microsoft PowerPoint is. The render path that works: `osascript` to `open (POSIX file p)` in PowerPoint, then `save presentation "<file name>" in <HFS path> as save as PDF` with the output under `~/Library/Group Containers/UBF8T346G9.Office/`, then `close … saving no`. A POSIX path string reports "saved" but writes nothing, and exporting to /private/tmp hangs on the sandbox. Allow 150s+ for the save — a 60s AppleEvent timeout failed on a 10-slide deck. PowerPoint caches documents by path: reopening a rebuilt file at the same path exported the OLD slides, so always render a uniquely named copy (e.g. qa-HHMMSS.pptx) and spot-check the PDF text (PDFKit page.string) before trusting images. Convert PDF pages with a small Swift PDFKit script. Delete the group-container scratch folder afterward.

Update 2026-10-13 (Darwin 27): this session could not read or write `~/Library/Group Containers/UBF8T346G9.Office/` at all ("Operation not permitted", even unsandboxed), so the PDF-export path was unusable. What worked instead, fully headless: Quick Look. `qlmanage -t -s 1600 -o <dir> deck.pptx` renders only the first slide, so write one copy of the deck per slide with `<p:sldIdLst>` cut down to that slide and thumbnail each. Fonts are substituted (Inter shows as a serif) and picture crop shapes are ignored, so treat it as a layout check, not a text-fit check; estimate text fit from character counts. `open -a "Microsoft PowerPoint" file` plus `count of slides of presentation N` over osascript still works and confirms PowerPoint loads the file (a `repeat with p in presentations` loop hung; index the presentations instead). For icons: `npm install lucide-static` in the scratchpad, recolor the SVG stroke, and rasterize to PNG with a small Swift `NSImage` script.

Devin edits a delivered deck in PowerPoint between turns (on 2026-10-13 he reworded a title and deleted two slides within minutes). Before changing a deck again, compare the file's md5 with what was delivered and ask PowerPoint for `saved of presentation N`. If he has saved edits, patch his file's XML (shape names survive PowerPoint's re-save) instead of regenerating; if `saved` is true, `close presentation "<name>" saving no`, replace the file and reopen it; if `saved` is false, leave it alone and write a new file.

**Why:** these four traps (path format, sandbox, timeout, stale cache) cost several round trips on 2026-09-14.
**How to apply:** go straight to this path for any .pptx visual QA on this machine. Context: [[plaid-technical-deep-dive]].
