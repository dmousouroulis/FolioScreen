# Visual capability probe — results

Tested in Power BI Service (free licence, My workspace) in a desktop browser and in the Power BI iPhone app,
on fictional demo data.

## Round 1 (10 Nov 2026)

| ID | Technique | Desktop | iPhone | Decision |
|---|---|---|---|---|
| T1 | Segoe UI Light / Semilight / Regular / Semibold / Bold | pass, distinct weights, no serif | pass | large Light figures, Semibold labels |
| T2 | right-aligned numbers and headers | pass | — | native tables |
| T3 | several values in one card visual | pass; inner dark box; auto units (72.92K) | values cut off | fix settings (round 2) |
| T4 | card reference labels (role `ReferenceLabels`) | not rendered | — | use a separate small line |
| T5 | container corner radius | pass (6 and 14) | pass | rounded panels; shadows not useful on dark |
| T6 | static signed format `+0.00%;−0.00%` | pass | — | use |
| T6 | dynamic format string | deploy failed: TMDL child object placed before plain properties | — | retest (round 2) |
| T7 | ▲ ▼ ● ◆ ↗ ↘ ✓ ⚠ | pass | — | text markers |
| C1 | area chart | pass | pass | candidate hero chart |
| C2 | two lines, right axis, zero line, legend top | pass | pass | performance chart |
| C2 | report-page tooltip | pass (values truncated: sizing) | — | use; resize (round 2) |
| C3 | field parameter | table deployed; visual error: missing `fieldParameters` query binding | — | retest (round 2) |
| C4 | sorted bars with labels | pass (stray axis title) | — | allocation |
| B1 | DAX SVG images in table cells | pass | pass | image columns; row height too large |
| B2 | native sparklines (`SparklineData`) | fail (table empty, no error) | fail | draw trends as SVG images |
| — | drillthrough | menu item absent: source visual lacked the drillthrough field | — | retest (round 2) |
| — | phone layouts (`mobile.json`) | — | pass | dedicated phone layouts |

Layout lessons: two-paragraph captions at 10 + 9 pt need more than 40 px or they scroll.
Phone layouts support per-visual formatting overrides (`objects`, `visualContainerObjects` in `mobile.json`).

## Findings from the Phase 4 build (10 Nov 2026, FolioScreen-Demo)

| Finding | Detail |
|---|---|
| Button slicer text | Needs the inner `padding` block (`paddingSelection: Custom`, top/bottom 0) as in Marine Energy Screen; without it the text is pushed out of a 32–36 px button. |
| Action button text | `text.show` must sit in an entry **without** a selector; text, colour and font go under `selector: default`. |
| Field parameter, several fields per option | Two rows sharing one display label become two separate slicer items. Filter an extra column (`Mode`) instead: one click selects every row with that value. |
| `SELECTEDVALUE` on a field-parameter display column | Errors (the column has a group-by column). Read a plain extra column instead. |
| Measure inside a `CALCULATE` boolean filter | Rejected ("function 'PLACEHOLDER' … table filter expression"). Capture it in a `VAR` first; a unit test now guards this. |
| `executeQueries` errors | May return HTTP 200 with an `error` object and empty rows; `execute_dax` treats both as errors. |
| Reference line at 0 on a value chart | Forces the axis to include 0; used only on return charts. |
| Drillthrough filter context | `pageBinding.acceptsFilterContext: "None"` keeps page slicers from flowing into the detail page. |
| Verified on screen | Custom tooltip page (2 × 2), conditional colour by measure in cards, tables and bars, table totals, column chart, page navigation and Back buttons, slicer default selection. |
| Phone: multi-value card | Does not reflow on the phone (the `maxTiles` override has no effect): seven values are squeezed into one row. Figures that must stack on the phone are separate cards; on desktop they share one panel. |
| Phone: wide tables | Phone layouts reuse the desktop visual, so a 14-column table scrolls sideways. A compact phone-only table sits behind the full table on desktop (fully covered, lower z) and is the only one in the phone layout. |
| Phone: per-visual overrides | `objects` (font size) and `visualContainerObjects` (panel style) in `mobile.json` both apply. |
| Column chart with 12 categories | Scrolls in a 300 px panel; `preferredCategoryWidth` did not help. A continuous (date) axis does not scroll. |
| Refresh allowance | `POST /refreshes` returns HTTP 429 ("Retry in 120 seconds") once a shared-capacity model has used its 8 refreshes in a rolling 24 h; retrying minutes later fails again. FolioScreen reports it instead of retrying; `deploy --no-refresh` publishes report and measure changes without using a refresh. |
