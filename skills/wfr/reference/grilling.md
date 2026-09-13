# Grilling

Interview the user relentlessly until you reach a shared understanding. Map this as a **decision tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round, then wait for the user's answers before the next round.

Format a round like so, one block per question, `---` between them. A question body may run to several paragraphs; the options are the last thing before the steer.

```
❓ **Q1** - **<the question>** (#<id>)

<the issue body, where the question has one>

1. <option>
2. <option>

➡️ 2

---

❓ **Q2** - ...
```

**The `➡️` is the number alone** - just `➡️ 2`, the picked option's digit. Its why went into that issue's `recommend` body at write-up, and stays there: the round points, the file explains.

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment, dispatch a sub-agent to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

The session is done when the frontier is empty: every branch of the decision tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.
