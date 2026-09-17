# Deliverable

After claiming:

## 1. Check ticket's fitness

**A claimed ticket that doesn't fit one context boundary is split, not started** — the same fit-check the ticket was drafted against (≤~3 files, ≤~5 steps, one deliverable, no open-ended search). If exploring the code showed it overruns, `add` the split children, `block` accordingly, release the claim. Building an oversize ticket is what compacts mid-session.

## 2. Build

Write its **failing test** and make sure it goes red. A new test that passes on its first run tests nothing. Follow [TDD](tdd.md) at the seams the spec named. Typecheck and run the touched tests as you go, the full suite once at the end.

**Every test you turn green, `comment` it before writing the next** — `wfr.py comment FILE N`, one line for the behaviour that now works and the file(s) you touched. A build that turned three tests green and posted no comment threw away its refresh points. An interrupted session rebuilds from those comments plus the held claim; the commit still lands once, as a unit, at resolve.

When a failure proves a board heads-up wrong: supersede it then, `--ref` this ticket.

**A gap is a thing the build needs decided that the spec never decided.** Sort each one by whether it is hard to reverse:

- **Easy to reverse** - a name, a default, internal layout: decide it, build on, and log it under **Gaps**.
- **Hard to reverse** - a schema, a wire format, a public interface, anything a ticket blocked on this one builds on: stop. `add` a `grilling` child of this impl ticket, `block` the ticket on it, and release the claim. The human answers it as a normal round.

## 3. Close it out

**Bring the board current before you resolve**: every heads-up on a path this diff touched still holds or is superseded, and every surprise you hit that a later session would repeat is a new heads-up, `--ref` this ticket, `--create-ref` this commit. A gap you decided that a later ticket builds on is a fact too.

**Close the impl in five ordered moves — commit, compose, resolve, review, release:**

1. **Commit** the ticket's work — one commit for the whole ticket; nothing resolves uncommitted, so the ref is real. Unless a standing rule forbids commits: skip it, and the body carries no ref.
2. **Compose the resolve payload** in the shape below — a decision subject, then the three sections. **The subject states the decision, not a description of the files or a status line** ("Tracer bullet working" is a status; the decision is what you built and chose). It becomes the gist.
3. **Resolve by piping that payload to `resolve` on stdin** — no positional subject, no `--body`, no `--gist`. One heredoc, alone in its Bash call (see below).
4. **Add the review child** — `add` one `kind=review` child of this impl, not blocked on anything.
5. **Release the claim**, once the resolve has echoed its byte count back.

Resolve in a format like this:
```sh
wfr.py resolve /abs/path.wf 12 <<'EOF'
Subject line, becomes the gist

## What it does

Reads every open ticket, then drops the root (#1), any with an unclosed blocker, and any with a non-empty assignee, and prints the rest oldest-first by id.

    frontier_list = []
    for t in open tickets:
        t is root (#1):
          skip
        t.assignee set: # claimed
          skip
        any blocker open:
          skip
        else:
          add to frontier_list
    sort frontier_list oldest-first
    for i in frontier_list:
      print i

## Verified

`test_frontier` at the frontier-query seam, the three exclusions it pins:

    claimed   #2 open but assigned          → excluded
    blocked   #4 open, blocked by open #3   → excluded; #3 still listed
    root      #1 with no blockers           → still excluded
    
    worked example  open {1 root, 2 claimed, 3, 4 blocked-by-3}  →  [3]

`frontier()` @ wfr.py #abc123f.

## Gaps

| No. | What | Decision | Reason |
| --- | --- | --- | --- |
| 1 | Spec never said what an empty input shows | **Decided an empty list** | An empty list is not an error |

EOF
```

1. "What it does": the delivered behaviour in prose and pseudo-code (where applicable). It is *intent, not the code*: the human reads it first and can reject the approach outright (e.g. via a `grilling` child).
2. "Verified": name the test that holds the slice and paste the one worked example it pins. Never paste the body itself: it reads as live code and goes stale the next time a slice touches those lines, where a symbol at a ref does not.
3. "Gaps": one row for **every gap you decided** — the thing, the disposition, and the reason where the disposition does not carry it. The human course-corrects from this table, so a gap left off it is a call they never saw.

### Follow-up

User feedback on a resolved ticket — a correction, a new requirement surfaced by seeing the actual thing — becomes a child of that ticket, kinded by what the work is (`impl`, `grilling`, `research`). Ticket it on sight; the user typing a correction is the brief. Non-actionable notes go as `comment`.
