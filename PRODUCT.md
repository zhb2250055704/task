# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary users are game QA, development, operations, and tool administrators working across multiple KS environments and game accounts. Administrators execute and maintain operational data; regular users primarily search, inspect, copy, calculate, and generate test designs.

## Product Purpose

GM Tool centralizes GM commands, KS environments and accounts, GM console scripts, QA design, item data, formulas, Git updates, SkillHub, and user access. Success means an operator can identify the current identity and target, inspect the exact payload, execute through the correct channel, and understand durable success or failure feedback.

## Positioning

The product resolves KS catalog data and live Cocos client state into one executable target model, then uses that model across GM command and script workflows.

## Operating Context

The tool is an internal web application backed by a local Python service. It works with KS, Cocos WebSocket clients, GM Console, local Git repositories, configuration spreadsheets, Codex skills, and uploaded product or technical documents.

## Capabilities and Constraints

- Preserve all roles, permissions, APIs, data files, and workflows documented in `PRD.md`.
- Require explicit target selection and complete command parameters before execution.
- Distinguish delivery success from final in-game business success.
- Keep administrator-only controls hidden for regular users and protected by server-side authorization.
- Support dark and light themes, 50-300% desktop zoom, and a mobile layout capped at 100% zoom.
- Do not invent KS environments, user accounts, Git results, execution results, or business metrics.

## Brand Commitments

The user supplied the Stitch project `PRD Prototype Generator` as the binding high-fidelity visual source. Product copy remains Chinese where defined by the PRD. The shell identity is GameOps Engine / Mission Control as shown in the prototype.

## Evidence on Hand

- Product requirements: `PRD.md`
- Stitch export: `stitch-export/prd-prototype-generator`
- Stitch design system: `stitch-export/prd-prototype-generator/02-design-system`
- Existing implementation and API bindings: `index.html`, `login.html`, and `server.py`

## Product Principles

1. Make the active identity, environment, account, server, and execution channel explicit.
2. Use deliberate confirmation and durable feedback for high-risk operations.
3. Keep dense operational data scannable and comparable.
4. Preserve recovery paths when external systems or local files block an operation.
5. Prefer real current data over illustrative dashboard metrics.
