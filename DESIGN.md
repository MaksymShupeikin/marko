---
version: 1.0
name: Marko-Design-System
description: |
  Comprehensive design system for Marko — an engineering-grade B2B auto parts
  intelligence, pricing analytics, and catalog ingestion platform.
  Synthesizes Vercel's stark precision and stacked elevation, Resend's high-contrast
  editorial confidence and atmospheric depth, Linear's dense data ergonomics,
  and Raycast's keyboard-driven search velocity.

colors:
  # Light Theme (Canvas & Surfaces)
  canvas: "#ffffff"
  canvas-soft: "#f8fafc"
  canvas-soft-2: "#f1f5f9"
  surface-card: "#ffffff"
  surface-elevated: "#ffffff"
  surface-inset: "#f1f5f9"
  
  # Dark Theme (Canvas & Surfaces)
  dark-canvas: "#000000"
  dark-canvas-soft: "#09090b"
  dark-surface-card: "#0f0f12"
  dark-surface-elevated: "#18181b"
  dark-surface-inset: "#050507"

  # Core Inks & Text
  primary: "#0f172a"
  on-primary: "#ffffff"
  ink: "#0f172a"
  body: "#475569"
  mute: "#94a3b8"
  ash: "#cbd5e1"
  disabled: "#e2e8f0"
  
  dark-ink: "#f8fafc"
  dark-body: "rgba(248,250,252,0.85)"
  dark-mute: "#94a3b8"

  # Dividers & Hairlines (1px precision)
  hairline: "#e2e8f0"
  hairline-strong: "#cbd5e1"
  hairline-focus: "#0f172a"
  dark-hairline: "rgba(255,255,255,0.08)"
  dark-hairline-strong: "rgba(255,255,255,0.16)"
  dark-hairline-focus: "#ffffff"

  # Brand & Actions (Vercel/Raycast Cobalt)
  brand: "#0070f3"
  brand-deep: "#0051bb"
  brand-soft: "#eff6ff"
  brand-glow: "rgba(0,112,243,0.18)"

  # Automotive & Market Semantics
  success: "#10b981"          # Best price / In stock / Original (OE)
  success-soft: "#ecfdf5"
  success-glow: "rgba(16,185,129,0.18)"
  
  warning: "#f59e0b"          # Median price / Aftermarket replacement
  warning-soft: "#fffbeb"
  warning-glow: "rgba(245,158,11,0.18)"
  
  error: "#ef4444"            # Max price / Out of stock / Sync error
  error-soft: "#fef2f2"
  error-glow: "rgba(239,68,68,0.18)"

  # Platform Integrations
  prom-orange: "#ff5722"      # Prom.ua connector
  prom-soft: "#fff3e0"
  avto-blue: "#0284c7"        # avto.pro lookup
  avto-soft: "#f0f9ff"

typography:
  # Display & Headlines (Geist / Inter)
  display-xl:
    fontFamily: "Geist, Inter, system-ui, sans-serif"
    fontSize: 32px
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: -1.2px
  display-lg:
    fontFamily: "Geist, Inter, system-ui, sans-serif"
    fontSize: 24px
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: -0.7px
  heading-md:
    fontFamily: "Geist, Inter, system-ui, sans-serif"
    fontSize: 18px
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: -0.3px
  heading-sm:
    fontFamily: "Geist, Inter, system-ui, sans-serif"
    fontSize: 15px
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: -0.15px

  # Body & UI
  body-lg:
    fontFamily: "Geist, Inter, system-ui, sans-serif"
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.5
  body-md:
    fontFamily: "Geist, Inter, system-ui, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.45
  body-sm:
    fontFamily: "Geist, Inter, system-ui, sans-serif"
    fontSize: 12.5px
    fontWeight: 400
    lineHeight: 1.4
  button-md:
    fontFamily: "Geist, Inter, system-ui, sans-serif"
    fontSize: 13.5px
    fontWeight: 500
    lineHeight: 1.2
  button-sm:
    fontFamily: "Geist, Inter, system-ui, sans-serif"
    fontSize: 12.5px
    fontWeight: 500
    lineHeight: 1.2

  # Technical Monospace Layer (Geist Mono / JetBrains Mono)
  oem-code:
    fontFamily: "Geist Mono, JetBrains Mono, monospace"
    fontSize: 13px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: 0.2px
  price-display:
    fontFamily: "Geist Mono, JetBrains Mono, monospace"
    fontSize: 15px
    fontWeight: 600
    lineHeight: 1.2
  caption-mono:
    fontFamily: "Geist Mono, JetBrains Mono, monospace"
    fontSize: 11.5px
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: 0.3px
  hotkey-badge:
    fontFamily: "Geist Mono, JetBrains Mono, monospace"
    fontSize: 11px
    fontWeight: 500
    lineHeight: 1.0

rounded:
  none: 0px
  xs: 4px       # Hotkeys, tiny tags
  sm: 6px       # Inputs, table chips, segmented sub-pills
  md: 8px       # Buttons, toolbars, list cards
  lg: 10px      # Feature cards, dropzone containers
  xl: 14px      # Main surface panels, modal windows
  full: 9999px  # Status pills, search omnibar wrapper

spacing:
  xxs: 2px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 20px
  2xl: 24px
  3xl: 32px
  4xl: 48px

components:
  # Omnibar & Search
  search-omnibar:
    backgroundColor: "{colors.surface-card}"
    borderColor: "{colors.hairline}"
    borderFocusColor: "{colors.brand}"
    rounded: "{rounded.lg}"
    height: 48px
    padding: "0px {spacing.md}"
    typography: "{typography.body-md}"

  # Mode Switcher Segmented Bar
  segmented-track:
    backgroundColor: "{colors.canvas-soft-2}"
    borderColor: "{colors.hairline}"
    rounded: "{rounded.md}"
    padding: "{spacing.xxs}"
    height: 38px
  segmented-item-active:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    shadow: "0 1px 2px rgba(0,0,0,0.06)"

  # Dropzone File Import
  dropzone-card:
    backgroundColor: "{colors.canvas-soft}"
    borderStyle: "dashed"
    borderColor: "{colors.hairline-strong}"
    borderHoverColor: "{colors.brand}"
    rounded: "{rounded.lg}"
    padding: "{spacing.3xl} {spacing.xl}"

  # Price Spectrum Bar
  price-spread-bar:
    backgroundColor: "{colors.canvas-soft-2}"
    rounded: "{rounded.md}"
    padding: "{spacing.md} {spacing.lg}"
    minColor: "{colors.success}"
    medianColor: "{colors.ink}"
    maxColor: "{colors.error}"

  # Technical OEM Badges
  oem-chip:
    backgroundColor: "{colors.canvas-soft-2}"
    textColor: "{colors.ink}"
    borderColor: "{colors.hairline}"
    typography: "{typography.oem-code}"
    rounded: "{rounded.xs}"
    padding: "3px 7px"

  # Primary Actions
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button-md}"
    rounded: "{rounded.md}"
    height: 38px
    padding: "0px {spacing.lg}"

  button-secondary:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    borderColor: "{colors.hairline}"
    typography: "{typography.button-md}"
    rounded: "{rounded.md}"
    height: 38px
    padding: "0px {spacing.lg}"
---

# Marko Design System

## 1. Overview & Core Philosophy

**Marko** is an engineering-grade SaaS platform built for automotive parts businesses, catalog managers, and pricing analysts. It lives at the intersection of:
1. **Vercel's Precision & Stark Surfaces**: 1px hairline borders, near-white canvas (`#FAFAFA` / `#FFFFFF`), strict 4px grid rhythm, and stacked micro-shadows.
2. **Resend's High-Contrast Typographic Rigor**: High-contrast black/white CTA anchors, crisp status dots, clean badge semantics, and atmospheric glows for accent moments.
3. **Raycast's Keyboard-First Search Ergonomics**: Instant search Omnibar, integrated hotkey indicators (`Enter ↵`, `Tab ⇥`), and compact segmented pill controllers.
4. **Linear's Information Density**: Clean tabular rows, mono-spaced OEM identifiers, and dense pricing spreads that maximize screen efficiency.

---

## 2. Color System & Semantic Tokens

### 2.1 Surfaces & Canvas (Dual-Theme)

| Token | Light Mode | Dark Mode | Role |
| :--- | :--- | :--- | :--- |
| `canvas` | `#FFFFFF` | `#000000` | Pure background canvas / modal cards |
| `canvas-soft` | `#F8FAFC` | `#09090B` | Default page background tone |
| `canvas-soft-2` | `#F1F5F9` | `#18181B` | Segmented tracks, chip backgrounds, inset panels |
| `surface-card` | `#FFFFFF` | `#0F0F12` | Elevated card surfaces, search panels, product tiles |
| `hairline` | `#E2E8F0` | `rgba(255,255,255,0.08)` | 1px clean separation dividers and borders |
| `hairline-strong` | `#CBD5E1` | `rgba(255,255,255,0.16)` | Active card borders and dropzone dashed outlines |

### 2.2 Automotive Pricing Semantics

* **`success` (`#10B981`)**: Minimum (Best) competitor price, Original (OE) quality status, and active synchronization.
* **`warning` (`#F59E0B`)**: Median market price, aftermarket analogue parts, and pending background tasks.
* **`error` (`#EF4444`)**: Maximum competitor price, sync failures, or invalid OEM formats.
* **`brand` (`#0070F3`)**: Primary actions, focus rings, and external marketplace links (Prom / avto.pro).

---

## 3. Typography & Technical Monospace Layer

The system uses a strict **two-family typography hierarchy**:

1. **Narrative & UI Layer (`Geist` / `Inter`)**:
   * Clean geometric sans with slight negative letter-spacing for headlines (`-0.7px` to `-1.2px`).
   * Sentence-case everywhere. Display weight ceiling is **600** (never 700+).
2. **Technical & Data Layer (`Geist Mono` / `JetBrains Mono`)**:
   * **OEM Numbers & Article Codes** (`W914/2`, `7701478505`, `OC 90`) MUST always render in monospace with `weight: 600` and letter-spacing `+0.2px`.
   * **Prices & Currency** (`1 250 ₴`, `48.50 $`) MUST render in monospace for vertical tabular alignment.
   * **Keyboard Shortcuts** (`↵`, `ESC`, `⌘K`) render inside dedicated `hotkey-badge` containers.

---

## 4. Component Architecture & Specifications

### 4.1 Mode Selector (`segmented-track`)
Replaces bulky radio cards with a high-density macOS / Raycast-style segmented controller.
* **Height**: 38px.
* **Background**: `canvas-soft-2` with 1px `hairline` border.
* **Active Indicator**: `surface-card` with `rounded: 6px` and micro-shadow (`0 1px 2px rgba(0,0,0,0.06)`).
* **Modes**:
  1. `🛒 Prom.ua` — Store Catalog URL Sync
  2. `📄 XLSX Файл` — Batch Excel Ingestion
  3. `⚡ Поиск OEM` — Instant avto.pro Price Intelligence

---

### 4.2 Search Omnibar (`search-omnibar`)
Power-user command bar for part numbers and aftermarket cross-codes.
* **Structure**:
  ```text
  [ 🔍 Icon ] [ OEM Input Field: "W914/2..." ] [ Brand Pill: "MANN ▾" ] [ Keycap: "Enter ↵" ] [ ⚡ Найти цены ]
  ```
* **Quick-Test Chips**: Clickable sample OEM badges (`W914/2 MANN`, `OC90 KNECHT`, `7701478505 RENAULT`) placed directly below for 1-click test searches.

---

### 4.3 Interactive Dropzone (`dropzone-card`)
A tactile drag-and-drop ingestion container for Prom.ua / Excel catalog files.
* **Border**: 1px dashed `hairline-strong` (transitions to `brand` with soft glow on drag-over).
* **Background**: `canvas-soft`.
* **Content**:
  * Format badge: `XLSX · До 50 МБ`.
  * Primary action: `Выбрать файл на диске` + drag & drop hint.
  * Columns detected badge: `✓ Название, Цена, Бренд, OEM, Наличие`.

---

### 4.4 Competitor Price Spread Bar (`price-spread-bar`)
A single horizontal spectrum visualization showing market price distribution:
```text
┌─────────────────────────────────────────────────────────────────────────────┐
│  МИН: 180 ₴ (Лучшая)   ══════════●══════════════●══════════    МАКС: 340 ₴  │
│  🟢 АвтоПартс Киев          Медиана: 245 ₴                     🔴 Exist     │
└─────────────────────────────────────────────────────────────────────────────┘
```
* **Min Price**: Highlighted with `success` (`#10B981`).
* **Median Price**: Highlighted with `ink` (`#0F172A`).
* **Max Price**: Displayed in `body` or `error` (`#EF4444`).

---

## 5. Elevation & Stacked Shadows

Marko rejects generic heavy Material blur shadows in favor of **stacked crisp offsets**:

* **Level 0 (Flat)**: `border: 1px solid hairline` (cards, inputs).
* **Level 1 (Card Rest)**: `0 1px 2px rgba(0,0,0,0.04), 0 0 0 1px hairline`.
* **Level 2 (Hover / Active)**: `0 4px 12px -2px rgba(0,0,0,0.08), 0 0 0 1px hairline-strong`.
* **Level 3 (Modal / Drawer)**: `0 8px 24px -4px rgba(0,0,0,0.12), 0 0 0 1px hairline-strong`.

---

## 6. Do's and Don'ts

### Do
* Use `Geist Mono` for all OEM numbers, article codes, and currency amounts.
* Use 1px hairlines (`#E2E8F0`) with subtle contrast rather than 2px+ thick outlines.
* Keep buttons compact (38px height) with radius `8px`.
* Show keyboard shortcut hints (`Enter ↵`, `Esc`) on actionable inputs.
* Provide quick-test chips for instant demo workflows.

### Don't
* Don't use Material 3 rounded bubble buttons (24px+ radius) or pastel tonal washes.
* Don't render OEM part numbers in standard proportional sans-serif.
* Don't use emoji as UI icons — use clean SVGs / Lucide / Material Symbols (rounded stroke).
* Don't hide file requirements — always show accepted `.xlsx` columns and formats.
* Don't let search results jump abruptly — use smooth 150–200ms transitions (`easeInOut`).
