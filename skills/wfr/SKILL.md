---
name: wfr
description: Run an effort inside a single `.wf` tracker. Use when a `.wf` file is named, or when `/wfr` starts one from a prose brief.
disallowed-tools: AskUserQuestion
---

A `.wf` file represents one effort. It replaces plan docs and piles of `.md` with a single, structured issue tracker.

## Before anything

Run `wfr.py` bare once a session, because that's where the reference is. It ought to be in PATH; if not, it is in the skill directory. Offer to place it in the user's PATH as a symlink if not already.

Ensure you pass only absolute paths into `wfr.py`; cwd resets between Bash calls.

**The scratchpad** (usually `/tmp/claude-$(id -u)/$(pwd | sed 's:/:-:g')/${CLAUDE_CODE_SESSION_ID}/scratchpad`) is Claude's own session temp dir. Resolve it once and keep the literal path - shell state resets with cwd. Everything this skill makes that is not an issue (findings, prototype code, exports) *passes through* there on its way into the `.wf` via `research --from` or `put`. Work that ends its life in the scratchpad was never delivered. Every subagent you dispatch gets that absolute path in its prompt, and cwd holds the `.wf` alone.

Next up: `wfr.py map FILE`:

* **No file** - you're charting. Pick a slug, initialize with `wfr.py init $PWD/<slug>.wf --title "<the effort>"`, state where it landed, then name the destination.
* **A map in it** - you're continuing. Root holds the destination, notes, fog; read them, take `wfr.py frontier FILE`, pick up there; the destination is settled.
* **Anything claimed** - check every time, not only on an empty frontier: one stale claim hides its issue silently rather than emptying the list. A claimed `research` or `impl` may be a live parallel session: report it and let the human call it.

Invoking wfr is the human's call that this effort is tracked. Chart it, whatever the subject. **Decision trees are universal**, only a deliverable assumes a codebase.

## The shape

One file, this shape:

```
#1  map       <the effort>          destination, fog, Notes
#2    grilling  Which store?
#5      grilling  ...raised by #2
#3    research  How does X authenticate?
#4    task      Provision the bucket
#6    spec      Build X               blocked by #2 #3 #4 #5
#7      impl      Slice A             blocked by #6
#8      impl      Slice B             blocked by #7
```

A spec in its own `.wf`, or a spec root beside the map, happens **only when the user says so**.

## The flow

Write an item to the `.wf` first, *then* let the user read a view (the chat, a disk copy, an export, a subagent's report).

**Views are one way**, never roundtrip one back into a write. `show` interleaves children and comments together, and using it for `set` will result in a broken issue body.

**The human runs the server**. Do not start one; `serve` is theirs. Write every link as a **bare path**. A hostname and port in a round is a guess at someone else's setup.

## 1. Map

**Name the destination first** - it fixes the scope, so every later issue is judged against it. Follow [grilling](reference/grilling.md) and [domain modeling](reference/domain-modeling.md) to pin down what this effort is finding its way to: a spec to build from, a decision to lock, a change made in place. Then grill again **breadth-first**, fanning across the space rather than deep on one thread, and seed the map body: Destination, Notes, fog under "Not yet specified". If that surfaces no fog there is nothing to chart; say so and stop.

**Plan, don't do.** Map issues resolve into decisions, not code. The pull to build is the signal the map is done and the spec is next.

### Kinds

#### grilling

Conversation, and the default. HITL: the human answers for themselves and you never answer for them. Follow [grilling](reference/grilling.md) and [domain modeling](reference/domain-modeling.md).

**Grills beget grills.** A resolved grill usually raises the next question as a consequence. Add it as a child of the grill that raised it - `--parent` is that grill, not the map - so the tree records what led to what. Encouraged, not the exception.

**A word you had to pin down is a `term`.** Write it with `wfr.py term` as that grill resolves, not at the round close - a resolve body explaining what a word means here is a definition in the wrong place. The tell is disambiguation: you asked which sense was meant, or the human corrected your usage.

**A format you had to pin down takes an example.** The glossary holds none of it - a shape is implementation detail - so one literal instance goes in the resolve body as that grill resolves: a code block representing the data type. Structs, keys, the works. The tell is an ambiguous format decision: "Let's use JSON," "XML it is", the keys listed in prose, the nesting and the types left to whoever writes the code. You *must* write the code block down in the tracker for the user's review.

#### research

A fact from outside this directory that a decision waits on.
AFK - it never holds up a round because it runs parallel.

1. `add` the `research` issue, parented to the `map` or the `grill` that originates it, and write its body then and there (`--body -`). **A research issue is never bodyless**: the body is the brief - the fact wanted, the decision waiting on it, what counts as an answer - and step 3's prompt is cut from it.
2. `wfr.py claim FILE N` **before** you dispatch. A background agent is work under way, and an unclaimed research issue is one a parallel session takes and redoes.
3. Dispatch a subagent that follows [research](reference/research.md), handing it the scratchpad path to write into.
4. It should come back with a **path** in the scratchpad, so slurp THAT file rather than the agent's report:
```
wfr.py research FILE --from /path/to/findings.md --issue N
```
The research file's title comes from the `# ` heading; `--issue N` hangs it off the question it serves.
5. Resolve the research issue, the finding as its gist and `/r/ID` as where the detail lives.

#### prototype

When "how should it look" or "how should it behave" is the question. HITL. Follow [prototype](reference/prototype.md) to run one. Follow [prototype-caller](reference/prototype_caller.md) for handling them: the issue body, the scratchpad round-trip, and landing the settled take in the store.

#### task

Manual work gating a decision: provisioning, access, moving data so its shape can be seen. The one kind that does rather than decides, earning its place by unblocking a question.

### The round

Per [grilling](reference/grilling.md): the frontier in one round, each question numbered with your `➡️` under it, then wait.

**Every question is an issue**: a whole round, one follow-up, an aside you thought of mid-answer.

**Write the question** before you ask it:
1. `add` every question in the round, each with its body (`--body -`) - the framing you would otherwise type under it in the chat
2. write each one's `option` rows and your `recommend`
3. only then, put the round in the chat, as prose you type.

Ask first and write up after and you are transcribing a view: what reaches the file is the compressed version, options and steer and the human's reasoning gone.

**The issue title itself only contains the question**, never the number (e.g. `Q1`).

**A fact only the human holds takes a body, no options, no `recommend` and no `➡️`.** Where they live, what they already own, what happened the last time they did this: unfindable, so ask it bare of options and resolve with `--picked` omitted, which claims nothing. Everything else is a decision - options and a steer - or a `research`, where the answer is out there to be found.

**The human types the answer in prose.** Your options are only the answers you already thought of, and the one that matters is the one you did not: that the premise under the round is wrong. Typed prose is where "none of these, you have misread X" arrives. A round that dies on pushback is this working.

**An answer need not cover the round.** Silence is *not* a resolution: leave unanswered questions open for the next round, never inferred. Option numbers restart at 1 on each issue, so a bare number means nothing unpaired with its Q.

**"Take all" and "idk" are legitimate.** Take-all resolves `--picked 0`, with a gist naming what was taken. An "idk" is the question arriving early: add the `research` or `prototype` that would settle it and `block` this one on it.

**Resolve with a subject and a body.** The subject is the decision, the body is why, in the human's own terms. A one-line resolve is legal and is a decision half-lost.

**An invalidated round is closed, never deleted.** Judge each issue alone: a failed premise voids some and leaves others standing. Not yet resolved - `resolve` it with the failed premise as its gist, so the next session does not re-ask it. Already resolved - the correction resolves `--supersedes` the old one. Either way the corrected question is a child of what it corrects.

**Close the round before you open the next.** Answers land, then in one pass:
1. `resolve` each answered issue, subject and body
2. move the map body - fog those answers lifted comes off "Not yet specified", fog they revealed goes on, decisions worth keeping go to Notes; retitle an ADR as it resolves per [ADR format](reference/domain-modeling_adr-format.md)
3. `block` what the answers gated
4. only then take `wfr.py frontier FILE` for the next round.

A round that ends at step 1 leaves the map describing the effort as it was before you asked.

### Claiming and stopping

**The human is the lock; never claim a grill.** Claim `research`, `task` and `impl`; leave `grilling` and `prototype` unclaimed. A claim makes a second session skip work under way: a real race for `research` and `impl`, and none at all for HITL, where one human answers in one conversation and `resolve` never needed a claim anyway.

**One round a session or many, and stop after any of them.** Stopping is free: the file holds the state, which is what it is for. Close the round and the recomputed frontier is already the next round.

**Before you stop:** release any `research`, `task` or `impl` you claimed and did not finish. Do it as the *work* ends rather than as the session ends - an abrupt stop leaves no turn to tidy up. Then `wfr.py map FILE`: every question you asked is on it, every answer in a gist or a body, and the chart matching the tree - no fog the tree has already lifted. What lives only in the chat dies with it.

## 2. Spec

Not every effort reaches here. This phase is for a destination that is something to **build**. A destination that was a decision to lock, or a change made in place, ends at the map: no spec, no deliverable, and the effort closes when the map closes.

* Add one `kind=spec` child of the map. Only `block` it on decisions still open when the spec is cut - that's real gating, work waiting on an answer.
* A spec cut from an already-closed map needs no edges at all: every decision it composes is closed already, so the block would gate nothing, and the map's Decisions list is already the provenance trail back to them.
* Cut it when the map is **charted**: the frontier holds no decisions and "Not yet specified" is empty.
* Fog goes stale the moment the issue that lit it resolves, so read the body back before you call it charted.
* The spec **composes** "Decisions so far" and does not re-argue them; where a decision needs its reasoning, link its issue.

Write it per [spec](reference/spec.md): check seams with user first, the sections the body carries, and what "User stories" actually looks like.

### Impl tickets

`kind=impl` children of the spec. Follow [to-tickets](reference/to-tickets.md) to draft and quiz the vertical slices - tracer bullets, the wide-refactor exception, what such a ticket looks like, presenting the breakdown and iterating until the user approves.

**Never `block` a ticket on the spec itself** - parentage already records that it came from there. Instead, `block` each ticket on the sibling tickets it actually depends on, mirroring the dependency shape the map's decisions established. A spec-shaped block puts the whole frontier behind one issue that only closes once every ticket is already done.

**A screen nobody has seen is not a ticket yet.** Where a human will look at the result and no resolved issue settled how it looks, add a `prototype` child of that ticket and block it on that - the map's kind, hung where the unseen thing is. Once settled, the ticket cites `/p/<path>` and builds against it, translated into whatever the thing is actually written in: layout, hierarchy and affordances carry from an HTML take into e.g. a desktop window or an ncurses screen, where the markup does not.

**Approved tickets end the session.** Stopping is free here for the same reason it is after a round - the file holds the state. The deliverable takes the frontier fresh, in its own session.

## 3. Deliverable

The result of executing the `impl` tickets.

Read [deliverable](reference/deliverable.md) when you take an impl issue off the frontier.
