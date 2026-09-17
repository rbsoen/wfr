---
name: wfr
description: Run an effort inside a single `.wf` tracker.
disallowed-tools: AskUserQuestion
---

A `.wf` file represents one effort in a self-contained ticket tracker: a SQLite file, read and written through `wfr.py` alone.

## First up

Run (not read) `wfr.py` with no arguments, once. All ~270 lines of the output *is* the reference. If not located in the user's PATH, it's in the skill directory.

**The scratchpad** (usually `/tmp/claude-$(id -u)/$(pwd | sed 's:/:-:g')/${CLAUDE_CODE_SESSION_ID}/scratchpad`) is Claude's own session temp dir. Resolve it once and keep the literal path, shell state resets with cwd. Everything this skill makes that is not a ticket (findings, prototype code, exports) *passes through* there on its way into the `.wf` via `research --from` or `put`. **Work that ends its life in the scratchpad was never delivered.** Every subagent you dispatch gets that absolute path in its prompt, and cwd holds the `.wf` alone.

Depending on how this skill is invoked:
* **Bare**: ask the user what they meant: continuing a `.wf`, charting a new effort, or something else.
* **No file, and the user states the goal in prose**: you're charting, and any `.wf` you find is irrelevant. `wfr.py init $PWD/<slug>.wf --title "<the effort>"`, state where it landed, then name the goal.
* **A file named**: `wfr.py map FILE`. Roots hold destination, notes, fog: read them. Then pick up `wfr.py board FILE`, they hold heads-ups and precautions that apply to the entire effort, and `wfr.py research FILE`, the facts already established. A brief given with the file [opens a round](#opening-a-round): its questions are the frontier.
* **A file and number named**: `wfr.py show FILE NUMBER`, then `wfr.py board FILE`. Follow the instructions for its kind under [Types of ticket](#types-of-ticket), then pick up from there.

Invoking this skill is the user's call that this effort is tracked. Chart it, whatever the subject. **Decision trees are universal**, only a deliverable assumes a codebase.

A claimed `research`, `prototype` or `impl` may be a live parallel session: report it and let the human call it. Take `wfr.py frontier FILE`, pick up there; the destination is settled.

## The file's shape

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

## Ground rules

1. Write to the `.wf` **first**, then let the user read a view (chat, disk copy, export, subagent report).
2. Views are **one way**. To edit a body, read it with `wfr.py show FILE ID --body`, edit that, and `set FILE ID body -` it back; plain `show` interleaves edges and comments, so its output breaks a body.
3. Pass only absolute paths to `wfr.py`, because CWD resets between Bash calls.
4. **The human runs the server, never you.** Write every link as a bare path.
5. The human is the lock; never claim a grill.

### Before you stop

1. Release any `research`, `task`, `prototype` or `impl` you claimed and did not finish. Do it as the *work* ends rather than as the session ends - an abrupt stop leaves no turn to tidy up.
2. `wfr.py map FILE`: every question you asked is on it, every answer in a gist or a body, and the chart matching the tree - no fog the tree has already lifted.
3. `wfr.py research FILE` and `wfr.py term FILE`: every fact a decision rested on, and every word you had to learn, is there.

## Working through a map

1. **Name the destination**. Use [grilling](reference/grilling.md) and [domain modeling](reference/domain-modeling.md) to pin down exactly what this effort is finding its way to: a spec to build from, a decision to lock, a change made in place. It fixes the scope, so every ticket under it is judged against it.
2. **Grill again breadth-first**. Fan across the space, rather than deep on one thread.
3. **Seed the map body**: destination, notes, fog under "Not yet specified". Questions the brief names seed the frontier; the breadth pass fills it.
4. **Plan, don't do**. Map tickets resolve into decisions, not execution.

### Opening a round

1. `add` every question in the round, each with its body (`--body -`) - the framing you would otherwise type under it in the chat. **The title itself only contains the question**, never the number (e.g. `Q1`). **One ticket, one question.** The body frames it; every further question it raises is its own `add`: in this round if it is on the frontier now, otherwise as a child of the question it hangs on.
2. Write each one's `option` rows, each with its why in `--body`, and your `recommend`. See exceptions below.
3. Only then, type the round into the chat.

Format a round like so, one block per question, `---` between them. A question body may run to several paragraphs; the options are the last thing before the steer.

```
❓ **Q1** - **<the question>** (#<id>)

<the ticket body, where the question has one>

1. <option>
2. <option>

➡️ 2

---

❓ **Q2** - ...
```

**The `➡️` is the number alone** - just `➡️ 2`, the picked option's digit. Its why went into that ticket's `recommend` body at write-up, and stays there: the round points, the file explains.

**A fact only the human holds takes a body, no options, no `recommend` and no `➡️`.** Where they live, what they already own, what happened the last time they did this: unfindable, so ask it bare of options and resolve with `--picked` omitted, which claims nothing.

**An answer need not cover the round.** Leave unanswered questions open for the next round, never inferred. Option numbers restart at 1 on each ticket, so a bare number means nothing unpaired with its Q.

### Closing a round

**Resolve with a subject and a body.** The subject is the decision, the body is why, in the human's own terms. A one-line resolve is legal and is a decision half-lost.

In one pass:

1. `research --from` each fact this round's answers rest on that is not yet in `/r/`
2. `resolve` each answered ticket with a subject and body. Linking the `/r/ID` it rests on.
3. move the map body. fog those answers lifted comes off "Not yet specified", fog they revealed goes on, decisions worth keeping go to Notes; retitle an ADR as it resolves.
4. `block` what the answers gated
5. only then take `wfr.py frontier FILE` for the next round, or run [Before you stop](#before-you-stop) when the frontier holds none.

A round that ends at step 2 leaves the map describing the effort as it was before you asked.

### Invalidating a round

**An invalidated round is closed, never deleted.** Judge each ticket alone: a failed premise voids some and leaves others standing.

* Not yet resolved: `resolve` it with the failed premise as its gist, so the next session does not re-ask it.
* Already resolved: the correction resolves `--supersedes` the old one.

Either way, the corrected question is a child of what it corrects.

### Performing research

1. `add` the `research` ticket, parented to the `map` or the `grill` that originates it, and write its body then and there (`--body -`). **A research ticket is never bodyless**: the body is the brief - the fact wanted, the decision waiting on it, what counts as an answer - and step 3's prompt is cut from it.
2. `wfr.py claim FILE N` **before** you dispatch. A background agent is work under way, and an unclaimed research ticket is one a parallel session takes and redoes.
3. Dispatch a subagent, handing it the scratchpad path to write into. The subagent's brief follows [research](reference/research.md).
4. It should come back with a **path** in the scratchpad, so slurp THAT file rather than the agent's report:
```
wfr.py research FILE --from /path/to/findings.md --ticket N
```
The research file's title comes from the `# ` heading; `--ticket N` hangs it off the question it serves.
5. Resolve the research ticket, the finding as its gist and `/r/ID` as where the detail lives.


## Drafting the spec

**The destination decides whether this phase runs.** Something to **build** reaches here.

1. Add one `kind=spec` child of the map, then follow [spec](reference/spec.md). Only block it on **decisions still open** when the spec is cut.
2. **Charted** is the gate to cut it, and it is two conditions: the frontier holds no decisions, *and* "Not yet specified" is empty.
3. **Read the fog bodies back before you call it**. Fog goes stale the moment the ticket that lit it resolves.
4. The spec **composes** "Decisions so far" and does not re-argue them; where a decision needs its reasoning, link its ticket.

## Drafting the deliverable

1. Add `kind=impl` children of the spec. Follow [to-tickets](reference/to-tickets.md) to draft and quiz the vertical slices. A user who says to skip the quiz skips the quiz alone: the slice rules and step 3 still hold.
2. **Block each ticket on the sibling tickets it actually depends on**, never the spec itself - parentage already records that it came from there.
3. **A screen nobody has seen is not a ticket yet.** Where a user will look at the result and no resolved ticket settled how it looks, add a `prototype` child of that ticket.
4. Run [Before you stop](#before-you-stop).

## Types of ticket

### Grilling

Follow [grilling](reference/grilling.md) and [domain modeling](reference/domain-modeling.md). Conversation, and is the default. Human-in-the-loop; the user answers for themselves and you never answer for them.

**Grills beget grills.** A resolved grill usually raises the next question as a consequence. Add it as a child of the grill that raised it, not the map, so the tree records what led to what.

**The human types the answer in prose.** Your options are only the answers you already thought of, and the one that matters is the one you did not: that the premise under the round is wrong. Typed prose is where "none of these, you have misread X" arrives. A round that dies on pushback is this working.

**A word you had to pin down is a `term`.** Write it with `wfr.py term` as that grill resolves, not at round close. A resolve body explaining what a word means here is a definition in the wrong place. The tell is *disambiguation*: you asked which sense was meant, the human corrected your usage, or you had to look the word up before you could ask about it.

### Research

When starting from this ticket, follow [Performing research](#performing-research). A fact a decision waits on: from outside this directory, or from inside it when establishing it took more than one command. During grilling, this ticket is AFK - it never holds up a round because it runs parallel.

### Prototype

Follow [prototype-caller](reference/prototype_caller.md). Raise one when "how should it look" or "how should it behave" is the question.

### Task

Manual work gating a decision: provisioning, access, moving data so its shape can be seen. The one kind that does rather than decides, earning its place by unblocking a question.

### Implementation

Follow [deliverable](reference/deliverable.md). **Resolving an impl adds its one `review` child; drafting adds none.** It does not block the next impl, it hits the frontier beside it.

### Review

Claim it, then follow [code review](reference/code-review.md). Work it now, batch several, or leave it; the next impl proceeds either way.
