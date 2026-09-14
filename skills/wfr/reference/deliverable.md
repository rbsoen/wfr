# Deliverable

Work the impl frontier: `wfr.py frontier FILE`, claim, build.

**Read the board before the code.** `wfr.py board FILE` is the codebase as earlier sessions left it: start from it, and look only where it is silent. Check each fact on a path this ticket touches against its `create_ref` - `git log REF..HEAD -- PATHS` for a commit, `git log --since` for a time, that ticket's resolve commit for a ticket - and supersede any that no longer holds.

Follow [TDD](tdd.md) at the seams the spec named - the failing test first. Typecheck and run the touched tests as you go, the full suite once at the end. When a failure proves a board fact wrong, supersede it then, `--ref` this ticket.

**A gap is a thing the build needs decided that the spec never decided.** Sort each one by whether it is hard to reverse:

- **Easy to reverse** - a name, a default, internal layout: decide it, build on, and log it under Calls.
- **Hard to reverse** - a schema, a wire format, a public interface, anything a ticket blocked on this one builds on: stop. `add` a `grilling` child of this impl ticket, `block` the ticket on it, and release the claim. The human answers it as a normal round.

After that, [code-review](code-review.md). **Dispatch** it, one **blind** agent per axis, in parallel: each gets the diff and its own axis material, and none of your reasoning - you wrote this code, so your context is the author's, not a reviewer's. The Standards agent also gets the board's facts from earlier sessions: `wfr.py board FILE`, less any whose `ref` or `create_ref` is this ticket - those carry your reasoning.

Its fixed point is the previous ticket's commit ref, off the map; its spec is the `spec` ticket body, so neither is a question for the human here. The review *is* the two reports: the step closes when both land in the chat.

**Bring the board current before you resolve**: every fact on a path this diff touched still holds or is superseded, and every gap you decided that a later ticket builds on is a fact, `--ref` this ticket, `--create-ref` this commit.

Resolve each impl ticket with the subject as its gist and the commit reference in the body.

The body ends in `## Calls`: one numbered line for **every finding in both review reports and every gap you decided** - the axis (`Standards:`, `Spec:`) or `Gap:`, the thing, the disposition in bold, then the reason where the disposition does not carry it. The human course-corrects from this list, so a finding left off it is a call they never saw.

`resolve` takes that answer on **stdin** and no text argument, and one resolve is the whole
close: it posts the comment, closes the ticket, lands the gist on the map. So a heredoc, alone
in its Bash call - a second command sharing the call takes the redirect with it:

```sh
wfr.py resolve /abs/path.wf 12 <<'EOF'
Subject line, becomes the gist

What was built, the tests that hold it, the commit ref.

## Calls
1. Standards: duplicated .gitignore line - **Fixed**
2. Standards: terse `Plug` struct name - **Left as is**, matches eqmatch2's convention
3. Spec: DIB grey fill vs. "blank" - **Fixed**, zero-init/black
4. Gap: spec never said what an empty input shows - **Decided an empty list**, not an error
5. Standards: diff contradicts b4, modules in `internal/*` - **Superseded** by b7
EOF
```

Release the claim in the next call, once the resolve has echoed its byte count back.
