# JewelLAN UI/UX Design Brief

**Product feel:** calm, fast, precise, trustworthy, and practical for a jewellery counter
**Primary platform:** Windows desktop using Tkinter/ttk

## 1. Design objectives

- Make scanning and posting the fastest path for a cashier.
- Make price composition understandable enough for customer and accountant review.
- Keep destructive or irreversible actions deliberate and permission-aware.
- Use the same visual language across billing, inventory, returns, and reports.
- Remain readable on ordinary showroom monitors and usable with keyboard/scanner input.

## 2. Visual direction

Use a restrained premium-business palette: warm off-white surfaces, charcoal text, deep jewel-toned primary actions, muted borders, and semantic status colors. The interface should feel like dependable accounting software with subtle jewellery cues, not a decorative luxury storefront.

Recommended tokens:

| Token | Use |
|---|---|
| Surface | Main cards, forms, tables |
| Surface-muted | Helper text, labels, secondary metadata |
| Ink | Primary text and totals |
| Primary | Main actions such as Post, Save, Quote |
| Success | Posted, verified, in-stock, connected |
| Warning | Needs review, pending, setup incomplete |
| Danger | Cancel, destructive reversal, blocked conflict |
| Border | Card and table separation |

Existing shared helpers in `jewel_client/ui_theme.py` should remain the source for palette, cards, dividers, buttons, and status pills.

## 3. Typography and layout

- Use Segoe UI or the Windows system sans-serif for normal text.
- Use a semibold page title, short explanatory subtitle, and clear section labels.
- Use tabular-looking alignment for money, weights, rates, and totals.
- Keep primary content in cards with generous but efficient spacing.
- Use two-column layouts for workflows: work area on the left, summary/actions on the right.
- Tables must have stable column headings, sensible widths, and vertical scrolling.
- Never hide the final amount, payment mismatch, or conflict state below the fold.

## 4. Information hierarchy

Every page should answer, in order:

1. Where am I?
2. What record or task am I working on?
3. What is the current status?
4. What decision or input is needed next?
5. What will happen when I press the primary button?

## 5. Key screen briefs

### Login and connection

Show server discovery, manual address entry, connection state, certificate fingerprint verification, username, password, and a concise error message. The fingerprint confirmation must explain that a changed identity blocks login and requires administrator verification.

On first setup, show the one-time bootstrap-secret state separately from the password-change state. If company setup is incomplete after a previous session, take the user directly to the missing setup step without forcing another password change.

### Dashboard

Use a compact set of metrics: today’s sales, stock indicators, pending operational work, backup/data-health state, and Tally queue status. Keep it actionable; clicking a metric should open the related module.

### Billing counter

The barcode field receives initial focus. Show a “Ready for scanner” status pill. The item table is the primary work surface. Selecting a line reveals its complete calculation. The right panel contains customer, discount, old-gold, payments, amount due, and the primary Post action.

The primary action must be disabled or blocked when payment totals do not match, no lines exist, the quote is stale, or the user lacks permission. Display the server-calculated final total prominently.

Before posting, show the quote ID/version or a compact “quote current” status. A stale quote message must show the fresh quote and require the cashier to review the changed total before re-entering or confirming tender. If a write times out, replace the normal failure message with a persistent **Outcome unknown — Reconcile** state and expose Pending Posts after restart.

### Returns & Credit Notes

Use a guided three-step layout: find invoice → select returnable tags → quote/refund/post. Show original invoice context and return total together. The post button must explain that stock and accounting history will be reversed.

For every selected tag, require a visible disposition choice: saleable stock, quarantine/review, damaged, or scrap. Show the return request/reference status and use the same **Outcome unknown — Reconcile** treatment as sales. A duplicate-return conflict must explain which original tag is already involved in an effective credit note.

### Inventory and forms

Group fields into identity, physical properties, pricing, tax, location, and notes. Put tag/barcode, metal, purity, and weights near the top. Mark optional RFID EPC and certificate fields clearly. Validate weights and HUID inline.

Display weights in grams but identify the canonical milligram value in advanced/detail context. When an edit loses an `expected_version` race, preserve the user’s inputs and explain that the record changed on another workstation.

## 6. Interaction rules

- Enter submits scanner input; Tab moves predictably through forms.
- Escape closes a non-destructive dialog; it never silently discards edited business data.
- Double-clicking a table row opens its detail where supported.
- Long-running or network actions show progress or a pending state.
- Success feedback includes a durable reference number where one exists.
- Error messages state the operator action: correct input, retry, contact manager, or verify server.
- Error surfaces use structured categories/codes—validation, permission, connectivity/unknown outcome, server, quote stale, stock conflict, version conflict, and day closed—with a human-readable action.
- Confirmation dialogs are reserved for cancellation, posting, restore, and other materially consequential actions.

## 7. Accessibility and hardware

- Maintain keyboard-only access for every core workflow.
- Use visible focus indicators and sufficient contrast.
- Do not communicate status by color alone; pair colors with text/icons.
- Support USB HID scanners as keyboard input, with Enter suffix recommended.
- Keep scale and RFID input adapters out of the core screen logic; show their values as validated inputs with source/status where available.
- Make tables usable at common 100% Windows scaling and support the existing scale/scroll behavior.

## 8. Recovery and control screens

- **Pending Posts:** list unresolved sale, purchase, return, collection, and adjustment requests with timestamp, reference UUID, cart/operation summary, and Reconcile/Retry actions.
- **Day Close:** show business date/timezone, reconciliation checks, open unknown outcomes, payment/journal differences, stock-audit conflicts, Tally status, backup verification, and the evidence/lock action.
- **Backup:** show verified local copies and independent-copy status. Provide a clear link to the offline recovery utility instructions; do not present Restore as a live client action.
- **Certificate trust:** show current fingerprint, prior trust event, replacement reason/evidence, and explicit re-trust action.

## 9. UX acceptance checklist

- A new cashier can scan, understand, tender, and post a sale without training beyond the documented flow.
- A manager can identify why a return or cancellation is blocked.
- A user can distinguish a server/network error from a business validation conflict.
- Money, weights, rates, and tax values are never truncated or ambiguous.
- Every destructive action has a clear consequence and role-based protection.
- No timeout, stale quote, duplicate operation, day-close lock, or version conflict is represented as an ambiguous generic failure.
