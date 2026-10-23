# Console design system — Phase 1

The existing vanilla HTML/CSS/JavaScript console uses a neutral dark palette and shared
semantic tokens in `triager/static/style.css`. No remote font requests are required.
Keep later design phases on the dashboard design PR; this phase changes presentation only.

| Foundation | Tokens / convention |
| --- | --- |
| Surfaces | `--bg`, `--panel`, `--surface-raised`, `--surface-inset`, `--surface-hover` |
| Borders | `--line`, `--border-strong` |
| Text | `--text`, `--text-secondary`, `--muted` |
| Status | `--green` (success), `--orange` (warning), `--error` (failure), each with a background and border token |
| Source labels | `--info`, `--info-bg` |
| Focus | `--focus`, a two-pixel outline with three-pixel offset |
| Spacing | 4, 8, 12, 16, 20, 24, 32, 36px via `--space-*` |
| Radius | 6px controls, 10px cards, 12px dialogs; pill radius for statuses |
| Elevation | `--shadow-card`, `--shadow-popover`, `--shadow-dialog` |
| Type | 15px body, 14px content/controls, 13px secondary labels, 16px section headings, 24px titles, 32px metrics |

Use `--sans` for interface text and `--mono` for metric numbers, code and timestamps.
Numbers use tabular figures; body line height is 1.6. Reserve 12px for exceptional compact
annotations rather than normal content. Metrics stay 32px on narrow screens.
Chart labels use the same muted, warning, border and success tokens as the rest of the UI.

Buttons, inputs and selects share a minimum 36px height. Secondary and text buttons retain
their hierarchy on hover, disabled buttons stay disabled visually, and interactive elements
have visible keyboard focus. Tooltips use an elevated dark surface with readable text;
status meanings remain written out rather than conveyed through color alone. Existing
keyboard, tooltip, modal, sorting, simulation and approval behavior is preserved.

## Validation

- JavaScript syntax check and `make build` (lint, formatting, wheel and packaged assets).
- CSS parsed without errors; all 47 referenced custom properties resolve.
- Shared text/background contrast: primary 14.84:1, muted 7.64:1, success 7.56:1,
  warning 7.93:1, failure 6.90:1, source badge 7.95:1. These are token-pair checks,
  not a claim of a complete accessibility audit.
- Browser review of dashboard and incident dialog at desktop and 375px viewport:
  no document overflow, 15px body, 32px metrics; existing table scrolls horizontally
  within its container. Review retains its timeline, evidence, trace and approval controls.

No backend, endpoint, dependency, application version or release tag changes are included.
