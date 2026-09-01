---
name: Nexus Operational System
colors:
  surface: '#121414'
  surface-dim: '#121414'
  surface-bright: '#383939'
  surface-container-lowest: '#0d0e0f'
  surface-container-low: '#1b1c1c'
  surface-container: '#1f2020'
  surface-container-high: '#292a2a'
  surface-container-highest: '#343535'
  on-surface: '#e3e2e2'
  on-surface-variant: '#c0c7d6'
  inverse-surface: '#e3e2e2'
  inverse-on-surface: '#2f3031'
  outline: '#8a919f'
  outline-variant: '#404753'
  surface-tint: '#a5c8ff'
  primary: '#a5c8ff'
  on-primary: '#00315e'
  primary-container: '#2492ff'
  on-primary-container: '#002a53'
  inverse-primary: '#005fae'
  secondary: '#d5baff'
  on-secondary: '#42008a'
  secondary-container: '#600fc0'
  on-secondary-container: '#caa9ff'
  tertiary: '#ffb688'
  on-tertiary: '#512400'
  tertiary-container: '#e37103'
  on-tertiary-container: '#471e00'
  error: '#f5222d'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#d4e3ff'
  primary-fixed-dim: '#a5c8ff'
  on-primary-fixed: '#001c3a'
  on-primary-fixed-variant: '#004785'
  secondary-fixed: '#ecdcff'
  secondary-fixed-dim: '#d5baff'
  on-secondary-fixed: '#270057'
  on-secondary-fixed-variant: '#5e08bd'
  tertiary-fixed: '#ffdbc7'
  tertiary-fixed-dim: '#ffb688'
  on-tertiary-fixed: '#311300'
  on-tertiary-fixed-variant: '#733600'
  background: '#121414'
  on-background: '#e3e2e2'
  surface-variant: '#343535'
  success: '#52c41a'
  warning: '#faad14'
  background-deep: '#141414'
  background-elevated: '#1f1f1f'
  border-subtle: '#303030'
  ks-executable: '#13c2c2'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-md:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  code-md:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 16px
  margin-page: 24px
  sidebar-width: 240px
  header-height: 56px
---

## Brand & Style

The design system is a high-utility, technical framework designed for Game Management and Operations. It prioritizes information density, operational safety, and clear system feedback over decorative elements. The brand personality is **Technical, Utilitarian, and Reliable**, serving as a "Mission Control" for developers and QA engineers.

The system employs a **Corporate / Modern** aesthetic with **Minimalist** influences to maximize cognitive bandwidth for complex data tasks. It uses a rigorous grid, subtle tonal layering, and highly legible typography to ensure that critical status changes are never missed. Every visual element serves a functional purpose, with intentional "design friction" applied to high-risk operations to prevent catastrophic errors in live environments.

## Colors

The color system is optimized for a high-contrast **Dark Mode** by default to reduce eye strain during long operational sessions, though it maintains a robust **Light Mode** counterpart. 

- **Primary (Admin Blue):** Used for primary actions, active navigation states, and focus indicators.
- **Operational Status:** Success (Green), Warning (Amber), and Error (Red) colors are reserved strictly for system feedback and execution states. They must always be accompanied by text labels or icons for accessibility.
- **Neutral Scale:** A comprehensive gray scale is used for structural UI—borders, backgrounds, and secondary text—to create a clear visual hierarchy between the interface and the data content.
- **Special States:** Specific colors are allocated for platform-specific states, such as `ks-executable` for specific API permissions and `secondary` (Purple) for administrative-only features.

## Typography

The typography system focuses on clarity at small scales to support data density. **Inter** is the primary typeface for its exceptional legibility and neutral character. For technical content—including GM commands, JSON payloads, and Git diffs—**JetBrains Mono** is used to ensure character distinction (e.g., 0 vs O).

- **Headlines:** Used sparingly for page titles and section headers to maintain vertical space.
- **Body Text:** The standard 14px size is the workhorse of the system. 12px is used for metadata and supplementary info.
- **Code/Monospace:** Essential for all command inputs and script blocks.
- **Labels:** Uppercase labels with slight tracking are used for status tags and category headers to provide visual differentiation from body content.

## Layout & Spacing

The layout is a **Fixed Sidebar + Top Header** structure, designed to provide a persistent frame for global controls. The main content area utilizes a **Fluid Grid** system that prioritizes horizontal space for dense data tables.

- **Grid Model:** 12-column layout on desktop, reflowing to 4-columns or a single column on mobile.
- **Rhythm:** An 8px (base unit) grid is used for component alignment, with a 4px sub-unit for tight data clusters inside cards and tables.
- **Responsive Behavior:** 
  - **Desktop (>1200px):** Multi-column card grids and full data tables.
  - **Tablet (768px - 1199px):** Sidebar collapses to icons; cards stack into two columns.
  - **Mobile (<767px):** Single column layout. Sidebar becomes a drawer. Horizontal scrolling is permitted for data tables to preserve cell integrity.

## Elevation & Depth

Visual hierarchy is established through **Tonal Layers** rather than heavy shadows, ensuring the UI feels "flat" and efficient.

- **Level 0 (Base):** Deep neutral background (#141414).
- **Level 1 (Cards/Containers):** Elevated background (#1f1f1f) with a subtle 1px border (#303030).
- **Level 2 (Popovers/Tooltips):** Slightly lighter tonal shift with a soft ambient shadow (10% opacity) for separation.
- **Level 3 (Modals):** High-contrast background with a 60% opacity dark mask. 
- **Interactions:** Hover states are indicated by a subtle brightening of the surface color or a 1px primary-colored border.

## Shapes

The shape language is **Soft (0.25rem)**, providing a clean, professional look that doesn't feel overly playful or aggressive. 

- **Inputs & Buttons:** 4px (0.25rem) radius.
- **Cards & Modals:** 8px (0.5rem) radius for distinct containment.
- **Tags/Chips:** Fully rounded (pill) shapes for status indicators to distinguish them from interactive buttons.
- **Selection:** Selected cards should use a 2px primary border with a subtle inner glow or tonal shift.

## Components

- **Data Tables:** Dense layout with fixed headers and 12px typography. Use zebra-striping and 1px horizontal borders. Row hover states must be distinct.
- **Command Cards:** Compact containers showing title, execution status (Tag), and "Last Used" metadata. Buttons are placed in a bottom-aligned toolbar within the card.
- **Status Tags:** High-contrast background with white text. Green for Online, Red for Offline, and Teal for KS-Executable. Always include an icon for redundant signaling.
- **Primary Buttons:** Solid blue fill. Use a loading spinner and "Disabled" state (reduced opacity) during execution to prevent double-submissions.
- **Danger Buttons:** Ghost style (red border) by default; solid red only on hover or within confirmation modals.
- **Input Fields:** Dark background with subtle borders. Labels should be top-aligned for better vertical scanning in dense forms.
- **Modal Dialogs:** Used for "high-risk" confirmations. These must require an explicit interaction (e.g., typing "CONFIRM" or a toggle) for destructive game operations.
- **Progress Indicators:** Linear bars for long-running Git/Sync tasks; circular spinners for instantaneous API polling.