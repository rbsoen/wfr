# Deliverable

Work the impl frontier: `wfr.py frontier FILE`, claim, build.

Follow [TDD](tdd.md) at the seams the spec named - the failing test first. Typecheck and run the touched tests as you go, the full suite once at the end.

After that, follow [code-review](code-review.md), then commit.

Resolve each impl issue with the subject as its gist and the commit reference in the body.

`resolve` takes that answer on **stdin** and no text argument, and one resolve is the whole
close: it posts the comment, closes the issue, lands the gist on the map. So a heredoc, alone
in its Bash call - a second command sharing the call takes the redirect with it:

```sh
wfr.py resolve /abs/path.wf 12 <<'EOF'
Subject line, becomes the gist

What was built, the tests that hold it, the commit ref.
EOF
```

Release the claim in the next call, once the resolve has echoed its byte count back.
