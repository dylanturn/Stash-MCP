# Search Strategy

Detailed guidance for using Stash-MCP's semantic search effectively. The search system uses vector embeddings, not keyword matching — this fundamentally changes how to write queries and interpret results.

## How Search Works

Content files are split into chunks (default: 1000 characters with 100-character overlap) and embedded as vectors using a sentence-transformer model. Queries are embedded with the same model and compared by cosine similarity.

When contextual retrieval is enabled, each chunk is enriched at indexing time with document-level context — a brief summary of where the chunk fits within the larger document. This improves retrieval for queries that depend on broader meaning rather than local keywords.

## Score Interpretation

Similarity scores range from 0 to 1. Calibration depends on the embedding model and content characteristics, but as general guidance:

| Score Range | Interpretation | Action |
|-------------|---------------|--------|
| 0.65+ | Strong match — high confidence this content is relevant | Read and use |
| 0.50–0.65 | Probably relevant but possibly tangential | Read to verify relevance |
| 0.40–0.50 | Weak signal — may contain something useful buried in context | Only read if nothing better is available |
| Below 0.40 | Likely noise | Skip — consider rephrasing the query |

These thresholds are approximate. A store with highly specialized technical content may produce higher average scores than one with diverse general content.

## Query Techniques

### Write Natural Language, Not Keywords

The embedding model understands meaning, not keyword frequency. Natural language queries consistently outperform keyword fragments.

| Instead of... | Try... |
|--------------|--------|
| `trigger webhook` | `how does the trigger system handle webhook events` |
| `error handling` | `what happens when a workflow execution fails` |
| `API auth` | `how is authentication implemented for the REST API` |
| `database schema` | `what tables and relationships make up the data model` |

### Broaden Before Giving Up

If a specific query returns weak results (all below 0.50), broaden rather than assuming the content doesn't exist:

1. Rephrase using different terminology — the content may use different words for the same concept
2. Ask a more general question — `how does error handling work` instead of `where is the retry logic for failed API calls`
3. Try adjacent concepts — if searching for deployment config returns nothing, try `how to run the service` or `environment setup`

### Use Multiple Short Queries

One complex query often performs worse than two or three focused ones:

- Instead of: `how does the notification system send emails and handle delivery failures and track open rates`
- Try three queries:
  - `how does the notification system send emails`
  - `how are email delivery failures handled`
  - `how are email open rates tracked`

Each query targets a specific facet, improving the chance of finding relevant chunks.

### Filter With file_types

The `file_types` parameter accepts comma-separated extensions:

- `.md` — documentation only
- `.py` — Python source code
- `.md,.py` — docs and code, excluding configs and other files

Use this when you know what kind of content you're looking for. Searching only `.md` files when you need documentation avoids noise from code comments or config files that happen to mention similar terms.

### Combine Search With Structure Inspection

Search finds *what's relevant*. Structure inspection shows *where it fits*.

```
search_content("how authentication works")
  → returns chunks from auth.md and api-design.md

inspect_content_structure("auth.md")
  → shows the full document outline

read_content("auth.md", max_lines=N)
  → read the specific section identified by structure inspection
```

This three-step approach is more efficient than reading entire files returned by search.

## Limitations to Know

- **Not keyword search** — searching for an exact function name or variable won't work well. Use `read_content` with `max_lines` or grep-style inspection for exact string matching.
- **Chunk boundaries** — information split across two chunks may not surface for a single query. If you suspect this, try querying from different angles.
- **Index freshness** — the index updates incrementally as files change, but there may be a brief delay after writes before new content is searchable.
- **Model-dependent** — score calibration varies by embedding model. If the server changes models, previously reliable thresholds may shift.
