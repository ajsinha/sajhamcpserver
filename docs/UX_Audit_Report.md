# SAJHA MCP Server v4.0.0 — UX Audit Report

**Prepared by:** UX Design Lead + Behavioral Psychologist  
**Date:** May 12, 2026  
**Scope:** 42 screens, 4 themes, complete navigation flow  
**Objective:** World-class UX assessment with actionable recommendations

---

## Executive Summary

SAJHA has strong bones — 42 functional screens, property-driven configuration, 4 themes, and comprehensive feature coverage. The landing page sets a premium bar. However, the internal application screens don't consistently meet that bar. The gap isn't in functionality — it's in *how the functionality feels to use*.

**Overall Score: 6.5/10** (Functional but not world-class)

The path to 10/10 requires work in three domains:

1. **Cognitive Load Reduction** — too many screens require the user to hold context in their head
2. **Emotional Design** — the UI tells users what they *can* do, but rarely rewards them for doing it
3. **Consistency & Polish** — small inconsistencies accumulate into a feeling of roughness

---

## Part 1: Psychologist's Assessment

### 1.1 Cognitive Load Analysis

**Finding: Information overload on key screens**

The Help page (898 lines) presents everything at once — tutorials, API reference, tool groups, glossary. Human working memory holds 4±1 chunks. This page presents 20+.

The AI Settings page has 5 tabs with dense forms. Users must understand providers, models, preferences, semantic search, AND usage in one place.

**Recommendation:** Progressive disclosure. Show the minimum needed, reveal complexity on demand. Help page should open with 4-6 cards ("What do you want to do?") that expand into detail. AI Settings should have a guided "Get Started" flow for first-time setup.

### 1.2 Decision Fatigue

**Finding: Too many equal-weight choices**

The MCP Studio dropdown offers 9 creator types with no guidance on which to choose. The tool catalog shows 497 tools in a flat list. The Composite Builder asks users to pick "Sibling" or "Parent-Child" without explaining the tradeoff.

**Recommendation:** Default paths. "Most users start here →" labels. Smart defaults pre-filled. For Composite Builder: show a 1-sentence use case next to each arrangement type ("Sibling: run 3 market data tools at once" / "Parent-Child: get a list, then drill into each item").

### 1.3 Trust & Confidence

**Finding: Insufficient feedback loops**

When a user saves a tool in MCP Studio, they get a green banner — but no confirmation of what was saved, where it went, or how to find it. When a composite tool is saved, there's no "preview what this will do" step.

The tool execution page shows raw JSON output with no interpretation. A user who runs `yahoo_quote` for AAPL gets a wall of JSON — no summary like "Apple Inc. — $198.42 (+1.2% today)".

**Recommendation:** Every destructive or creative action needs a 3-part feedback loop: (1) confirmation of what happened, (2) link to the result, (3) suggested next step. Tool execution should show a human-readable summary ABOVE the raw JSON.

### 1.4 Anxiety Triggers

**Finding: Irreversible actions lack safeguards**

Deleting an API key shows a `confirm()` browser dialog — the least reassuring UI pattern. Disabling a tool used by production agents has no warning about downstream impact. The plugin load/unload API has no "are these tools currently in use?" check.

**Recommendation:** Inline confirmation with context. "This API key is used by 3 active scripts. Deleting it will break their access. Type the key name to confirm." Show impact before the action, not just "Are you sure?"

### 1.5 Flow States

**Finding: No onboarding flow**

A new user logs in and sees the dashboard — but has no guided path. They don't know whether to browse tools, create one, or configure an LLM provider. The dashboard's "Quick Actions" panel helps but doesn't prioritize.

**Recommendation:** First-login onboarding: 3-step wizard. "Welcome to SAJHA → Browse 497 tools → Create your first tool → Connect an LLM provider." Track completion. Show a subtle progress indicator on the dashboard until onboarding is done.

---

## Part 2: UX Designer's Assessment

### 2.1 Visual Hierarchy & Layout

**Finding: Inconsistent content density**

The Dashboard has good information density — metric cards, quick actions, status panel. But the Reports page is sparse (163 lines), the AI Settings page is dense (496 lines), and the Tool Schema page is text-heavy with no visual structure beyond raw JSON.

**Recommendation:** Standardize page layouts into 3 templates:
- **Overview pages** (Dashboard, Reports): metric cards + chart + table
- **List pages** (Tools, Prompts, API Keys): filter bar + card/table toggle + pagination
- **Detail pages** (Tool Schema, Prompt Detail): header card + tabbed content

### 2.2 Navigation & Wayfinding

**Strengths:**
- Breadcrumbs exist (58 references) ✓
- Back buttons on detail pages (22 references) ✓
- Consistent navbar across all screens ✓

**Weaknesses:**
- No "you are here" indicator — the active nav item doesn't highlight on many pages
- Studio has 9 sub-pages but no sidebar or step indicator
- Help/About/Docs are in the right side of the navbar, separated from related content

**Recommendation:**
- Add active state to navbar items (`.nav-link.active` style based on current URL)
- Studio should have a left sidebar showing all creator types with the current one highlighted
- Move Help to a floating "?" button (bottom-right corner) available on every page

### 2.3 Micro-interactions & Animation

**Finding: Almost zero micro-interactions**

Card hover lift exists (CSS `transform: translateY(-2px)`) — that's it. No button press feedback, no loading skeletons, no transition between views, no success animations.

World-class UX uses micro-interactions to:
- Confirm actions (button ripple, checkmark animation)
- Indicate progress (skeleton screens, progress bars)
- Reward completion (confetti on first tool created, subtle pulse on save)
- Guide attention (gentle bounce on CTAs, slide-in for new content)

**Recommendation (Priority):**
- Add CSS `transition` to all buttons (scale down on `:active`)
- Loading skeleton placeholders instead of "Loading..." text
- Smooth transitions when switching between table/card view
- Subtle slide-in animation for inline forms (Add Provider, Add Model)

### 2.4 Empty States

**Finding: Empty states are afterthoughts**

"No composite tools yet" — plain text with no action. "No tool usage data yet. Execute some tools to see analytics." — tells the user what to do but doesn't make it easy.

**Recommendation:** Every empty state should have: (1) an illustration or large icon, (2) a 1-line explanation, (3) a primary action button. Example: "No composite tools yet" → Large boxes icon + "Chain multiple tools into one call" + [Create Your First Composite] button.

### 2.5 Responsive Design

**Finding: Adequate but not mobile-first**

84 responsive breakpoints across templates. The layout works on tablets but several forms break on mobile (Composite Builder's 3-column row, AI Settings' 4-column preferences row). The landing page is fully responsive.

**Recommendation:**
- AI Settings preference row: stack to 2-column on medium, 1-column on small
- Tool execution page: full-width JSON panel on mobile
- Dashboard metric cards: 2×2 grid on mobile (currently 4-across breaks at small sizes)

### 2.6 Accessibility (A11y)

**Findings:**
- 49 ARIA attributes (low for 42 screens — should be 200+)
- Only 1 `tabindex` / keyboard navigation attribute
- No skip-to-content link
- No focus-visible styling for keyboard users
- Form labels exist but some lack `for` attributes
- Color alone used to indicate status (red/green badges without text)

**Recommendation (Compliance):**
- Add `aria-label` to all icon-only buttons
- Add `role="status"` to dynamic content areas (tool execution results)
- Add skip-to-content link in base.html
- Add `:focus-visible` outline styling to all interactive elements
- Ensure all color indicators also have text/icon alternatives

### 2.7 Typography

**Finding: Inconsistent type scale**

Some pages use `h1.h3` (Bootstrap utility), some use actual `<h1>`, some use custom sizes in inline styles. Font weights vary between `500`, `600`, `700`, `bold` across templates.

**Recommendation:** Define 5 type styles and use them everywhere:
- **Page title**: 1.5rem / 700 / heading color
- **Section header**: 1.1rem / 600 / heading color
- **Body**: 0.9rem / 400 / text color
- **Caption/Label**: 0.8rem / 600 / muted color / uppercase
- **Code**: 0.85rem / JetBrains Mono / monospace

### 2.8 Iconography

**Finding: Over-reliance on Bootstrap Icons**

70 uses of `bi-book`, 55 of `bi-check-circle-fill`, 43 of `bi-info-circle`. The same icons are reused for different purposes (bi-tools for both the Tools nav item and the tool count metric). No custom icons that create brand identity.

**Recommendation:** Create 5-6 custom SVG icons for key SAJHA concepts: MCP protocol, tool, composite, provider, transport. Use consistently. Reserve Bootstrap Icons for generic actions (save, delete, search).

---

## Part 3: Screen-by-Screen Findings

### Landing Page ★★★★★
**Verdict: Excellent.** Sets the quality bar. Atmospheric gradients, glass-morphism, clear value proposition, strong CTA. No changes needed.

### Login Page ★★★★☆
**Verdict: Strong.** Matches landing aesthetic. Add "Forgot password?" link (even if placeholder). Add subtle animation on the card (fade-in on load).

### Dashboard ★★★★☆
**Verdict: Good.** Metric cards, quick actions, status panel — well-organized. Missing: a trend sparkline in metric cards (tools executed over last 7 days), a "recent activity" feed showing last 5 tool executions.

### Tools List ★★★☆☆
**Verdict: Functional.** Card/table toggle is good. Missing: category filter sidebar (FMP, FRED, Yahoo, etc.), provider logos/avatars on cards, a "favorites" or "recently used" section at top.

### Tool Schema ★★★☆☆
**Verdict: Dense.** Raw JSON dominates. Missing: visual parameter form (like Swagger UI), "Try it" button next to schema, copy-as-curl button, example request/response.

### Tool Execute ★★★☆☆
**Verdict: Raw.** JSON output with no interpretation. Missing: human-readable result summary, execution time display, "Run Again" button with pre-filled params, result history.

### AI Settings ★★★☆☆
**Verdict: Complex.** 5 tabs is a lot. Provider cards look good. Missing: setup wizard for first-time users, provider health dashboard (green/red dots showing real-time status), token usage chart.

### Composite Builder ★★★★☆
**Verdict: Well-designed.** Two-panel layout (list + form) works well. Missing: visual flow diagram showing how tools connect, drag-and-drop step reordering, live schema preview as steps are added.

### MCP Studio ★★★☆☆
**Verdict: Powerful but intimidating.** 9 creator types in a flat list. Missing: "Recommended" badge on Python and REST creators (most common), template library (pre-built tool configs to start from), inline preview of what the tool will look like in the catalog.

### Reports ★★☆☆☆
**Verdict: Underwhelming.** Only tables, no charts (despite Chart.js being mentioned in docs). Missing: line/bar charts for trends, date range picker, export to CSV/PDF buttons, comparison view.

### Monitoring ★★★☆☆
**Verdict: Data-rich.** Good tables with sorting. Missing: real-time sparklines, alert indicators, time-range selector, export.

### Help ★★★☆☆
**Verdict: Comprehensive but overwhelming.** 898 lines of content on one page. Missing: search within help, collapsible sections (show headings only, expand on click), "Was this helpful?" feedback on each section.

### About ★★★★☆
**Verdict: Professional.** Good capability cards, stats. Minor: the comparison table with competitors adds credibility but may need updating.

---

## Part 4: Priority Recommendations

### Tier 1 — Quick Wins (1-2 days, high impact)

| # | Item | Impact |
|---|------|--------|
| 1 | **Active nav highlighting** — add `.active` class to current page's nav link | Wayfinding |
| 2 | **Button press feedback** — add `:active { transform: scale(0.97) }` to all `.btn` | Responsiveness |
| 3 | **Empty state CTAs** — add action buttons to every "No X yet" message | Engagement |
| 4 | **Form autofocus** — first input on every form gets `autofocus` | Efficiency |
| 5 | **Inline form animations** — `slideDown` when Add Provider/Model forms appear | Polish |
| 6 | **Skip-to-content link** — accessibility compliance | A11y |
| 7 | **Focus-visible outlines** — `:focus-visible` styling for keyboard users | A11y |
| 8 | **Tool execution summary** — parse JSON result, show 1-line human summary above raw JSON | Comprehension |

### Tier 2 — Medium Effort (1 week, significant impact)

| # | Item | Impact |
|---|------|--------|
| 9 | **Reports charts** — add Chart.js line/bar charts to reports dashboard | Insight |
| 10 | **Tool category sidebar** — filter tools by provider/category on tools list | Discovery |
| 11 | **Onboarding wizard** — 3-step first-login flow | Adoption |
| 12 | **Help search** — add search-within-help functionality | Self-service |
| 13 | **Loading skeletons** — replace "Loading..." text with skeleton placeholders | Perceived speed |
| 14 | **Dashboard sparklines** — trend mini-charts in metric cards | Awareness |
| 15 | **Studio sidebar** — replace dropdown with persistent left sidebar for creators | Navigation |

### Tier 3 — Strategic (2-4 weeks, transformative)

| # | Item | Impact |
|---|------|--------|
| 16 | **Swagger-style tool tester** — visual form for tool params instead of raw JSON | Accessibility |
| 17 | **Composite visual flow** — drag-and-drop diagram showing tool chain | Comprehension |
| 18 | **Real-time monitoring dashboard** — WebSocket-fed live metrics | Operations |
| 19 | **Mobile-responsive overhaul** — test and fix all 42 screens on 375px viewport | Reach |
| 20 | **Custom icon set** — 8-10 SVG icons for SAJHA concepts | Brand identity |
| 21 | **Dark mode polish pass** — screen-by-screen review of every dark theme element | Consistency |
| 22 | **Keyboard shortcuts** — Cmd+K search, Cmd+/ help, Cmd+T new tool | Power users |

---

## Part 5: The Gap to World-Class

The current SAJHA UI is a *capable admin panel*. World-class tools (Vercel Dashboard, Linear, Stripe Dashboard, Datadog) share traits SAJHA doesn't yet have:

1. **Instant feedback** — every click produces a visible response within 100ms
2. **Contextual intelligence** — the UI adapts to what you've done and suggests what to do next
3. **Narrative flow** — screens tell a story (here's what happened → here's what it means → here's what to do)
4. **Delightful details** — transitions, illustrations, copy that has personality
5. **Zero dead ends** — every error, empty state, and edge case has a designed path forward

SAJHA's landing page achieves #4 and #5. The internal screens need #1, #2, and #3.

**The single highest-impact change:** Transform the tool execution page from "paste JSON, see JSON" into "fill a form, see a result with a human sentence explaining what it means." This is the page users visit most, and it currently feels like a developer debugging tool, not a product.

---

*Report prepared for SAJHA MCP Server v4.0.0*  
*42 screens audited · 4 themes evaluated · 22 recommendations across 3 priority tiers*  
*Copyright © 2025-2030 Ashutosh Sinha. All rights reserved.*
