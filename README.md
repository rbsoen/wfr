# wfr

**Plan → spec → implementation for agentic AI assisted work.**

Derived from [Matt Pocock's AI Skills for Real Engineers](https://github.com/mattpocock/skills).

It produces a browsable, single-file SQLite `.wf` database integrating the following:

1. Decision tree
2. Glossary
3. ADR
4. Prototypes
5. Research docs

It consists of `SKILL.md` + additional reference md's (progressive disclosure) + a single `wfr.py` tool.

The `wfr.py` tool is designed primarily for agents to work with. However, you can use the tool to read the resulting `.wf` database and watch it as agents chip off the issues one by one:

```sh
wfr.py serve big-feature.wf
```

This skill is still subject to improvement.

## Install

Only tested with Claude Code for now.

```
git clone https://github.com/rbsoen/wfr
cp -r wfr/skills/wfr ~/.claude/skills/wfr
```

## Invocation

1. Instantiate a new map: `/wfr I want a new feature...`
2. Answer grill rounds to sharpen the spec
3. Stop and pick up any time: `/wfr new-feature.wf`
4. Implement tickets `/wfr new-feature.wf implement 15-20`

**Stop a round at any time.** The skill makes the agent persist questions first into the database before asking it to you in chat—think of it as a kind of write-ahead log. Small contexts [tend to benefit agents](https://www.aihero.dev/ai-coding-dictionary/smart-zone), so use this to your advantage.

## Basic flow

```
map → grill
   |    `→ grill
   `→ research
   `→ prototype
   `→ task
   `→ spec
        `→ impl
```

1. The agent builds a **MAP**: it is a ledger stating the goal, what is decided on so far, what is still unknown, what is out of scope.
2. From the map, comes **GRILLS**: the heart of it all. It is a game of 50 questions to make you pin down the design. It essentially builds the _decision tree_ that forms the pathway to the goal.
3. Agents may need to do **RESEARCH** if there is some decision that needs an outside fact to confirm.
4. Agents may also sometimes need to do **TASKS** if some issue required things to be moved around, written, or otherwise done first.
5. When you can't imagine what the agent is going for, or when it comes to UI, you can request the agent to create a **PROTOTYPE** for you to visually confirm and make a decision.
6. After everything is settled, you will have a **SPEC**.
7. The SPEC is then broken down to **IMPL** issues, ready for the agent to execute.

Any one of these can be exported out at any time if the .md artifacts are needed, see `wfr.py export FILE DIR`.

## Why create this?

I've come to regularly use a couple of the skills from the set
this was based off of—`/grilling`, `/grill-with-docs`, `/wayfinder`. For most of my projects there is no issue tracker integration, so it created .md files instead, in accordance to their fallbacks.

While these docs are human-readable and meant to be committed in some way, I did not feel comfortable carrying them around.

I wanted to change the set so that it will do that but also be:

1. obvious to agents - hence the `wfr.py` tool
2. human readable - hence the server functionality in the same tool
