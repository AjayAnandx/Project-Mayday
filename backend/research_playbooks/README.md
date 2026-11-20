# Research playbooks

Plain-Markdown guidance injected into the research flow (`backend/core/research_flow.py`).
Editing these files changes how Mayday researches. No code changes needed.

## Stage playbooks: `stages/<stage>.md`

One file per LLM stage: `scope`, `plan`, `extract`, `synthesize`, `review`. The whole file is
added to that stage's system prompt, so keep each one short (under ~1,500 characters).

## Category playbooks: `categories/<type>.md`

One file per research type (`market`, `financial`, `academic`, `legal`, …, see
`RESEARCH_TYPES` in `backend/core/research_store.py`). A missing type falls back to
`_default.md`. Front matter is read by code; the body is shown to the scope, plan and
synthesize stages.

```markdown
---
preferred_sources: [web, news]      # adapter names the planner should favour, in order
avoid_sources: [wikipedia]          # adapters the planner must not use for this category
min_primary_sources: 1              # gather gate: at least this many primary-tier sources
---
## Question angles
- ...
## What counts as strong evidence
- ...
## Pitfalls
- ...
```

Adapter names are listed by `available_adapters()` in `backend/core/research_sources.py`
(built-in: web, news, academic, crossref, pubmed, wikipedia, firecrawl; plus any
`research.mcp_adapters` from `config.yaml`).

## Skill excerpts

`config.yaml research.skills` can also pull named sections from installed skills, e.g.
`plan: "deep-research#Critical rules|Pitfalls"`. Only those sections are injected, never the
whole skill.
