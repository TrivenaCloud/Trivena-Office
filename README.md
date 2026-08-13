# TrivOffice

**AI-native office suite for macOS, Windows, and Linux** — forked and rebranded from [GenOffice](https://github.com/genspark-ai/genoffice) for [Trivena Cloud](https://github.com/TrivenaCloud/Trivena-Office).

[![CI](https://github.com/TrivenaCloud/Trivena-Office/actions/workflows/ci.yml/badge.svg)](https://github.com/TrivenaCloud/Trivena-Office/actions/workflows/ci.yml)
[![Build installers](https://github.com/TrivenaCloud/Trivena-Office/actions/workflows/build.yml/badge.svg)](https://github.com/TrivenaCloud/Trivena-Office/actions/workflows/build.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
![Platforms: macOS | Windows | Linux](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)

TrivOffice opens and saves real Microsoft Office formats — Word (`.docx`), Excel
(`.xlsx`), PowerPoint (`.pptx`) — and edits PDF and Markdown too: a word
processor, spreadsheet, presentation editor, PDF editor, and Markdown editor as
six Electron modules sharing one engine layer, hosted by a single shell app.

## Download / test builds

Installer artifacts are produced by the
[Build installers](https://github.com/TrivenaCloud/Trivena-Office/actions/workflows/build.yml)
workflow (Linux, Windows, and macOS). Open the latest successful run and download
the artifacts from the **Artifacts** section.

Local packaging:

```bash
npm run dist:mac     # dmg + zip
npm run dist:win     # NSIS installer
npm run dist:linux   # AppImage + deb + rpm
```

## Apps

| App             | Product                 | What it is |
| --------------- | ----------------------- | ---------- |
| `apps/docs`     | **TrivOffice Docs**     | `.docx` word processor with byte-preserving round trip |
| `apps/sheets`   | **TrivOffice Sheets**   | `.xlsx` spreadsheet (Univer UI + Rust xlsx sidecar) |
| `apps/slides`   | **TrivOffice Slides**   | `.pptx` presentations (in-house engine + Konva) |
| `apps/pdf`      | **TrivOffice PDF**      | Real PDF text/image editing (pdf.js + PDFium wasm) |
| `apps/markdown` | **TrivOffice Markdown** | `.md` / `.markdown` block editor |
| `apps/shell`    | **TrivOffice**          | Suite shell: home, tabs, theme, auto-update |

**AI backend (Genspark).** Sign-in uses a Genspark device-code flow; model calls
and agent tools (search, image generation, media analysis) route through the
Genspark proxy / `gsk` CLI. Document editing itself is fully local.

## Engine packages

- `packages/docx-engine` — docx parse + byte-level paragraph patch
- `packages/pptx-engine` / `packages/pptx-render` — pptx model and rendering
- `packages/file-parse` — text extraction for AI attachments
- `packages/agent-core` — shared agent loop
- `packages/ai-provider` — model provider streaming
- `packages/ai-search` — Genspark auth + search tools
- `packages/i18n`, `packages/ui`, `packages/project-store`, `packages/electron-utils`

## Development

Prerequisites: Node 22+, npm 10+, Rust (`cargo` on PATH for the sheets sidecar).

```bash
npm install
npm run fixtures     # generate test .docx fixtures
npm test
npm run typecheck
npm run dev          # all five editors + shell (Vite)
npm run dev:docs     # single app
```

## Architecture notes (docx round trip)

```
open docx ─► archive original by hash (never touched)
          ─► docx-engine parses word/document.xml top-level elements
          ─► Block tree, each block anchored by docxIndex + original XML slice
          ─► Tiptap streaming editor (manual + AI editing, dirty tracking)
save      ─► dirty blocks → OOXML fragments
          ─► splice into original document.xml (untouched blocks keep original bytes)
          ─► repack zip; all other entries copied byte-for-byte
```

## Security

See [SECURITY.md](SECURITY.md).

## License

Apache-2.0 for the open-source core. The `ee/` directory is reserved for
enterprise modules under a separate license ([ee/LICENSE](ee/LICENSE)).

This project is derived from GenOffice (Apache-2.0); see upstream acknowledgements
in the original project for Electron, Univer, PDFium, pdf.js, Tiptap, Konva,
HarfBuzz, calamine, IronCalc, and bundled fonts.
