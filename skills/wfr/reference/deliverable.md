# Deliverable

Work the impl frontier: `wfr.py frontier FILE`, claim, build.

**Read the board heads-ups first.** `wfr.py board FILE` carries what earlier sessions learned the hard way: unwritten conventions, gotchas, surprises. Check each on a path this ticket touches against its `create_ref` — `git log REF..HEAD -- PATHS` for a commit, `git log --since` for a time, that ticket's resolve commit for a ticket — and supersede any that no longer holds.

Follow [TDD](tdd.md) at the seams the spec named - the failing test first. Typecheck and run the touched tests as you go, the full suite once at the end. When a failure proves a board fact wrong, supersede it then, `--ref` this ticket.

**A gap is a thing the build needs decided that the spec never decided.** Sort each one by whether it is hard to reverse:

- **Easy to reverse** - a name, a default, internal layout: decide it, build on, and log it under Calls.
- **Hard to reverse** - a schema, a wire format, a public interface, anything a ticket blocked on this one builds on: stop. `add` a `grilling` child of this impl ticket, `block` the ticket on it, and release the claim. The human answers it as a normal round.

**Bring the board current before you resolve**: every heads-up on a path this diff touched still holds or is superseded, and every surprise you hit that a later session would repeat is a new heads-up, `--ref` this ticket, `--create-ref` this commit. A gap you decided that a later ticket builds on is a fact too.

Resolve each impl ticket with the subject as its gist and the commit reference in the body. Add one `review` child of this impl — `kind=review`, not blocked on anything.

The body ends in `## Gaps`: one row for **every gap you decided** — the thing, the disposition, and the reason where the disposition does not carry it. The human course-corrects from this table, so a gap left off it is a call they never saw.

`resolve` takes that answer on **stdin** and no text argument, and one resolve is the whole
close: it posts the comment, closes the ticket, lands the gist on the map. So a heredoc, alone
in its Bash call - a second command sharing the call takes the redirect with it:

```sh
wfr.py resolve /abs/path.wf 12 <<'EOF'
Subject line, becomes the gist

What was built, the tests that hold it, the commit ref.

## Gaps

| No. | What | Decision | Reason |
| --- | --- | --- | --- |
| 1 | Spec never said what an empty input shows | **Decided an empty list** | An empty list is not an error |

EOF
```

Release the claim in the next call, once the resolve has echoed its byte count back.

### Follow-up

User feedback on a resolved ticket — a correction, a new requirement surfaced by seeing the actual thing — becomes a child of that ticket, kinded by what the work is (`impl`, `grilling`, `research`). Ticket it on sight; the user typing a correction is the brief. Non-actionable notes go as `comment`.

## Review

When a `review` ticket is on the frontier: claim it, then follow [code-review](code-review.md).

**Dispatch** one **blind** agent per axis, in parallel: each gets the diff and its own axis material, and none of the impl author's reasoning. The Standards agent also gets the board's heads-ups: `wfr.py board FILE`, less any whose `ref` or `create_ref` is the parent impl ticket.

The fixed point is the previous impl ticket's commit ref, off the map; the spec is the `spec` ticket body. The review *is* the two reports: the step closes when both land in the chat.

Resolve the review ticket. The body ends in `## Calls`: one row per finding — the axis (`Standards:`, `Spec:`), the thing, and the severity. No disposition: the human reads the table and decides what to fix.

```sh
wfr.py resolve /abs/path.wf 13 <<'EOF'
Code review for #12

## Calls

| No. | Kind | What | Action |
| ---- | --- | --- | --- |
| 1 | Standards | duplicated .gitignore line | needs fix |
| 2 | Standards | terse `Plug` struct name | judgement call, matches convention |
| 3 | Spec | DIB grey fill vs. "blank" | needs fix, zero-init/black |

EOF
```
