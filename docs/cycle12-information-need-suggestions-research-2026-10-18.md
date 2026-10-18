# Cycle 12 research: information-need label reuse

**Research checked:** 2026-10-18
**Repository baseline observed:** `1fe2cec` (`v0.12.0`)
**Scope:** Read-only inspection of the current concept-query editor and official HTML/accessibility documentation. No code or tests were changed or run.

## Current implementation observed

The concept editor puts “Evaluation queries and information-need groups” inside a collapsed advanced `<details>` section. Its explanatory copy says that repeated information-need names group multiple query phrasings and that a blank name leaves each query as its own group. The row builder creates a regular text input limited to 120 characters; saving trims and collapses whitespace and omits the field when blank; loading restores the saved value. The app already uses a native `<datalist>` for index suggestions. The query row CSS stacks the fields on narrow screens (at and below 560px).

These observations are bounded to the relevant editor markup, row creation/collection/loading functions, and responsive styles. They do not establish how the backend computes evaluation fingerprints or whether a UI-only change is harmless to that pipeline; verify that separately before implementation claims.

## Options

| Option | Assessment |
| --- | --- |
| **A. Native datalist suggestions for existing labels** | A small fit for optional, reusable free-text labels, consistent with the existing index-suggestion pattern. Reusing a spelling can reduce accidental label drift. Browser and assistive-technology behavior has caveats, so suggestions must remain optional and ordinary free-text entry must continue to work. |
| **B. Visual grouping or variant summary in the editor** | Could make the relationship between a label and its query variants more visible. It adds UI surface to an already collapsed advanced editor, while the current explanation already describes grouping and blank behavior. A summary could also imply that variants grouped across train and validation are necessarily valid together. Defer unless novice observation shows the current explanation is not enough. |
| **C. Keep free text as-is or address another nearby novice issue** | Reasonable because there is no usage or confusion evidence. Within the proposed choices, however, A is a bounded, behavior-preserving convenience. Choose C if the next cycle prioritizes avoiding any dependence on native suggestion-popup behavior. |

## Official sources

Sources were checked on **2026-10-18**.

1. **WHATWG HTML Standard — the `datalist` element**
   https://html.spec.whatwg.org/multipage/form-elements.html#the-datalist-element
   The standard defines nonempty `<option>` values as suggestions connected to an input through its `list` attribute. This describes suggested values; it does not define this app’s grouping or save behavior.

2. **MDN — `<datalist>`: The HTML Data List element**
   https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/datalist
   MDN says suggestions do not restrict the input to listed values. It documents differences in popup presentation across browsers and identifies accessibility limitations: option text may not zoom, popup styling is very limited (including for high-contrast rendering), and some screen-reader/browser combinations, including NVDA with Firefox, may not announce popup contents. MDN labels the feature “Limited availability” and not Baseline. This supports treating support and interaction as uneven; it is not a complete, version-by-version browser support matrix.

3. **W3C WAI-ARIA Authoring Practices Guide — Combobox Pattern**
   https://www.w3.org/WAI/ARIA/apg/patterns/combobox/
   The pattern describes keyboard conventions for comboboxes, including Tab, arrow keys, Enter, and Escape. It recommends relying on browser-provided text editing behavior for text inputs and not interfering with those keys. This is design guidance for combobox widgets; it does not guarantee the exact native `<datalist>` interaction in any particular browser or assistive-technology combination.

## Product inference and recommendation

**Recommendation: choose A as a small, optional enhancement.** Build suggestions from nonblank labels already present in the current editor rows. Deduplicate suggestions using the existing Cycle 11 identity rule—trim and collapse whitespace, then compare case-insensitively—while preserving a readable display spelling. Keep blank values out of the suggestion list. Let users save a new label without selecting a suggestion, or leave the field blank. Keep helper text explicit that suggestions are optional and that repeating a label groups variants.

This recommendation is an inference from the current data model, UI, and the sources above. There is no telemetry or user research in this evidence to show how often people reuse labels or whether they currently find the grouping concept confusing.

Keep the slice UI-only: do not alter query execution, query IDs, ranking, evaluation behavior, or fingerprint inputs. Confirm this with a before/after inspection of the relevant serialization and evaluation/fingerprint path when implementation is authorized.

### Suggested acceptance criteria

- Keyboard users can focus the text input, type a prefix, navigate and accept a suggestion with the supported browser’s keyboard behavior, and continue ordinary typing/editing. Tab and Escape remain usable. Verify in the app’s target desktop browsers rather than assuming identical behavior everywhere.
- Suggestions refresh after concept load and after a label is added, edited, or deleted. The list has no blank entries or duplicate identities.
- Leaving the field blank remains blank and keeps the existing per-query singleton behavior. A novel label can be entered and saved without choosing a suggestion.
- Save and reload preserve the labels and the existing trim/collapse normalization.
- Changing only the suggestion UI leaves serialized query content, query IDs, query behavior, and fingerprint inputs unchanged. No backend or model changes are part of this slice.
- At 320px, 390px, 760px, and desktop widths, the label input and suggestion behavior do not cause clipping or overlap; the existing narrow-screen stacking remains intact.
- Record tested browser/assistive-technology combinations and retain free-text entry as the fallback path. Do not present the suggestion popup as the only way to understand or enter a label.

## Evidence limits

- No browser or assistive-technology matrix was run. Official documentation supports the stated semantics and cautions, not app-specific compatibility claims.
- No user confusion, accessibility complaint, or label-reuse frequency evidence was available.
- Code inspection was bounded to the relevant editor markup, query row creation/collection/loading code, and nearby responsive CSS. It was not an end-to-end trace through the backend, ranking, or fingerprint implementation.
- Therefore this readout supports a product recommendation for a small candidate slice; it does not prove usability impact or prove that a future implementation leaves fingerprints unchanged.

## Model record

The parent requested **`gpt-6-luna`** through the subagent tool. The runtime identity cannot be independently verified from this workspace or the available tool output; no claim about the actual serving model is made.
