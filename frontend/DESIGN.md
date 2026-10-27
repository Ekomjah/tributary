# DESIGN.md: Tributary

Read this file before writing or changing any UI. If a rule here conflicts with a library default, this file wins.

## Concept

Tributary looks like a web app from **2013**: the flat-but-practical look of Google Reader at the end of its life. White canvas, grey chrome, a narrow feed sidebar with tiny icons and grey unread counts, bold blue headlines, small grey excerpts, one red call-to-action button. Colors are few and meaningful. Corners are square or almost square.

The reference screenshots are saved as `public/sample.jpeg` (overall layout) and `public/reading-view.webp` (article view). When in doubt, match them.

This is a homage to the style, not a copy. Do not use Google logos, the Google wordmark, Google's trademarked icons, or Reader's original artwork. Draw original icons.

## Principles

1. **Content first.** White background, text does the work. Chrome is light grey, thin and quiet.
2. **Flat with one-pixel structure.** 1px borders and dividers. No gradients and no glossy effects. A very faint shadow is allowed only on floating things (menus, dialogs).
3. **Square-ish.** Border radius is **2px** on buttons, inputs and cards. Never more than 3px. No pills, no circles except avatars and radio buttons.
4. **Color has jobs.** Blue = links and headlines. Red = the one primary action. Grey = secondary text and counts. Yellow = starred. Green and amber = status. Don't decorate with color.
5. **Dense and scannable.** Small type, tight rows, counts in parentheses.
6. **State is never color alone.** Pair color with a glyph, weight or text.

## Tokens

```css
:root {
  /* surfaces */
  --bg:        #ffffff;   /* page and content */
  --chrome:    #f1f1f1;   /* top bar, toolbars, pipe box headers */
  --sidebar:   #fafafa;   /* feed list column */
  --divider:   #ebebeb;   /* thin dividers between rows */
  --border:    #d9d9d9;   /* borders on inputs, cards, boxes */

  /* text */
  --text:      #222222;   /* primary text */
  --text-2:    #666666;   /* meta: source, date, excerpt */
  --text-3:    #999999;   /* counts, hints, disabled */

  /* brand and links */
  --blue:      #1155cc;   /* links, item headlines, selected accents */
  --blue-dark: #0b3c99;   /* hover and visited-active */
  --blue-bg:   #e8f0fe;   /* selected row and hover tint */
  --red:       #d14836;   /* primary action button, destructive */
  --red-dark:  #b0281a;   /* red button border and hover */

  /* status */
  --yellow:    #f4b400;   /* starred */
  --green:     #0f9d58;   /* success, fresh, running OK */
  --amber:     #e37400;   /* warning, slow, stale */

  /* shape */
  --radius: 2px;
  --shadow-float: 0 2px 4px rgba(0, 0, 0, 0.2);   /* menus and dialogs only */

  /* type */
  --font: "Arimo", Arial, Helvetica, sans-serif;     /* free Arial-metric font */
  --font-mono: "Roboto Mono", ui-monospace, monospace;
  --text-sm: 11px;     /* counts, meta */
  --text-base: 13px;   /* body, rows */
  --text-md: 15px;     /* item headlines, section titles */
  --text-lg: 20px;     /* page titles */
  --row-h: 28px;
  --space-1: 4px; --space-2: 8px; --space-3: 16px; --space-4: 24px;
}
```

Fonts: Arimo (Apache 2.0) matches Arial's metrics. Check each font's license before shipping. Body text is 13px; do not go below 11px anywhere. Minimum contrast 4.5:1 for text; `--text-3` is for counts and hints only, never essential text.

## Layout

Three zones, as in the reference:

1. **Top bar** (56px, `--bg`, bottom border `--divider`): app name "Tributary" (20px, `--red`, bold) at the left, a wide search input in the middle, and a small settings link at the right.
2. **Sub bar** (40px, `--bg`): left, the red **Add feed** button; right, view controls (All items, Unread, Starred) as plain text links with the active one bold and underlined.
3. **Two columns** below:
   - **Sidebar** (240px, `--sidebar`, right border `--divider`): the feed tree.
   - **Content** (fluid, max 760px readable column, left padding 24px): the list of items.

**Mobile** (under 700px): the sidebar is a slide-over opened from a menu icon, and the content takes the full width with 16px gutters.

## Sidebar: the feed tree

- Top entries: **Home**, **All items**, **Starred items**, then a divider, then **Pipes**, then your **Feeds**.
- **Folders:** a small triangle (right when collapsed, down when open), a folder glyph, the folder name, and the total unread in grey parentheses, e.g. `Search (702)`.
- **Feeds:** a 16x16 favicon (or a generic square glyph if none), the feed title (truncate with an ellipsis), and unread count in grey parentheses `(42)`. Feeds with unread items are **bold**.
- **Row:** `--row-h` high, 8px left padding, indented 16px per level.
- **Selected row:** `--blue-bg` background, 3px `--blue` left border, bold text.
- **Hover:** `#f0f0f0` background.

## Content: the item list

Each item is a **block with space around it**, not a bordered card:

- **Group header** (when grouped by feed): feed title as a bold 20px `--blue` link followed by the count in grey `(2)`, as in the reference.
- **Headline:** `--text-md`, bold, `--blue`, underline on hover. One line, ellipsis if long.
- **Excerpt:** first lines of the item text in `--text-2`, 13px, 2 lines max, with a trailing ellipsis. If the item has a one-line AI summary, show it first in bold `--text` ("**Summary:** ...").
- **Meta line:** `See more from` + the label as a blue link, e.g. `See more from Arts (509)`. Date and source in `--text-3`.
- **Actions** (appear on hover or when the item has keyboard focus): a star toggle, Mark as read, Add label.
- 16px vertical space between items; a 1px `--divider` between groups.
- **Keyboard:** `j`/`k` next/previous, `s` star, `m` mark read/unread, `o` or `Enter` open, `v` open original, `r` refresh. Show the focused item with a 3px `--blue` left border.

## Components

**Primary button (the one red action):** `--red` fill, 1px `--red-dark` border, white bold 11px uppercase text, `--radius`, padding 8px 20px. Hover: `--red-dark` fill. Only one primary button per screen ("Add feed", "Run pipe").

**Secondary button:** `--chrome` fill, 1px `--border`, `--text` text, `--radius`, padding 6px 12px. Hover: slightly darker (`#e8e8e8`) and `--text-3` border. Pressed: inset 1px shadow.

**Link:** `--blue`, no underline; underline on hover. Visited links keep `--blue`; read/unread is shown by weight, not by color.

**Text input and search:** white, 1px `--border`, `--radius`, 28px high. Focus: 1px `--blue` border plus a 1px inner `--blue` line.

**Menu / dropdown:** white, 1px `--border`, `--shadow-float`, rows at `--row-h` with `--blue-bg` hover.

**Dialog:** white, 1px `--border`, `--shadow-float`, a 56px title strip in `--chrome`, with buttons right-aligned at the bottom (primary on the right).

**Tag / label chip:** `--chrome` fill, 1px `--border`, `--radius`, 11px text.

**Counts:** grey parentheses in `--text-3`, never a badge or pill.

## Pipe canvas (React Flow)

The canvas keeps the same flat language, so it doesn't feel like a different app:

- **Canvas background:** `--bg` with a faint dotted grid in `#ececec`.
- **Box (node):** 180px wide, white, 1px `--border`, `--radius`, a **header strip** in `--chrome` (28px) with the box name in bold 13px and a small type glyph at the left. The body has the settings: inputs and selects at 28px high.
- **Plain boxes** (Fetch, Merge, Dedupe, Sort, Filter by keyword): neutral header.
- **AI boxes** (Summarize, Filter by meaning, Why you'd care, Read aloud): a 3px `--blue` strip along the top edge of the header and a small blue `AI` tag in the header. This is how you tell at a glance which steps use a model. The tag is text, so it works without color.
- **Selected box:** 1px `--blue` border plus a 2px `--blue` outer line (no glow).
- **Ports:** 8px squares on the left (in) and right (out) edges, white with a 1px `--text-3` border. Connected ports fill `--blue`.
- **Wires:** 1.5px `--text-3`; selected wire 2px `--blue`. Use smooth-step (right-angle) edges.
- **Run states** shown in the header, with an icon and a word: Running (spinner, `--blue`), Done (check, `--green`), Slow (clock, `--amber`), Error (warning triangle, `--red`, with the message under the header).

## States

| State | Look |
| --- | --- |
| Unread | Bold feed or headline text; unread count in grey parentheses |
| Read | Regular weight, `--text-2` headline |
| Starred | Filled `--yellow` star; unstarred is a grey outline star |
| Selected / focused | `--blue-bg` row (sidebar) or 3px `--blue` left border (item) |
| Hover | `#f0f0f0` row |
| Loading | Small inline spinner plus text `Loading...`; never block the whole page |
| Empty list | Centered `--text-2` message, e.g. "No unread items" with a link to All items |
| Error | `--red` text with a warning-triangle icon, and a plain-language message |
| Slow or stale | `--amber` clock icon plus the time, e.g. `4.2 s per item` |
| Disabled | `--text-3` text, no hover |

## Motion

Minimal. Allow a 100ms color transition on hover and a spinner for loading. No slide-ins, bounces or page transitions. Respect `prefers-reduced-motion` (turn off the spinner animation and show text instead).

## Accessibility

- Text contrast is at least 4.5:1: `--text` and `--text-2` on white pass; use `--text-3` only for non-essential counts and hints.
- `--blue` (#1155cc) on white passes AA for normal text.
- Every interactive element is reachable by keyboard with a visible focus outline: a 2px `--blue` ring with 2px offset.
- Touch targets are at least 32px on mobile; the 28px rows apply to desktop only.
- Do not rely on color alone: starred has a shape, errors have an icon and text, AI boxes have a text tag.

## Implementation notes

- Plain CSS variables from the token block, in one file. No hard-coded colors or sizes elsewhere.
- Do not use a component library's default theme. If you use one (Radix, shadcn), restyle it fully with these tokens.
- Style React Flow's nodes, edges, controls and minimap yourself.
- Icons: lucide-react line icons at 16px, one stroke weight. Do not copy Google's icons.

## References

Put screenshots in `public/` and note what to copy:

| File | Copy this |
| --- | --- |
| `public/sample.jpeg` | Overall layout, sidebar tree with counts, bold blue headlines, grey excerpts, red button |
| `public/reading-view.webp` | The article reading view |


