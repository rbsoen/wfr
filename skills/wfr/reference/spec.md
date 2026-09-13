# Spec

Sketch the **seams** you will test at first - prefer existing ones, take the highest available, aim for one - and check them with the user before writing the rest. Where the effort builds nothing executable there are no seams: skip this and the Testing decisions section. Then the body:

```markdown
## Problem
<user's perspective>

## Solution
<user's perspective>

## User stories
<numbered and exhaustive: As an <actor>, I want <feature>, so that <benefit>.
 Changes shape when there is no human actor - see below.>

## Implementation decisions
<modules, interfaces, schema changes, API contracts. No file paths.>

## Testing decisions
<the seams, what makes a good test here, prior art in the codebase>

## Out of scope
```

**The "User stories" section changes shape with the actor; its exhaustiveness never does.** Its job is to enumerate the whole surface so nothing is dropped in silence, and that bar travels even where the form does not fit:

- **A person uses it** - user stories exactly as written. The case they were built for.
- **Another program uses it** - a library, a CLI in a pipeline, a wire format, a tool like this one. "As a caller I want `frontier` to list takeable issues" only restates the signature. Enumerate the **entry points**: each one, what it accepts, returns, refuses.
- **Nothing observable changes** - a migration, a rename, a wide refactor. Nobody wants a new thing, so there is no story to tell. Enumerate the **invariants that must survive**, and name what is allowed to change.

Whichever form it takes, a short list means you have not looked yet.

**A gap the spec needs decided and no grill settled** sorts by whether it is hard to reverse. Hard to reverse (a schema, a wire format, a public interface): `add` a `grilling` child of the spec and `block` the spec on it. Easy to reverse: decide it in the body.