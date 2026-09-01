# PRD Prototype Generator - Stitch Export

Stitch project: `PRD Prototype Generator`  
Project ID: `1469742293694552308`

This directory contains the requested PRD, design system, generated page code,
original-resolution screenshots, and image assets exported from Stitch.

## Directory map

| Directory | Content |
| --- | --- |
| `01-prd` | `PRD.md` and its Stitch screen metadata |
| `02-design-system` | Design documentation, source JSON, and CSS tokens |
| `03-command-hub` | Command management - core hub |
| `04-login` | Login and authentication |
| `05-script-multiserver` | Script management - multi-server configuration |
| `06-qa-design` | Test design - AI-assisted generation |
| `07-command-params-detail` | Command management - parameters and details |
| `08-script-batch-feedback` | Script management - batch execution feedback |
| `09-git-repository-center` | Git pull - repository center |
| `10-ks-sync` | Environment sync - KS data center |
| `11-git-conflict-lock` | Git pull - conflict and lock handling |
| `12-user-management` | User management - access control |

## Page files

- `index.html`: local-use version. Images referenced by the generated page have
  been downloaded into the page's `assets` directory and the paths rewritten.
- `index.stitch.html`: untouched Stitch export retaining the original hosted
  image URLs.
- `screenshot.png`: original-resolution Stitch screenshot.
- `screen.json`: screen ID, source URLs, dimensions, and export metadata.
- `assets.json`: mapping from hosted image URLs to downloaded local files.

The generated HTML still loads Tailwind CSS and Google Fonts from their public
CDNs, so an internet connection is required for exact styling. Open any
`index.html` in a browser to preview that screen.

## Root metadata

- `manifest.json`: requested items in their original order.
- `screens.json`: raw Stitch screen listing.
- `design-systems.json`: raw Stitch design-system listing.
