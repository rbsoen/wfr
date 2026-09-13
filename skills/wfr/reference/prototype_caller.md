# Prototype (caller)

Read this when you `add` a `prototype` issue or take one off the frontier. [prototype](prototype.md) is the doer's side, for the agent that actually builds the take.

`wfr.py claim FILE N` before you build or dispatch the take; the claim holds until you resolve it.

**A prototype issue is never bodyless.** At `add`, write what is unsettled and what a take has to answer, ending on `Still undecided` - the takes stay in the chat, where you can pull one up on the spot. The verdict replaces that line.

**A prototype also goes in the store, but it has to run.** Text goes straight to the store where executable code cannot: it needs a real path on disk, and that path is **the scratchpad**. So it round-trips:

```
wfr.py cat FILE shell.html > <scratchpad>/shell.html   # export FILE DIR for all of it
<run it, render it, iterate>
wfr.py put FILE shell.html --issue N < <scratchpad>/shell.html
```

`import FILE DIR` slurps a tree when the prototype outgrew one file. Resolve with the verdict as gist and `/p/<path>` as evidence.

**The settled take goes back in on its own.** A rig that switches between three takes is how you asked, not what was chosen: `put` the chosen one as its own file, and resolve pointing at that.
