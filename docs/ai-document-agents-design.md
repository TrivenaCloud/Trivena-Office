# AI document agents → TrivOffice

Design map for sharpening Docs / Slides / Sheets agents. Anthropic’s
[document skills](https://github.com/anthropics/skills) (`skills/docx|pptx|xlsx`)
are **proprietary** — use only as a pattern reference. Do not copy SKILL.md
text, scripts, or tooling into this repo.

## Engine boundaries

| Format | Runtime | AI skill entry | Context shape |
|--------|---------|----------------|---------------|
| DOCX | `@trivoffice/docx-engine` + TipTap | `apps/docs/.../protocol.ts` `AGENT_SYSTEM_PROMPT`, `tools.ts` | Numbered block list (`buildDocumentContext`) |
| PPTX | `@trivoffice/pptx-engine` | `apps/slides/.../slides-skill.ts` | Deck outline + `get_deck_context` / `read_slide` |
| XLSX | Rust `xlsx-sidecar` under `apps/sheets/native/xlsx-engine` | `apps/sheets/.../prompts/base.md` + `workbook-skill.ts` | Workbook context + ranges / `propose_operations` |

Shell (`apps/shell`) hosts tabs only. Each app runs its own `AgentLoop` from
`@trivoffice/agent-core`. There is **no** unified multi-format agent.

```text
User → Shell tabs → Docs | Slides | Sheets
                      ↓       ↓        ↓
                 docx-engine  pptx-engine  xlsx-sidecar
```

## Create vs edit (already present)

| App | Create / generate | Edit existing |
|-----|-------------------|---------------|
| Docs | `insert_content`, cover/TOC recipes via `apply_commands` | `replace_blocks`, `apply_commands`, charts/images |
| Slides | `generate_deck`, `regenerate_slide` (cloud / Trivena slide_generate) | `execute_slide_script`, element setters, `insert_web_image` |
| Sheets | `propose_operations` (`set_cell` / `set_formula` / structure ops) | Same op set after `read_range` / `get_workbook_context` |

Do **not** add a second pptxgenjs / openpyxl scripting path. Live models + tools
are the product surface.

## Tool surfaces (current)

### Docs

`get_document_context`, `read_blocks`, `insert_content`, `replace_blocks`,
`apply_commands`, `web_search`, `image_search`, `insert_image`, `insert_chart`,
`edit_chart`, plus `read_attachment` (files skill).

`COMMANDS_GUIDE` / `HTML_RULES` live in `protocol.ts` (includes `insertToc`,
styles, lists, move/delete). Tracked deletions are read-hidden; accept/reject
is UI Review, not an agent tool.

### Slides

`generate_deck`, `plan_deck`, `regenerate_slide`, `get_deck_context`,
`read_slide`, `execute_slide_script`, element CRUD/style tools, `web_search`,
`image_search`, `insert_web_image`, charts/tables/SmartArt, style templates,
`ask_clarification`, files skill.

QA: deterministic `layout-audit.ts` on tool results; optional vision
`slide-qc.ts` after cloud gen.

### Sheets

`get_workbook_context`, `read_range`, `read_cells`, `read_formats`,
`read_sheet_features`, `load_guide`, `propose_operations`, `web_search`,
`read_attachment`. Images: local `add_image` only (user-supplied path) — no
`image_search` agent tool today.

## Anthropic patterns → TrivOffice equivalents

| Pattern (reference) | TrivOffice equivalent |
|---------------------|------------------------|
| pptxgenjs “create deck” | `generate_deck` → Trivena/cloud page PPTX → merge via pptx-engine |
| unzip → edit `slideN.xml` → zip | In-memory pptx-engine + `execute_slide_script` / setters |
| Design QA / overflow | `layout-audit` + optional `slide-qc` (no LibreOffice) |
| openpyxl / formula models | Sheets guides + `set_formula` / `propose_operations` |
| docx tracked changes / TOC | Engine + `insertToc` / revision UI; agent must not “re-delete” tracked dels |
| Comments helpers | **Gap:** no Docs AI comment tools today (engine/UI may differ) |

## Sandbox we do not ship

`soffice`, `pandoc`, `pdftoppm`, `markitdown`, Anthropic `validate.py`.

| Their step | Ours |
|------------|------|
| Render DOCX/PPTX via LibreOffice for visual QA | Slides: canvas audit + optional screenshot QC; Docs: block list + editor state |
| `pandoc -t markdown` for read | `read_blocks` / `get_document_context` / `read_slide` / `read_range` |
| XSD `validate.py` | Package vitest round-trips + engine save/open |

## Proposed additions (prompts first)

1. Original quality sections on Docs / Slides / Sheets system prompts (structure,
   data provenance, audit loops, when to generate vs edit).
2. Gap audit (post-prompt): comments agent surface; Sheets optional
   `image_search` — implement only if product prioritizes them.
3. Non-goals: cloning `anthropics/skills`, new `xlsx-engine` npm package,
   unified shell agent, requiring Office binaries in the desktop runtime.

## Delivery

1. This design doc  
2. Prompt supplements (Docs → Slides → Sheets)  
3. Gap list + optional small PRs  
4. Version bump / auto-update when shipping prompt changes to users  

## Gap audit (2026-08-13)

| Gap | Engine / UI today | Agent today | Action |
|-----|-------------------|-------------|--------|
| Word **comments** (add/reply) | docx-engine preserves comment ranges on save; no AI insert API in `tools.ts` | Prompt tells agent to use chat / labeled body notes | **Defer** tool work — needs a dedicated `insert_comment` (or similar) + IPC; not required for prompt ship |
| Word **TOC** | `insertToc` in `apply_commands` | Documented in `COMMANDS_GUIDE` + quality section | **Done** (prompt reminder only) |
| Word **tracked changes** | Revisions UI + AI tracked rewrite path | Agent must not re-delete struck text | **Done** (existing + quality section) |
| Slides **image_search + insert** | `image_search`, `insert_web_image`, generate_deck auto-search | Present | **Done** |
| Slides **layout QA** | `layout-audit`, optional `slide-qc` | Quality section reinforces audit-fix loop | **Done** |
| Sheets **web image_search** | Local `add_image` path only | Prompt documents limitation | **Defer** optional `image_search` unless product prioritizes it |
| Sheets **formula / finance quality** | Guides + `set_formula` | New base.md section | **Done** (prompt) |
| Unified shell multi-format agent | N/A | Separate apps | **Non-goal** |

No confirmed gap is implemented in this pass beyond prompts + this audit. Next optional PRs: Docs `insert_comment` tool; Sheets `image_search` + insert-from-URL if product wants parity with Docs/Slides.
