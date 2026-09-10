# Research

Spin up a **background agent** to do the research, so you keep working while it reads.

Its job:

1. Investigate the question against **primary sources**, not a secondary write-up of them. Follow every claim back to the source that owns it.
2. Write the findings to a single Markdown file, citing each claim's source.
3. Write it to the scratchpad path the caller gave you, and report that **path** back. The caller files it into their own store; never write into the repo, and never let the findings reach the caller only as your summary - a summary has already dropped the sources that made this research.

## What counts as a valid source

1. Official docs
2. Source code
3. Specifications
4. First-party APIs

When possible, provide a direct blockquote OR a code citation in the form of `file:line`.

If the sources you need are not in hand, you may do a web search.
