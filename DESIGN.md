# Nexus Operational System

The visual authority is the Stitch design system and the ten exported high-fidelity screens in `stitch-export/prd-prototype-generator`.

## Direction

The interface is a dark, dense mission-control workspace for repeated operational tasks. A fixed 240px navigation rail, fixed 56px command bar, and fixed 32px connection bar frame every authenticated view. Tonal layers and 1px borders create hierarchy; decoration does not.

## Tokens

- Background: `#121414`
- Deep background: `#0d0e0f`
- Panel: `#1f2020`
- Elevated panel: `#292a2a`
- Border: `#303030`
- Text: `#e3e2e2`
- Secondary text: `#c0c7d6`
- Primary action: `#a5c8ff`
- Active navigation: `#600fc0`
- KS executable: `#13c2c2`
- Success: `#52c41a`
- Warning: `#faad14`
- Error: `#f5222d`
- Control radius: `4px`
- Container radius: `8px`

## Typography

Use Inter for interface text and JetBrains Mono for commands, identifiers, payloads, paths, logs, and technical status. The desktop page title is 24/32 at weight 600; the default body is 14/22.

## Components

- Primary buttons use solid blue and include a relevant icon.
- Destructive buttons stay outlined until confirmation or hover.
- Inputs use a deep background, 1px border, top-aligned labels, and visible blue focus state.
- Cards and tables use tonal surfaces rather than heavy shadow.
- Status color must include text and, when space permits, an icon.
- High-risk command and Git recovery dialogs use an explicit summary, concrete affected targets, raw output, and a single recovery action.

## Responsive Rules

- Above 1180px: full 240px rail and multi-column workspaces.
- 768-1180px: 76px icon rail and reduced top-bar controls.
- Below 768px: drawer navigation, single-column content, horizontally scrollable data tables, and fixed-format controls that do not resize with content.
