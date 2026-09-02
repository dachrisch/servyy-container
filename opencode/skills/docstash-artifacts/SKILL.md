---
name: docstash-artifacts
description: Create, manage, and publish documents using the DocStash MCP server
triggers:
  - document
  - artifact
  - docstash
  - "create document"
  - "create pdf"
  - "create spreadsheet"
  - "publish"
  - "share document"
  - "show document"
---

# DocStash Artifact Creation Skill

Create, read, manage, and publish documents via the DocStash MCP server (https://mcp.docstash.ai).

## When to Use This Skill

- Creating documents (PDF, Word, spreadsheets, web pages, text/code)
- Reading or listing existing documents
- Sharing or publishing documents
- Managing document versions and history

## Document Types

| Type | Tool | Use When |
|------|------|----------|
| PDF | `create_pdf` | Reports, memos, proposals, print-ready docs (DEFAULT for generic "make a document") |
| Word (.docx) | `create_docx` | User specifically wants an editable Word doc |
| Spreadsheet | `create_sheet` | Excel workbooks with formulas, charts, data tables |
| Web Page | `create_page` | Landing pages, dashboards, visual/interactive content (single file) |
| Web App | `create_app` | Multi-file bundles (HTML + JS + CSS), React/Vue/Svelte apps |
| Text/Code | `create_text` | Markdown docs, source code files, raw data, configs |

## Workflow

### Creating a New Document

1. **Call the appropriate `create_*` tool** with content
2. **STOP** — do NOT call `stash` automatically; the user reviews the preview
3. **Wait for user confirmation** ("save it", "stash", "looks good")
4. **Call `stash`** to persist the document (returns a URL)
5. Optionally call `manage_sharing` with `action='set-public'` to publish

### Reading an Existing Document

- `list_documents` — find a doc's slug (which='active' | 'trash' | 'shared-with-me')
- `read_document` — load content into context (silent, for reasoning)
- `get_pdf`, `get_docx`, `get_sheet`, `get_page`, `get_text` — display to user inline

### Sharing and Publishing

- `manage_sharing` with `action='add'` — grant per-user access by email
- `manage_sharing` with `action='set-public', isPublic: true` — publish to public URL
- `list_org_members` — resolve names to emails for sharing

## PDF Authoring Rules

PDFs are fixed A4 pages (794×1123px @96dpi). Key rules:

- Wrap each page in `<div class="ds-page">…</div>`
- Use `.ds-header` / `.ds-footer` for repeated chrome (page numbers, titles)
- Use `.ds-content` for body content (auto-shrinks to fit)
- Body copy: 13–15px (≈10–11pt), never below 11px
- Fill each page — half-empty pages look like mistakes
- Self-contained: inline all `<style>`, load fonts/images from CDN URLs
- Use `<span class="ds-pageno"></span>` and `<span class="ds-pagetotal"></span>` in footers

## Spreadsheet Spec

`create_sheet` takes JSON-stringified SheetSpec:

```json
{
  "theme": "finance",
  "sheets": [{
    "name": "Q3",
    "frozenRows": 1,
    "rows": [
      ["Item", "Revenue"],
      ["Subscriptions", {"value": 42000, "format": {"numberFormat": "$#,##0"}}],
      ["Total", {"formula": "=SUM(B2:B2)", "result": 42000, "format": {"bold": true, "numberFormat": "$#,##0"}}]
    ]
  }]
}
```

Themes: `minimal`, `corporate`, `finance`, `research`, `minimal_dark`

## Web App Bundle Rules

- Pass `files: { "index.html": "...", "styles.css": "..." }` — server zips and uploads
- Must declare `entry`, `language` (e.g. 'static'), and `framework` if applicable
- For Svelte/React/Vue: use esm.sh ESM imports, NOT build-step source files
- Every local URL must be a key in `files` or an absolute CDN URL
- Include `<meta name="viewport">` for mobile responsiveness

## Common Pitfalls

- **Don't call `stash` automatically** — wait for user to confirm save
- **Don't generate binary files** — pass HTML/JSON content, DocStash renders it
- **Don't use `create_page` for multi-file bundles** — use `create_app`
- **Don't use `create_pdf` for editable docs** — use `create_docx`
- **Always supply `result` alongside `formula`** in spreadsheets (blank cells otherwise)
- **Image/font URLs must be direct files** — gallery/viewer pages render broken
