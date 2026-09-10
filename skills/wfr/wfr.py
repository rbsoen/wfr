#!/usr/bin/env python3
"""wfr - a wayfinder tracker living in one SQLite file.

The issue schema is untouched; research docs, the prototype folder, issue
alternatives and their links are tables an older wfr.py never looks at, and
the verdict column carries a default, so both versions read and write the
same .wf file."""
import argparse, getpass, html, os, re, sqlite3, sys, tempfile
from urllib.parse import quote, unquote

# Named from argv so the help reads right both now and after this file takes
# the wfr.py name.
PROG = os.path.basename(sys.argv[0]) or 'wfr.py'
VERDICTS = ('accepted', 'rejected')

KINDS = ('map', 'grilling', 'research', 'prototype', 'task', 'spec', 'impl')
DECISIONS, OUT_OF_SCOPE = 'Decisions so far', 'Out of scope'

SCHEMA = """
CREATE TABLE issue(
  id       INTEGER PRIMARY KEY,
  kind     TEXT NOT NULL CHECK(kind IN %s),
  status   TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
  title    TEXT NOT NULL CHECK(title <> ''),
  body     TEXT NOT NULL DEFAULT '',
  assignee TEXT NOT NULL DEFAULT '',
  verdict  TEXT NOT NULL DEFAULT '',
  gist     TEXT NOT NULL DEFAULT '',
  adr_title TEXT NOT NULL DEFAULT '',
  adr      INTEGER NOT NULL DEFAULT 0,
  recommendation TEXT NOT NULL DEFAULT '',
  recommends INTEGER,
  picked   INTEGER,
  superseded_by INTEGER REFERENCES issue(id),
  parent   INTEGER REFERENCES issue(id),
  created  TEXT NOT NULL DEFAULT (datetime('now')),
  updated  TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE blocks(
  blocked INTEGER NOT NULL REFERENCES issue(id),
  blocker INTEGER NOT NULL REFERENCES issue(id),
  PRIMARY KEY(blocked, blocker), CHECK(blocked <> blocker));
CREATE TABLE comment(
  id      INTEGER PRIMARY KEY,
  issue   INTEGER NOT NULL REFERENCES issue(id),
  created TEXT NOT NULL DEFAULT (datetime('now')),
  body    TEXT NOT NULL);
CREATE INDEX blocks_blocker ON blocks(blocker);
CREATE INDEX comment_issue  ON comment(issue);
""" % (str(KINDS),)

# The one addition to wfr.py's schema. IF NOT EXISTS, so an old .wf gains the
# folder the first time wfr2 opens it and wfr.py keeps working either way.
EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS research(
  id      INTEGER PRIMARY KEY,
  title   TEXT NOT NULL CHECK(title <> ''),
  body    TEXT NOT NULL DEFAULT '',
  issue   INTEGER REFERENCES issue(id),
  created TEXT NOT NULL DEFAULT (datetime('now')),
  updated TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS proto(
  path    TEXT PRIMARY KEY CHECK(path <> ''),
  body    TEXT NOT NULL DEFAULT '',
  issue   INTEGER REFERENCES issue(id),
  updated TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS link(
  issue INTEGER NOT NULL REFERENCES issue(id),
  doc   INTEGER REFERENCES research(id) ON DELETE CASCADE,
  path  TEXT    REFERENCES proto(path)  ON DELETE CASCADE,
  CHECK((doc IS NULL) <> (path IS NULL)));
CREATE UNIQUE INDEX IF NOT EXISTS link_doc  ON link(issue,doc)  WHERE doc IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS link_path ON link(issue,path) WHERE path IS NOT NULL;
CREATE INDEX IF NOT EXISTS link_issue ON link(issue);
CREATE TABLE IF NOT EXISTS term(
  name    TEXT PRIMARY KEY COLLATE NOCASE CHECK(name <> ''),
  body    TEXT NOT NULL DEFAULT '',
  avoid   TEXT NOT NULL DEFAULT '',
  grp     TEXT NOT NULL DEFAULT '',
  issue   INTEGER REFERENCES issue(id),
  updated TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS option(
  id      INTEGER PRIMARY KEY,
  issue   INTEGER NOT NULL REFERENCES issue(id),
  label   INTEGER NOT NULL DEFAULT 0,
  title   TEXT NOT NULL CHECK(title <> ''),
  body    TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS option_issue ON option(issue);
"""

ISSUE_COLS = ('id, kind, status, title, body, assignee, verdict, gist, adr_title, adr,'
              ' recommendation, recommends, picked, superseded_by, parent, created,'
              ' updated')

MAP_SKELETON = """## Destination

## Notes

## %s

## Not yet specified

## %s
""" % (DECISIONS, OUT_OF_SCOPE)

HELP = """wfr - the wayfinder tracker: one effort, one SQLite file (a .wf).

Everything an agent needs is here; there is no tracker doc in the repo. The
file is the only artifact - research notes are posted as comments, prototype
code lives in the file's own folder, and either can be written back out to
disk whenever a session wants real files.

LANGUAGE
  Issue      One item on the tracker. Always "issue", never "ticket".
  Root       Issue #1, what the effort is about: a map when wayfinder charts a
             route, a spec when the work arrived as one. Any kind may be root.
             Never on the frontier, never resolved - close it with:
               set FILE 1 status closed
  Map        A kind=map root. An index, not a store: it gists each decision and
             points at the issue holding the detail. A tracker has at most one,
             and a tracker started from a spec has none.
  Kind       What an issue is, from a fixed set. A typo is rejected at write
             time, not silently dropped off a report:
               map grilling research prototype task spec impl
  Blocking   "A is blocked by B" - B must close before A can be worked.
  Frontier   Open, unclaimed, every blocker closed, not the root. The edge of
             the known: what a session may take right now.
  Claim      A non-empty assignee. Set it FIRST, before any work, so concurrent
             sessions skip the issue. Release with: claim FILE ID ""
  Gist       The one-line summary of a resolution. It is the subject line of
             the answer, and it lands on the map when the tracker has one.
  Fog        In-scope work not yet sharp enough to be an issue. Prose under the
             map's "Not yet specified". Graduates into issues; never an issue.
  Out of     Work past the destination. Closed, one line on the map, never
  scope      graduates. Not a step on the route, so it is kept off Decisions.
  Option     One way a question could be answered. A row on the question, not
             an issue: never work, never on the frontier, never on the map,
             never blocking, and it has no verdict of its own.
  Recommend  The agent's steer on a question - which option it leans to and
             why. One per question, written when the question is asked.
  Verdict    superseded, on a decision a later one replaced. Empty otherwise.
  Supersede  A later decision replacing a standing one. Directed and in
             time, unlike options, which compete at once.
  Term       One glossary entry: a name, what it IS in a sentence or two,
             and the words it replaces. Keyed on the name, case-blind.
  ADR        A closed issue marked as worth publishing as a decision record.
             Not a separate store: a flag and a rendering.

OPERATIONS
  Every command and every flag is here; the sections below hold the
  semantics rather than the surface.

  wfr.py init FILE --title "..." [--kind K]
                                        create the file, seed the root as #1;
                                        --kind defaults to map
  wfr.py map FILE                       the whole tree (once per session)
  wfr.py frontier FILE                  what is takeable now
  wfr.py show FILE ID                   one issue, its edges and its comments
  wfr.py add FILE --kind K --title "..." --parent N [--body -]
  wfr.py set FILE ID key value [key value ...]
                                        keys: title kind status assignee body
                                        parent; status is open or closed
  wfr.py block FILE ID --on N [N ...]   ID is blocked by N; wire every
                                        dependency you can name
  wfr.py unblock FILE ID --on N [N ...]
  wfr.py claim FILE ID [WHO]            WHO defaults to you; "" releases
  wfr.py comment FILE ID < notes.md     append a comment (research notes too)
  wfr.py resolve FILE ID [--oos] [--picked N] [--supersedes M] [--adr]
                        < answer.md
  wfr.py option FILE ISSUE [--add "..." [--body -]] [--rm N]
  wfr.py recommend FILE ISSUE [--option N] < why.md
  wfr.py gist FILE ID ["..."] [--oos|--decision]
                                        rewrite a closed issue's map line
  wfr.py term FILE [NAME] [--def "..."] [--avoid "..."] [--group G]
                    [--issue N] [--rm]  the glossary
  wfr.py adr FILE [ID] [--no]           mark a decision worth publishing
  wfr.py research FILE [ID] [--title "..."] [--issue N ...]
                        [--from PATH.md|--body -]     the research store
  wfr.py put FILE PATH [--issue N ...] < code   write (or replace) one file
  wfr.py cat FILE PATH                  print one prototype file
  wfr.py ls FILE [PREFIX]               list the prototype folder
  wfr.py rm FILE PATH                   drop one prototype file
  wfr.py import FILE DIR [--as P] [--issue N ...]  slurp a real directory in
  wfr.py export FILE DIR                write everything back out to disk:
                                        DIR/issues, DIR/research, DIR/proto,
                                        and, in the layout a repo expects,
                                        DIR/CONTEXT.md and DIR/docs/adr/
  wfr.py serve FILE [--port 8080]       browse at http://127.0.0.1:8080
  wfr.py selftest                       exercise the whole flow in a temp file

  A value of - means "read this from stdin", at most one per command:
      wfr.py set FILE 1 body - < map.md
      wfr.py add FILE --kind grilling --title "..." --parent 1 --body - < q.md
  resolve and comment always read stdin, so they need no -.

  term, research, adr and option share one shape: bare lists the store, a
  NAME or ID alone reads one, and a flag writes.

RESOLVING
  The answer is shaped like a git commit message:

      Subject line, becomes the gist
      <blank>
      The body, becomes the resolution comment.

  The subject is stored once, as the issue's gist; the body holds only what
  the subject does not say. The map, show and the ADR all compose the two, so
  a restated subject is a second copy, and the copy is what rots.

  One resolve is one transaction: it posts the comment, closes the issue and
  writes the gist to the map. It cannot half-resolve. A one-line answer is
  valid and leaves no comment. With no map the gist has nowhere to land, so
  it is skipped and the rest still happens.

      wfr.py resolve FILE 4 < answer.md          -> map "%s"
      wfr.py resolve FILE 4 --oos < why.md       -> map "%s"

  --oos is for an issue that sits past the destination: different section,
  deliberately not a decision.

OPTIONS AND RECOMMENDATIONS
  A grilling round has a shape: a question, the ways it could be answered,
  and the agent's steer. The question is the issue. The options are rows on
  it, and the steer is one recommendation on it.

      wfr.py option FILE 2 --add "Personal calendar only"
      wfr.py option FILE 2 --add "Availability booking" --body -
      wfr.py recommend FILE 2 --option 4 < why.md
      wfr.py option FILE 2                 list them, and the steer

  --parent is required on every add, and it is a real choice: a question that
  another question opened hangs off THAT question, not off the root, so the
  tree records what led to what. Only a question the effort raises on its own
  belongs directly under the map.

  Only the question resolves, and its gist is the answer - which in practice
  is often none of the options exactly ("(b), but not for the reason given").
  That answer, and why the others lost, is the resolution on the issue. A
  human choosing differently from the recommendation is not recommending:
  that reasoning is the resolution, or a comment.

  Record where the answer landed as you resolve:

      wfr.py resolve FILE 5 --picked 2 < answer.md   the answer is option 2
      wfr.py resolve FILE 5 --picked 0 < answer.md   none of them; see the gist

  wfr itself writes that pick into the head of the comment, in bold on its
  own line; leave it out of your own body, where the second copy is the one
  that goes stale. Omit --picked and nothing is claimed. Where picked and the
  recommendation differ, the steer was overruled - that pair is the one worth
  reading.

  An ADR's Considered Options lists the option titles and links the issue
  once. It does not repeat which one was taken or why the rest were not: that
  is settled on the issue, and saying it twice is how the two copies drift.

REVISING A DECISION
  The map is current state, not a log. A changed decision is rewritten where
  it stands, and the section is never reordered.

      wfr.py gist FILE 7 "the corrected one-liner"
      wfr.py gist FILE 7 --oos             move it to "%s"
      wfr.py gist FILE 7 --decision        and back

  Text is optional: with it the summary changes, without it only the
  section. At most one line per closed issue, keyed by its own /i/N link, so
  gist finds it wherever it sits.

  The two owned sections belong to resolve and gist; a body rewrite that
  races either drops a decision, so round-trip them unchanged and rewrite
  the fog and the Notes freely. To change a line use gist; to rule an issue
  out of scope use resolve --oos.

  What changed and why goes on the issue as a further comment. The map issue
  accepts comments too, but the map is an index - keep the argument on the
  issue holding the decision.

SUPERSEDING
  Not out-of-scope, which is work past the destination. Superseded means a
  decision stood and a later one has replaced it.

      wfr.py resolve FILE 9 --supersedes 4 < why.md

  #4 must be closed and not already superseded. #4 flips to superseded,
  points forward at #9, and its line is rewritten in place. It keeps its
  comment: the reasoning that was true then is still on it.

DECISION RECORDS
  An ADR is not a separate artifact: it is a closed issue worth publishing.
  The comments are the argument, and the issue's options are the Considered
  Options. The issue's own title stays the question it always was - an ADR
  needs its own title, required at the point of marking, stating the
  decision on its own terms rather than in answer to the question.

      wfr.py resolve FILE 7 --adr --adr-title "..." < answer.md
                                             mark it as it resolves
      wfr.py adr FILE 7 --title "..."       or afterwards

  A resolution that passes all three tests OWES an ADR - hard to reverse,
  surprising to a later reader, and the result of a real trade-off. Mark it
  as it resolves. Most decisions are not ADRs; the ones that are do not
  become ADRs by being remembered later.

  The number is assigned once, highest so far plus one, and never moves:
  marking an older issue later renumbers nothing already published, and
  unmarking leaves a gap rather than reusing a number. Status names a
  successor by ADR number.

GLOSSARY
  One row per term, keyed on the name and case-blind: "Order" and "order"
  are one term, so a clash is found rather than guessed at.

      wfr.py term FILE Order --def "..." --avoid "purchase, transaction"

  --avoid is enforced both ways: reading an avoided word answers with the
  canonical term, and defining one as a term of its own is refused.

  A definition says what a thing IS, in one or two sentences. No
  implementation detail and no rationale - if it contains "because", that
  belongs on the issue, and --issue N is the link that points there.

RESEARCH
  A whole markdown artifact kept as text, numbered r1, r2 ... read at /r/2.
  An ID with flags writes, rewriting the body only when given one (--from
  PATH.md, or --body - for stdin). --from takes the title from the doc's own
  "# ..." heading.

THE PROTOTYPE FOLDER
  A virtual folder inside the .wf: paths, no directories of its own. Nothing
  on disk, so a prototype survives a cleaned worktree. rm drops scratch code,
  never an issue.

CROSS-ISSUE LINKS
  --issue takes every issue an artifact serves: first is primary, the rest
  secondary (shown "also"), and the list replaces what was there.

      wfr.py research FILE 2 --issue 7 3 9   primary #7, also #3 and #9
      wfr.py research FILE 2 --issue 0       linked to nothing

  Links are only what --issue says - a "#3" in prose is a heading, in code a
  comment. Dropping a prototype file drops its links with it.

      for m in research/*.md; do wfr.py research FILE --from "$m"; done

BROWSING
  serve has five tabs, with breadcrumbs under them:
      /       Issues       the whole tree
      /g/     Glossary     the glossary
      /a/     Decisions    the ADRs, /a/N for one
      /r/     Research     the research store, /r/ID for one
      /p/     Prototypes   file tree left, raw code right; ?raw for plain text

GOTCHAS
  - Claim before working, or two sessions do the same issue.
  - A dead session leaves an issue claimed forever, invisible to the frontier.
    Release it: claim FILE ID ""
  - wfr owns two map headings, "%s" and "%s". set refuses a body that alters
    either - round-trip them unchanged and edit the fog and the Notes. To
    change a line use gist; to rule an issue out of scope use resolve --oos.
  - Nothing is deleted. An issue ruled out of scope is closed, not removed.
  - A question that must wait for another question is not an option row on
    it; it still needs: block FILE THIS --on THAT
  - If you can say in prose that one question gates another, WIRE IT. A
    dependency argued in a body and not blocked is a claim the tracker
    cannot see, so a second session takes the gated question first and
    answers it without the thing it depended on.
  - A block that would close a cycle is refused: every issue on it would
    leave the frontier for good, and nothing would say why.
""" % (DECISIONS, OUT_OF_SCOPE, OUT_OF_SCOPE, DECISIONS, OUT_OF_SCOPE)


def die(msg):
    sys.exit(PROG.split('.')[0] + ': ' + msg)


def read_stdin(what):
    if sys.stdin.isatty():
        die('%s reads from stdin; redirect a file into it' % what)
    return sys.stdin.read()


# ---------------------------------------------------------------- store

def connect(path, create=False):
    if not create and not os.path.exists(path):
        die('no such tracker: %s (make one with: %s init %s)' % (path, PROG, path))
    db = sqlite3.connect(path, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=5000')
    db.executescript(EXTRA_SCHEMA)
    if 'issue' not in {r[1] for r in db.execute('PRAGMA table_info(proto)')}:
        db.execute('ALTER TABLE proto ADD COLUMN issue INTEGER REFERENCES issue(id)')
    cols = {r[1] for r in db.execute('PRAGMA table_info(issue)')}
    if cols and 'verdict' not in cols:
        db.execute("ALTER TABLE issue ADD COLUMN verdict TEXT NOT NULL DEFAULT ''")
    if cols and 'gist' not in cols:
        db.execute("ALTER TABLE issue ADD COLUMN gist TEXT NOT NULL DEFAULT ''")
    if cols and 'adr_title' not in cols:
        db.execute("ALTER TABLE issue ADD COLUMN adr_title TEXT NOT NULL DEFAULT ''")
    if cols and 'superseded_by' not in cols:
        db.execute('ALTER TABLE issue ADD COLUMN superseded_by INTEGER REFERENCES issue(id)')
    if cols and 'adr' not in cols:
        db.execute('ALTER TABLE issue ADD COLUMN adr INTEGER NOT NULL DEFAULT 0')
    if cols and 'recommendation' not in cols:
        db.execute("ALTER TABLE issue ADD COLUMN recommendation TEXT NOT NULL DEFAULT ''")
    if cols and 'recommends' not in cols:
        db.execute('ALTER TABLE issue ADD COLUMN recommends INTEGER')
    # three states on purpose: NULL never recorded, 0 none of the options,
    # N option N. Defaulting the past to 0 would assert 32 answers were
    # freeform when nobody ever said so.
    if cols and 'picked' not in cols:
        db.execute('ALTER TABLE issue ADD COLUMN picked INTEGER')
    # KINDS lives in a CHECK constraint, and SQLite cannot alter one, so a file
    # made before a kind existed would reject it forever. Rebuild the table
    # when its constraint is behind - the only way to add a kind to an old .wf.
    # option.label was text before it became a stable per-question number.
    odl = db.execute("SELECT sql FROM sqlite_master WHERE name='option'").fetchone()
    if odl and 'label   TEXT' in odl[0]:
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('DROP TABLE IF EXISTS option_new')
            db.execute(EXTRA_SCHEMA[EXTRA_SCHEMA.index('CREATE TABLE IF NOT EXISTS option('):]
                       .split(');')[0].replace('option(', 'option_new(', 1) + ');')
            db.execute('INSERT INTO option_new(id,issue,label,title,body,created)'
                       ' SELECT id,issue,0,title,body,created FROM option')
            db.execute('DROP TABLE option')
            db.execute('ALTER TABLE option_new RENAME TO option')
            for q in [r[0] for r in db.execute('SELECT DISTINCT issue FROM option')]:
                for i, o in enumerate(db.execute('SELECT id FROM option WHERE issue=?'
                                                 ' ORDER BY id', (q,)).fetchall(), 1):
                    db.execute('UPDATE option SET label=? WHERE id=?', (i, o[0]))
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
        db.execute('COMMIT')
    ddl = db.execute("SELECT sql FROM sqlite_master WHERE name='issue'").fetchone()
    if ddl and any("'%s'" % k not in ddl[0] for k in KINDS):
        db.execute('PRAGMA foreign_keys=OFF')
        one = SCHEMA[SCHEMA.index('CREATE TABLE issue('):]
        one = one[:one.index(');') + 2].replace('issue(', 'issue_new(', 1)
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('DROP TABLE IF EXISTS issue_new')   # a crashed rebuild
            db.execute(one)          # one statement: executescript would commit
            db.execute('INSERT INTO issue_new(%s) SELECT %s FROM issue'
                       % (ISSUE_COLS, ISSUE_COLS))
            db.execute('DROP TABLE issue')
            db.execute('ALTER TABLE issue_new RENAME TO issue')
        except BaseException:
            # only if one is open: a rollback that itself throws would bury the
            # error that actually caused the failure.
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
        db.execute('COMMIT')
        db.execute('PRAGMA foreign_keys=ON')
    return db


def issue(db, iid):
    r = db.execute('SELECT * FROM issue WHERE id=?', (iid,)).fetchone()
    if not r:
        die('no issue #%s' % iid)
    return r


def blockers(db, iid):
    return [r['blocker'] for r in
            db.execute('SELECT blocker FROM blocks WHERE blocked=? ORDER BY blocker', (iid,))]


def waiting(db, iid):
    return [r['id'] for r in db.execute(
        'SELECT i.id FROM blocks b JOIN issue i ON i.id=b.blocker '
        "WHERE b.blocked=? AND i.status<>'closed' ORDER BY i.id", (iid,))]


def options(db, qid):
    """The options weighed on one question. Not issues: an option is a way the
    question could have been answered, never a unit of work, never on the
    frontier and never on the map. The answer is the question's gist, which
    in practice is often none of the options exactly."""
    return db.execute('SELECT * FROM option WHERE issue=? ORDER BY id',
                      (qid,)).fetchall()


def opt_label(o):
    return '%d. %s' % (o['label'], o['title'])


def next_label(db, qid):
    """Highest label on this question plus one. Never reused, so a gap after
    a removal is real: renumbering would misname whatever points at item 3."""
    return db.execute('SELECT COALESCE(MAX(label),0)+1 AS n FROM option WHERE issue=?',
                      (qid,)).fetchone()['n']


def opt_pos(db, qid, oid):
    """The label of this option, or 0 for no item: a question may carry a
    recommendation with no option to point at, and then the paragraph is the
    whole of it."""
    o = db.execute('SELECT label FROM option WHERE id=? AND issue=?', (oid, qid)).fetchone()
    return o['label'] if o else 0


def avoid_list(s):
    return [w.strip() for w in s.split(',') if w.strip()]


def term_row(db, name):
    """name collates NOCASE, so this is the collision check as well as the
    lookup: "Order" and "order" are one term, which is the point."""
    return db.execute('SELECT * FROM term WHERE name=?', (name,)).fetchone()


def term_clash(db, word):
    """Terms whose _Avoid_ list already claims this word."""
    w = word.strip().lower()
    return [r for r in db.execute('SELECT * FROM term ORDER BY name')
            if w in [x.lower() for x in avoid_list(r['avoid'])]]


def adrs(db):
    """ADR-marked issues in ADR order. issue.adr holds the number itself, not
    a flag: it is assigned once and never moves, so marking an older issue
    later cannot renumber the ones already published."""
    return db.execute('SELECT * FROM issue WHERE adr>0 ORDER BY adr').fetchall()


def next_adr(db):
    """Highest existing number plus one - the rule ADR-FORMAT states. Unmarking
    leaves a gap, which is correct: an ADR number is never reused."""
    return db.execute('SELECT COALESCE(MAX(adr),0)+1 AS n FROM issue').fetchone()['n']


def adr_no(db, iid):
    return issue(db, iid)['adr'] or None


def the_root(db):
    r = db.execute('SELECT * FROM issue WHERE parent IS NULL ORDER BY id').fetchone()
    if not r:
        die('this tracker has no root issue')
    return r


def the_map(db):
    """The map, or None: a tracker may have at most one, and need have none."""
    rows = db.execute("SELECT * FROM issue WHERE kind='map' ORDER BY id").fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        die('this tracker has %d map issues (#%s); wayfinder expects one'
            % (len(rows), ', #'.join(str(r['id']) for r in rows)))
    return rows[0]


def state(db, r):
    if r['status'] == 'closed':
        return 'closed'
    if r['parent'] is None:
        return 'open'
    if r['assignee']:
        return 'claimed'
    return 'blocked' if waiting(db, r['id']) else 'frontier'


def touch(db, iid):
    db.execute("UPDATE issue SET updated=datetime('now') WHERE id=?", (iid,))


# ---------------------------------------------------------------- map body

def _span(body, heading):
    """Where one owned section starts and ends. None when it is missing."""
    m = re.search(r'^##[ \t]+%s[ \t]*$' % re.escape(heading), body, re.M)
    if not m:
        return None
    rest = body[m.end():]
    nxt = re.search(r'^##[ \t]', rest, re.M)
    return m.end(), m.end() + (nxt.start() if nxt else len(rest))


def append_section(body, heading, line):
    span = _span(body, heading)
    if not span:
        die('refusing to write: the map body has no "## %s" heading' % heading)
    cut = span[1]
    out = body[:cut].rstrip('\n') + '\n' + line + '\n'
    tail = body[cut:].lstrip('\n')
    return out + '\n' + tail if tail else out


def replace_section(body, heading, text):
    """An owned heading inside an issue body, the way the map owns two of its
    own: wfr writes what sits under it, so whatever prose was there is
    replaced. Appended when the heading is not present at all."""
    span = _span(body, heading)
    if span is None:
        return (body.rstrip() + '\n\n' if body.strip() else '') + \
               '## %s\n\n%s\n' % (heading, text)
    lo, hi = span
    tail = body[hi:].lstrip('\n')
    return body[:lo] + '\n\n' + text + '\n' + ('\n' + tail if tail else '')


OPTIONS, RECOMMENDATION = 'Options', 'Recommendation'


def issue_body(db, r):
    """The body as a reader should see it: the author's prose, with the two
    owned sections written from the tables over whatever was there."""
    body, opts = r['body'], options(db, r['id'])
    if opts:
        body = replace_section(body, OPTIONS, '\n'.join(
            '%d. **%s**%s' % (o['label'], o['title'],
                              ' - ' + o['body'].strip().replace('\n', ' ')
                              if o['body'].strip() else '')
            for o in opts))
    if r['recommendation'].strip():
        pos = opt_pos(db, r['id'], r['recommends'])
        body = replace_section(body, RECOMMENDATION, r['recommendation'].strip() +
                               ('\n\nOption %d.' % pos if pos else ''))
    return body


def _line_re(iid):
    return re.compile(r'^- \[[^\]]*\]\(/i/%d\):.*$' % iid, re.M)


def line_section(body, iid):
    """Which owned heading currently carries iid's line, if any."""
    for heading in (DECISIONS, OUT_OF_SCOPE):
        span = _span(body, heading)
        if span and _line_re(iid).search(body[span[0]:span[1]]):
            return heading
    return None


def drop_line(body, iid):
    """Drop iid's line from the two owned sections. Matches only the shape wfr
    writes and only inside its own headings, so fog and Notes prose is safe."""
    for heading in (DECISIONS, OUT_OF_SCOPE):
        span = _span(body, heading)
        if not span:
            continue
        lo, hi = span
        cut = re.sub(r'\n?' + _line_re(iid).pattern, '', body[lo:hi], flags=re.M)
        body = body[:lo] + cut + body[hi:]
    return body


def seed_map(body):
    """Append whatever the map skeleton is missing, keeping what is there. An
    issue promoted to a map after init has no headings, and without them
    resolve and gist have nowhere to write."""
    out = body.rstrip()
    for h in re.findall(r'^## (.+)$', MAP_SKELETON, re.M):
        if _span(out, h) is None:
            out += '\n\n## %s\n' % h
    return out.lstrip('\n') + '\n'


def check_owned(old, new):
    """resolve and gist write the two owned sections; set does not. Round-trip
    them unchanged and the rest of the body is yours. Change one and this
    refuses: silently keeping the stored text would throw away what the caller
    wrote, which is the same fault as silently dropping the decisions was."""
    for heading in (DECISIONS, OUT_OF_SCOPE):
        so, sn = _span(old, heading), _span(new, heading)
        if so is None:
            continue          # absent from the stored body: adding it is a repair
        if sn is None:
            die('the map body must keep its "## %s" heading' % heading)
        if old[so[0]:so[1]].strip() != new[sn[0]:sn[1]].strip():
            die('"## %s" is written by resolve and gist, not by set: submit it '
                'unchanged. To correct a line use gist; to rule an issue out of '
                'scope use resolve --oos.' % heading)


def set_line(body, iid, line, heading):
    """The map is current state, not a log: one line per closed issue, keyed
    by its own /i/N link. A line already under this heading is substituted
    where it stands, so revising a decision does not reorder the section;
    otherwise it is dropped from wherever it sat and appended here."""
    span = _span(body, heading)
    if span and _line_re(iid).search(body[span[0]:span[1]]):
        lo, hi = span
        # a lambda, not a replacement string: a gist may contain backslashes
        return body[:lo] + _line_re(iid).sub(lambda _: line, body[lo:hi], count=1) + body[hi:]
    return append_section(drop_line(body, iid), heading, line)


def verdict_label(r):
    """What the verdict reads as, with supersession naming its successor."""
    if r['verdict'] == 'superseded' and r['superseded_by']:
        return 'superseded by #%d' % r['superseded_by']
    return r['verdict']


def on_the_map(r):
    """Every closed issue but the root takes a line. Options are no longer
    issues at all, so there is nothing left to exclude."""
    return r['parent'] is not None


def lead_in(note, body):
    """Fold the pick into the comment as markdown, as its own paragraph above
    the reasoning: where the answer landed is a statement in its own right,
    not a label on the argument that follows."""
    return '**%s**\n\n%s' % (note, body) if note else body


def picked_note(r):
    """What the resolution landed on. None when it was never recorded - an
    issue closed before the flag existed says nothing rather than claiming
    its answer was freeform."""
    if r['picked'] is None:
        return None
    return 'Option %d.' % r['picked'] if r['picked'] else 'None of the options.'


def line_note(db, r):
    """What qualifies a decision: what replaced it, or what it was weighed
    against. One definition, so the map text and the served page agree."""
    v = verdict_label(r)
    if v:
        return v
    k = len(options(db, r['id']))
    return 'weighed %d option%s' % (k, '' if k == 1 else 's') if k else ''


def gist_line(db, r):
    """An issue's map line, built from the issue every time. Nothing ever
    parses a rendered line back into fields."""
    v = line_note(db, r)
    return '- [%s](/i/%d): %s%s' % (r['title'], r['id'],
                                    v + ' - ' if v else '', r['gist'])


# ---------------------------------------------------------------- markdown

def _inline(s):
    """s is already HTML-escaped."""
    holes = []

    def stash(m):
        holes.append('<code>%s</code>' % m.group(1))
        return '\x00%d\x00' % (len(holes) - 1)

    s = re.sub(r'`([^`]+)`', stash, s)

    def link(m):
        text, url = m.group(1), m.group(2)
        if url.startswith('//') or not re.match(
                r'(https?://|/|#|\.{0,2}/|[\w.\-]+\.md)', url, re.I):
            return m.group(0)     # not a URL we emit; falls back to literal text
        return '<a href="%s">%s</a>' % (url, text)

    s = re.sub(r'\[([^\]]*)\]\(([^)\s]+)\)', link, s)
    s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
    # Emphasis after strong, so only single markers are left. The underscore
    # form is what CONTEXT.md's own "_Avoid_" uses; the lookarounds keep it
    # off snake_case_names, where the underscores are part of the word.
    s = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'<em>\1</em>', s)
    s = re.sub(r'\*(\S[^*]*?)\*', r'<em>\1</em>', s)
    return re.sub(r'\x00(\d+)\x00', lambda m: holes[int(m.group(1))], s)


def _row(line):
    """Split one pipe-table row. ponytail: a literal | inside a cell (even in
    backticks) splits it; escape-aware splitting if that ever shows up."""
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|'):
        s = s[:-1]
    return [c.strip() for c in s.split('|')]


def _is_sep(line):
    cells = _row(line)
    return bool(cells) and all(re.fullmatch(r':?-+:?', c) for c in cells)


def markdown(text):
    """The documented subset: headings, fenced and indented code, inline
    code, bold, links,
    bullet and numbered lists, blockquotes, pipe tables, paragraphs. Anything
    else survives as escaped text.
    A wrapped line continues the list item above it (lazy continuation).
    ponytail: list nesting is flattened -- an indented item joins its parent
    list. Real nesting if a document ever needs it.
    ponytail: hand-rolled subset, swap in a real renderer if notes outgrow it."""
    out, para, lst, quote = [], [], [], []
    L = {'tag': 'ul', 'start': 1}

    def flush():
        if para:
            out.append('<p>%s</p>' % _inline(' '.join(para)));  para.clear()
        if lst:
            attr = ' start="%d"' % L['start'] if L['tag'] == 'ol' and L['start'] != 1 else ''
            items, nxt = [], L['start']
            for num, txt in lst:
                # a number that skips is kept: 1, 3, 4 is a list with a gap,
                # and renumbering it would misname whatever points at item 3.
                v = ''
                if L['tag'] == 'ol' and num is not None and num != nxt:
                    v, nxt = ' value="%d"' % num, num
                items.append('<li%s>%s</li>' % (v, _inline(txt)))
                nxt += 1
            out.append('<%s%s>%s</%s>' % (L['tag'], attr, ''.join(items), L['tag']))
            lst.clear()
        if quote:
            out.append('<blockquote>%s</blockquote>' % _inline(' '.join(quote))); quote.clear()

    lines, i = text.split('\n'), 0
    while i < len(lines):
        raw = lines[i]
        if raw.lstrip().startswith('```'):
            flush(); i += 1; code = []
            while i < len(lines) and not lines[i].lstrip().startswith('```'):
                code.append(lines[i]); i += 1
            out.append('<pre><code>%s</code></pre>' % html.escape('\n'.join(code)))
            i += 1; continue
        if (re.match(r'(?: {4}|\t)\S', raw) and not (para or lst or quote)
                and (i == 0 or not lines[i - 1].strip())):
            code = []                          # indented code block
            while i < len(lines) and (re.match(r'(?: {4}|\t)', lines[i])
                                      or not lines[i].strip()):
                code.append(re.sub(r'^(?: {4}|\t)', '', lines[i]))
                i += 1
            while code and not code[-1].strip():
                code.pop()
            out.append('<pre><code>%s</code></pre>' % html.escape('\n'.join(code)))
            continue
        if '|' in raw and i + 1 < len(lines) and _is_sep(lines[i + 1]):
            flush()
            head = [_inline(html.escape(c)) for c in _row(raw)]
            align = [('center' if c.startswith(':') and c.endswith(':') else
                      'right' if c.endswith(':') else
                      'left' if c.startswith(':') else '') for c in _row(lines[i + 1])]
            i += 2
            rows = []
            while i < len(lines) and '|' in lines[i] and lines[i].strip():
                rows.append([_inline(html.escape(c)) for c in _row(lines[i])])
                i += 1

            def cell(tag, v, n):
                a = align[n] if n < len(align) else ''
                return '<%s%s>%s</%s>' % (tag, ' style="text-align:%s"' % a if a else '',
                                          v, tag)
            out.append('<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (
                ''.join(cell('th', v, n) for n, v in enumerate(head)),
                ''.join('<tr>%s</tr>' % ''.join(
                    cell('td', r[n] if n < len(r) else '', n) for n in range(len(head)))
                    for r in rows)))
            continue
        line = html.escape(raw)
        h = re.match(r'(#{1,6})[ \t]+(.*)$', line)
        if h:
            flush(); n = len(h.group(1))
            out.append('<h%d>%s</h%d>' % (n, _inline(h.group(2).strip()), n))
        elif re.match(r'[ \t]*(?:[-*]|\d+[.)])[ \t]+', line):
            m = re.match(r'[ \t]*(?:([-*])|(\d+)[.)])[ \t]+(.*)$', line)
            tag = 'ul' if m.group(1) else 'ol'
            if para or quote or (lst and L['tag'] != tag):
                flush()
            if not lst:
                L['tag'] = tag
                L['start'] = int(m.group(2)) if tag == 'ol' else 1
            lst.append((int(m.group(2)) if m.group(2) else None, m.group(3)))
        elif line.startswith('&gt;'):
            if para or lst: flush()
            quote.append(re.sub(r'^&gt;[ \t]?', '', line))
        elif not line.strip():
            flush()
        else:
            if quote: flush()
            if lst:
                lst[-1] = (lst[-1][0], lst[-1][1] + ' ' + line.strip())  # lazy continuation
            else:
                para.append(line)
        i += 1
    flush()
    return '\n'.join(out)


# ---------------------------------------------------------------- proto

def vpath(p):
    """A folder path: no leading slash, no .. escaping into the real disk."""
    parts = [s for s in p.replace('\\', '/').split('/') if s not in ('', '.')]
    if any(s == '..' for s in parts):
        die('a folder path cannot contain ..: %r' % p)
    if not parts:
        die('that is not a path: %r' % p)
    return '/'.join(parts)


def proto_dir(db, d):
    """What sits directly under directory d ('' is the root): dirs, files."""
    pre = d + '/' if d else ''
    dirs, files = set(), []
    for r in db.execute('SELECT path FROM proto ORDER BY path'):
        if not r['path'].startswith(pre):
            continue
        rest = r['path'][len(pre):]
        (dirs.add(rest.split('/')[0]) if '/' in rest else files.append(rest))
    return sorted(dirs), files


def slug(s):
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', s.lower())).strip('-')[:60] or 'untitled'


# ---------------------------------------------------------------- commands

def cmd_init(a):
    if os.path.exists(a.file):
        die('%s already exists' % a.file)
    db = connect(a.file, create=True)
    db.executescript(SCHEMA)
    db.execute('INSERT INTO issue(id,kind,title,body) VALUES(1,?,?,?)',
               (a.kind, a.title, MAP_SKELETON if a.kind == 'map' else ''))
    print('#1  %s  %s' % (a.kind, a.title))
    print('%s ready. Next: add issues with --parent 1.' % a.file)


def cmd_add(a):
    db = connect(a.file)
    body = read_stdin('--body -') if a.body == '-' else (a.body or '')
    issue(db, a.parent)     # required: no default is right for both a follow-up
    #                         and an independent question, and a default that
    #                         picks the root quietly flattens every tree
    db.execute('BEGIN IMMEDIATE')
    cur = db.execute('INSERT INTO issue(kind,title,body,parent) VALUES(?,?,?,?)',
                     (a.kind, a.title, body, a.parent))
    db.execute('COMMIT')
    print('#%d  %s  %s' % (cur.lastrowid, a.kind, a.title))


def cmd_set(a):
    if len(a.pairs) % 2:
        die('set takes key value pairs; got an odd number of words')
    fields = dict(zip(a.pairs[::2], a.pairs[1::2]))
    allowed = ('title', 'kind', 'status', 'assignee', 'body', 'parent')
    for k in fields:
        if k not in allowed:
            die('cannot set %r; settable: %s' % (k, ' '.join(allowed)))
    if list(fields.values()).count('-') > 1:
        die('only one value may be - (stdin) per command')
    db = connect(a.file)
    r = issue(db, a.id)
    for k, v in fields.items():
        if v == '-':
            fields[k] = read_stdin('%s -' % k)
    if 'body' in fields and r['kind'] == 'map' and r['parent'] is None:
        check_owned(r['body'], fields['body'])
    if fields.get('kind') == 'map':
        # becoming a map means gaining the headings resolve and gist write to
        fields['body'] = seed_map(fields.get('body', r['body']))
    if 'kind' in fields and fields['kind'] not in KINDS:
        die('unknown kind %r; the kinds are: %s' % (fields['kind'], ' '.join(KINDS)))
    if fields.get('kind') == 'map' and the_root(db)['id'] != a.id:
        die('a tracker has one map and it is the root; #%d cannot become a second'
            % a.id)
    if 'status' in fields and fields['status'] not in ('open', 'closed'):
        die('status is open or closed, not %r' % fields['status'])
    if 'parent' in fields:
        p = int(fields['parent']) if fields['parent'] else None
        if p:
            issue(db, p)
            seen, walk = {a.id}, p
            while walk:                       # a parent cycle would hang the tree
                if walk in seen:
                    die('#%s cannot be a parent of #%s: that makes a cycle' % (p, a.id))
                seen.add(walk)
                walk = issue(db, walk)['parent']
        fields['parent'] = p
    db.execute('BEGIN IMMEDIATE')
    db.execute('UPDATE issue SET %s, updated=datetime(\'now\') WHERE id=?'
               % ', '.join('%s=?' % k for k in fields),
               list(fields.values()) + [a.id])
    db.execute('COMMIT')
    print('#%d  %s' % (a.id, ', '.join(sorted(fields))))


def cmd_block(a):
    db = connect(a.file)
    issue(db, a.id)
    db.execute('BEGIN IMMEDIATE')
    for b in a.on:
        issue(db, b)
        if b == a.id:
            die('#%d cannot block itself' % a.id)
        if not a.unblock:
            # Walk what already blocks the new blocker. A cycle would take
            # every issue on it off the frontier for good, and silently.
            seen, walk = set(), [b]
            while walk:
                cur = walk.pop()
                if cur == a.id:
                    die('#%s cannot block #%s: that closes a cycle, and every issue '
                        'on it would leave the frontier for good' % (b, a.id))
                if cur not in seen:
                    seen.add(cur)
                    walk += blockers(db, cur)
        if a.unblock:
            db.execute('DELETE FROM blocks WHERE blocked=? AND blocker=?', (a.id, b))
        else:
            db.execute('INSERT OR IGNORE INTO blocks(blocked,blocker) VALUES(?,?)', (a.id, b))
    touch(db, a.id)
    db.execute('COMMIT')
    w = blockers(db, a.id)
    print('#%d blocked by %s' % (a.id, ' '.join('#%d' % b for b in w) if w else '(nothing)'))


def cmd_claim(a):
    db = connect(a.file)
    r = issue(db, a.id)
    who = getpass.getuser() if a.who is None else a.who
    db.execute('BEGIN IMMEDIATE')          # the claim decides under the lock, or
    try:                                   # two sessions both think they got it
        if who:
            taken = db.execute("UPDATE issue SET assignee=?, updated=datetime('now')"
                               " WHERE id=? AND assignee IN ('', ?)",
                               (who, a.id, who)).rowcount == 0
            if taken:
                die('#%d is already claimed by %s'
                    % (a.id, issue(db, a.id)['assignee']))
        else:
            db.execute("UPDATE issue SET assignee='', updated=datetime('now')"
                       " WHERE id=?", (a.id,))
    except BaseException:
        db.execute('ROLLBACK')
        raise
    db.execute('COMMIT')
    print('#%d %s' % (a.id, ('claimed by ' + who) if who else 'released'))


def cmd_comment(a):
    db = connect(a.file)
    issue(db, a.id)
    text = read_stdin('comment').strip()
    if not text:
        die('refusing to post an empty comment')
    db.execute('BEGIN IMMEDIATE')
    db.execute('INSERT INTO comment(issue,body) VALUES(?,?)', (a.id, text))
    touch(db, a.id)
    db.execute('COMMIT')
    print('#%d  commented (%d chars)' % (a.id, len(text)))


def cmd_resolve(a):
    db = connect(a.file)
    r = issue(db, a.id)
    verdict = ''
    if r['parent'] is None:
        die('the root is not resolved like an issue; close it with: set FILE %d status closed' % a.id)
    if r['status'] == 'closed':
        die('#%d is already closed' % a.id)
    if a.picked:
        if not db.execute('SELECT 1 FROM option WHERE issue=? AND label=?',
                          (a.id, a.picked)).fetchone():
            die('#%d has no option %d; --picked names an option of this question, '
                'or 0 when the answer was none of them' % (a.id, a.picked))
    old = None
    if a.supersedes:
        if a.supersedes == a.id:
            die('#%d cannot supersede itself' % a.id)
        old = issue(db, a.supersedes)
        if old['status'] != 'closed' or old['verdict'] == 'superseded':
            die('#%d is not a standing decision, so there is nothing to supersede'
                % a.supersedes)
    if a.adr and not a.adr_title:
        die('an ADR needs its own title, the decision stated on its own terms - '
            'the issue stays the question: add --adr-title "..."')
    if a.adr_title and not a.adr:
        die('--adr-title needs --adr')
    text = read_stdin('resolve').strip('\n')
    lines = text.split('\n')
    subject = lines[0].strip()
    if not subject:
        die('the answer must open with a subject line: the gist for the map')
    if len(lines) > 1 and lines[1].strip():
        die('a subject line must be followed by a blank line, like a commit message')
    body = '\n'.join(lines[2:]).strip()
    heading = OUT_OF_SCOPE if a.oos else DECISIONS
    # Everything below runs under the write lock: the map is read *after*
    # BEGIN IMMEDIATE, or two concurrent resolves each append to the same
    # stale body and the second commit silently drops the first's decision.
    db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute("UPDATE issue SET status='closed', verdict=?, gist=?, adr=?,"
                      " adr_title=?, picked=?, updated=datetime('now') WHERE id=?"
                      " AND status='open'",
                      (verdict, subject, next_adr(db) if a.adr else 0, a.adr_title or '',
                       a.picked, a.id)).rowcount == 0:
            die('#%d was closed by another session' % a.id)
        mp = the_map(db)
        newbody = mp['body'] if mp else None
        if body:
            db.execute('INSERT INTO comment(issue,body) VALUES(?,?)', (a.id, body))
        # Losers close first and take no line: the winner's line counts them,
        # so it has to be built once they are actually rejected.
        if newbody is not None and on_the_map(issue(db, a.id)):
            newbody = set_line(newbody, a.id, gist_line(db, issue(db, a.id)), heading)
        if old is not None:
            db.execute("UPDATE issue SET verdict='superseded', superseded_by=?,"
                       " updated=datetime('now') WHERE id=?", (a.id, old['id']))
            if newbody is not None:
                where = line_section(newbody, old['id']) or DECISIONS
                newbody = set_line(newbody, old['id'],
                                   gist_line(db, issue(db, old['id'])), where)
        if mp:
            db.execute("UPDATE issue SET body=?, updated=datetime('now') WHERE id=?",
                       (newbody, mp['id']))
    except BaseException:
        db.execute('ROLLBACK')
        raise
    db.execute('COMMIT')
    print('#%d closed -> map "%s": %s' % (a.id, heading, subject) if mp else
          '#%d closed (no map to take the gist): %s' % (a.id, subject))
    if old is not None:
        print('     #%d is now SUPERSEDED by #%d' % (old['id'], a.id))


def cmd_gist(a):
    """Rewrite one map line in place. The map is a summary of where the effort
    stands now, so a decision that changes is corrected here, never appended
    to and never hand-edited out of the body by a caller."""
    db = connect(a.file)
    r = issue(db, a.id)
    if r['parent'] is None:
        die('the root is the map itself; it has no line on it')
    if r['status'] != 'closed':
        die('#%d is open; its line lands on the map when it resolves' % a.id)
    if a.text is not None and not a.text.strip():
        die('the gist is the one-line summary; it cannot be empty')
    db.execute('BEGIN IMMEDIATE')
    try:
        mp = the_map(db)
        if not mp:
            die('this tracker has no map, so there is no line to rewrite')
        where = OUT_OF_SCOPE if a.oos else DECISIONS if a.decision \
            else line_section(mp['body'], a.id)
        if where is None:
            die('#%d has no line on the map; add --decision or --oos to place one' % a.id)
        if a.text is not None:
            db.execute("UPDATE issue SET gist=?, updated=datetime('now') WHERE id=?",
                       (a.text.strip(), a.id))
        newbody = set_line(mp['body'], a.id, gist_line(db, issue(db, a.id)), where)
        db.execute("UPDATE issue SET body=?, updated=datetime('now') WHERE id=?",
                   (newbody, mp['id']))
    except BaseException:
        db.execute('ROLLBACK')
        raise
    db.execute('COMMIT')
    print('#%d -> map "%s": %s' % (a.id, where, issue(db, a.id)['gist']))


def cmd_term(a):
    """The glossary. Read with a name, write with a flag - the same duality
    research has. Definitions are keyed, so a clash is found, not guessed."""
    db = connect(a.file)
    if a.name is None:
        rows = db.execute('SELECT * FROM term ORDER BY grp, name').fetchall()
        if not rows:
            print('no terms yet.')
            return
        for r in rows:
            first = (r['body'].strip().split('\n') or [''])[0]
            print('%-22s %-52s%s' % (r['name'], first[:52],
                                     '  [%s]' % r['grp'] if r['grp'] else ''))
        return
    r = term_row(db, a.name)
    if a.rm:
        if not r:
            die('no term %r' % a.name)
        db.execute('DELETE FROM term WHERE name=?', (a.name,))
        print('dropped %r' % r['name'])
        return
    writing = any(v is not None for v in (a.definition, a.avoid, a.group, a.issue))
    if not writing:
        if r:
            print('%s\n%s' % (r['name'], r['body'].strip() or '(undefined)'))
            if avoid_list(r['avoid']):
                print('avoid: %s' % ', '.join(avoid_list(r['avoid'])))
            if r['grp']:
                print('group: %s' % r['grp'])
            if r['issue']:
                print('settled on: #%d' % r['issue'])
            return
        clash = term_clash(db, a.name)
        if clash:
            print('%r is not the word: it is avoided by %s' % (
                a.name, ', '.join(repr(c['name']) for c in clash)))
            return
        die('no term %r, and nothing avoids it' % a.name)
    if r is None:
        for c in term_clash(db, a.name):
            die('%r is already listed under _Avoid_ for %r; define that instead, '
                'or drop it from that avoid list first' % (a.name, c['name']))
    db.execute('BEGIN IMMEDIATE')
    try:
        if r is None:
            db.execute('INSERT INTO term(name) VALUES(?)', (a.name,))
        sets, vals = [], []
        for col, val in (('body', a.definition), ('avoid', a.avoid), ('grp', a.group)):
            if val is not None:
                sets.append('%s=?' % col)
                vals.append(val.strip())
        if a.issue is not None:
            if a.issue:
                issue(db, a.issue)
            sets.append('issue=?')
            vals.append(a.issue or None)
        sets.append("updated=datetime('now')")
        db.execute('UPDATE term SET %s WHERE name=?' % ', '.join(sets), vals + [a.name])
    except BaseException:
        db.execute('ROLLBACK')
        raise
    db.execute('COMMIT')
    print('%s  %s' % (term_row(db, a.name)['name'], 'defined' if r is None else 'updated'))


def cmd_adr(a):
    """Mark a resolved decision as worth publishing as an ADR. Most are not:
    the three tests are hard to reverse, surprising, and a real trade-off."""
    db = connect(a.file)
    if a.id is None:
        rows = adrs(db)
        if not rows:
            print('no ADRs yet.')
            return
        for r in rows:
            print('ADR-%04d  #%-4d %s%s' % (
                r['adr'], r['id'], r['adr_title'],
                '  ' + verdict_label(r).upper() if r['verdict'] else ''))
        return
    r = issue(db, a.id)
    if a.no:
        db.execute('UPDATE issue SET adr=0 WHERE id=?', (a.id,))
        print('#%d is no longer an ADR' % a.id)
        return
    if r['adr']:
        print('#%d is already ADR-%04d' % (a.id, r['adr']))
        return
    if r['status'] != 'closed':
        die('#%d is open; an ADR records a decision already made' % a.id)
    if not a.title:
        die('an ADR needs its own title, the decision stated on its own terms - '
            'the issue stays the question: adr FILE %d --title "..."' % a.id)
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('UPDATE issue SET adr=?, adr_title=? WHERE id=?',
                   (next_adr(db), a.title, a.id))
    except BaseException:
        db.execute('ROLLBACK')
        raise
    db.execute('COMMIT')
    print('#%d is ADR-%04d' % (a.id, adr_no(db, a.id)))


def cmd_option(a):
    """The ways a question could be answered. Options are the agent's framing
    of the choice, not work items: they never reach the frontier or the map."""
    db = connect(a.file)
    r = issue(db, a.issue)
    if a.rm:
        o = db.execute('SELECT * FROM option WHERE issue=? AND label=?',
                       (a.issue, a.rm)).fetchone()
        if not o:
            die('#%d has no option %s' % (a.issue, a.rm))
        if r['status'] == 'closed':
            die('#%d is closed: its options are the record of what was weighed, '
                'and dropping one now would rewrite that' % a.issue)
        db.execute('UPDATE issue SET recommends=NULL WHERE recommends=?', (o['id'],))
        db.execute('DELETE FROM option WHERE id=?', (o['id'],))
        print('#%d dropped option %d; the number is not reused' % (a.issue, a.rm))
        return
    if a.add:
        body = read_stdin('option --body') if a.body == '-' else a.body
        lab = next_label(db, a.issue)
        db.execute('INSERT INTO option(issue,label,title,body) VALUES(?,?,?,?)',
                   (a.issue, lab, a.add, body or ''))
        print('#%d option %d: %s' % (a.issue, lab, a.add))
        return
    opts = options(db, a.issue)
    if not opts:
        print('#%d has no options.' % a.issue)
    for o in opts:
        print('  %s%s' % (opt_label(o),
                          '   <- recommended' if r['recommends'] == o['id'] else ''))
    if r['recommendation']:
        print('\nrecommended: %s' % r['recommendation'])


def cmd_recommend(a):
    """The agent's recommendation on a question: which option it leans to and
    why. One per question. A human who picks an option for a different reason
    is not recommending - that reasoning is the resolution, or a comment."""
    db = connect(a.file)
    issue(db, a.issue)
    oid = None
    if a.option:
        o = db.execute('SELECT * FROM option WHERE issue=? AND label=?',
                       (a.issue, a.option)).fetchone()
        if not o:
            die('#%d has no option %s' % (a.issue, a.option))
        oid = o['id']
    body = read_stdin('recommend').strip()
    if not body:
        die('a recommendation needs a reason')
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute("UPDATE issue SET recommendation=?, recommends=?,"
                   " updated=datetime('now') WHERE id=?",
                   (body, oid, a.issue))
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise
    db.execute('COMMIT')
    print('#%d recommendation set%s' % (
        a.issue, ' (option %d)' % a.option if a.option
        else ' - no option named; add --option N to point at one'
        if options(db, a.issue) else ''))


def cmd_show(a):
    db = connect(a.file)
    r = issue(db, a.id)
    w = waiting(db, a.id)
    print('#%d  %s  %s' % (r['id'], r['kind'], r['title']))
    print('    %s%s%s%s' % (state(db, r),
                            '  ' + verdict_label(r).upper() if r['verdict'] else '',
                            '  @' + r['assignee'] if r['assignee'] else '',
                            '  parent #%s' % r['parent'] if r['parent'] else ''))
    if r['gist']:
        print('    gist: %s' % r['gist'])
    if picked_note(r):
        print('    picked: %s' % picked_note(r))
    if r['adr']:
        print('    ADR-%04d' % adr_no(db, a.id))
    for o in options(db, a.id):
        print('    option %-4d %s%s' % (o['id'], opt_label(o),
                                        '  <- recommended' if r['recommends'] == o['id'] else ''))
    if r['recommendation']:
        print('    recommended: %s' % r['recommendation'])
    b = blockers(db, a.id)
    if b:
        print('    blocked by %s%s' % (' '.join('#%d' % x for x in b),
                                       '  (waiting on %s)' % ' '.join('#%d' % x for x in w)
                                       if w else '  (all closed)'))
    kids = db.execute('SELECT id,title FROM issue WHERE parent=? ORDER BY id', (a.id,)).fetchall()
    for k in kids:
        print('    child #%d  %s' % (k['id'], k['title']))
    docs, files = refs(db, a.id)
    for i, (t, primary) in docs:
        print('    research r%d  %s%s' % (i, t, '' if primary else '  (also)'))
    for path, primary in files:
        print('    proto  %s%s' % (path, '' if primary else '  (also)'))
    if r['body'].strip():
        print('\n' + r['body'].rstrip())
    for c in db.execute('SELECT * FROM comment WHERE issue=? ORDER BY id', (a.id,)):
        print('\n--- comment %s ---\n%s' % (c['created'], c['body'].rstrip()))


def walk(db, parent=None, depth=0, acc=None, bars=()):
    """bars marks, for each ancestor level, whether a sibling still follows
    it (True) or it was the last child (False) - what draws the tree's
    vertical connectors down past a node that still has more coming."""
    acc = [] if acc is None else acc
    q = ('SELECT * FROM issue WHERE parent IS NULL ORDER BY id' if parent is None
         else 'SELECT * FROM issue WHERE parent=? ORDER BY id')
    kids = db.execute(q, () if parent is None else (parent,)).fetchall()
    for i, r in enumerate(kids):
        last = i == len(kids) - 1
        acc.append((depth, bars, last, r))
        walk(db, r['id'], depth + 1, acc, bars + (not last,))
    return acc


MARK = {'closed': 'done', 'open': 'open', 'frontier': 'FREE', 'claimed': 'work', 'blocked': 'wait'}


def cmd_map(a):
    db = connect(a.file)
    for depth, _bars, _last, r in walk(db):
        w = waiting(db, r['id'])
        st = state(db, r)
        print('%-4s  %-4s %s%-9s %s%s%s%s' % (
            MARK[st], '#%d' % r['id'], '  ' * depth, r['kind'], r['title'],
            '  ' + verdict_label(r).upper() if r['verdict'] else '',
            '  @' + r['assignee'] if r['assignee'] else '',
            '  waits %s' % ' '.join('#%d' % x for x in w) if w else ''))


def glossary_note(db):
    """Terms accrue as grills resolve, and a missing one leaves no trace of
    itself. Riding on frontier puts the count where the round already looks."""
    grills = db.execute("SELECT COUNT(*) FROM issue WHERE kind='grilling'"
                        " AND status='closed'").fetchone()[0]
    if not grills:
        return
    terms = db.execute('SELECT COUNT(*) FROM term').fetchone()[0]
    print('%d grilling resolved · %d in the glossary' % (grills, terms))


def cmd_frontier(a):
    db = connect(a.file)
    rows = [r for r in db.execute("SELECT * FROM issue WHERE status='open' AND assignee=''"
                                  ' AND parent IS NOT NULL ORDER BY id')
            if not waiting(db, r['id'])]
    if not rows:
        print('frontier empty: nothing open, unclaimed and unblocked.')
    for r in rows:
        print('#%-3d %-9s %s' % (r['id'], r['kind'], r['title']))
    glossary_note(db)


def links(db, ns):
    """--issue 3 7 9: the first is the primary, the rest are secondary.
    Returns (primary, secondaries); primary None means "leave as it was",
    0 means "clear the lot"."""
    if ns is None:
        return None, []
    if ns == [0]:
        return 0, []
    for n in dict.fromkeys(ns):
        issue(db, n)
    return ns[0], [n for n in dict.fromkeys(ns[1:]) if n != ns[0]]


def set_links(db, col, key, extra):
    """col is 'doc' or 'path' - ours, never a caller's word."""
    db.execute('DELETE FROM link WHERE %s=?' % col, (key,))
    for n in extra:
        db.execute('INSERT INTO link(issue,%s) VALUES(?,?)' % col, (n, key))


def issues_of(db, col, key, primary):
    """Every issue this artifact names, primary first."""
    rest = [r[0] for r in db.execute('SELECT issue FROM link WHERE %s=? ORDER BY issue' % col,
                                     (key,)) if r[0] != primary]
    return ([primary] if primary else []) + rest


def refs(db, iid):
    """The other way round: docs and files naming this issue, primary or not.
    Each comes back with a flag saying which."""
    docs = {r['id']: [r['title'], True] for r in
            db.execute('SELECT id,title FROM research WHERE issue=?', (iid,))}
    for r in db.execute('SELECT r.id id, r.title title FROM link l JOIN research r'
                        ' ON r.id=l.doc WHERE l.issue=?', (iid,)):
        docs.setdefault(r['id'], [r['title'], False])
    files = {r['path']: True for r in
             db.execute('SELECT path FROM proto WHERE issue=?', (iid,))}
    for r in db.execute('SELECT path FROM link WHERE issue=? AND path IS NOT NULL', (iid,)):
        files.setdefault(r['path'], False)
    return sorted(docs.items()), sorted(files.items())


def md_title(body, fallback):
    m = re.search(r'^#[ \t]+(.+)$', body, re.M)
    return m.group(1).strip() if m else fallback


def cmd_research(a):
    db = connect(a.file)
    wrote = a.title or a.frm or a.issue is not None or a.body == '-'
    if a.id and not wrote:                     # an id with no flags reads
        r = db.execute('SELECT body FROM research WHERE id=?', (a.id,)).fetchone()
        if not r:
            die('no research doc r%s' % a.id)
        return sys.stdout.write(r['body'])
    if not a.id and not wrote:                 # bare: list the store
        rows = db.execute('SELECT id,title,issue,updated,length(body) n FROM research'
                          ' ORDER BY id').fetchall()
        if not rows:
            print('no research docs yet. Add one with: research FILE --from notes.md')
        for r in rows:
            print('r%-3d %-10s %7d  %s  %s'
                  % (r['id'], ' '.join('#%d' % i for i in
                                       issues_of(db, 'doc', r['id'], r['issue'])),
                     r['n'], r['updated'], r['title']))
        return
    body = (open(a.frm, encoding='utf-8').read() if a.frm else
            read_stdin('research') if not a.id or a.body == '-' else None)
    if a.frm and not a.title:
        a.title = md_title(body, os.path.basename(a.frm).rsplit('.md', 1)[0])
    pri, extra = links(db, a.issue)
    db.execute('BEGIN IMMEDIATE')
    try:
        if a.id:
            if not db.execute('SELECT 1 FROM research WHERE id=?', (a.id,)).fetchone():
                die('no research doc r%s' % a.id)
            f = {}
            if a.title: f['title'] = a.title
            if body is not None: f['body'] = body
            if pri is not None: f['issue'] = pri or None
            db.execute("UPDATE research SET %s, updated=datetime('now') WHERE id=?"
                       % ', '.join('%s=?' % k for k in f),
                       list(f.values()) + [a.id])
            rid = a.id
        else:
            if not a.title:
                die('a new research doc needs --title, or --from a file with a "# heading"')
            if body is None:
                die('a new research doc needs a body: --from PATH.md, or redirect one in')
            rid = db.execute('INSERT INTO research(title,body,issue) VALUES(?,?,?)',
                             (a.title, body, pri or None)).lastrowid
        if pri is not None:
            set_links(db, 'doc', rid, extra)
    except BaseException:
        db.execute('ROLLBACK')
        raise
    db.execute('COMMIT')
    r = db.execute('SELECT * FROM research WHERE id=?', (rid,)).fetchone()
    print('r%d  %s%s' % (rid, r['title'], '  -> ' + ' '.join(
        '#%d' % i for i in issues_of(db, 'doc', rid, r['issue']))
        if r['issue'] else ''))


def cmd_put(a):
    db = connect(a.file)
    p, body = vpath(a.path), read_stdin('put')
    pri, extra = links(db, a.issue)
    db.execute('BEGIN IMMEDIATE')
    was = db.execute('SELECT issue FROM proto WHERE path=?', (p,)).fetchone()
    iss = (was['issue'] if was else None) if pri is None else (pri or None)
    db.execute("INSERT INTO proto(path,body,issue) VALUES(?,?,?) ON CONFLICT(path) "
               "DO UPDATE SET body=excluded.body, issue=excluded.issue,"
               " updated=datetime('now')", (p, body, iss))
    if pri is not None:
        set_links(db, 'path', p, extra)
    db.execute('COMMIT')
    named = issues_of(db, 'path', p, iss)
    print('%s  (%d bytes)%s' % (p, len(body),
                                '  -> ' + ' '.join('#%d' % i for i in named) if named else ''))


def cmd_cat(a):
    db = connect(a.file)
    r = db.execute('SELECT body FROM proto WHERE path=?', (vpath(a.path),)).fetchone()
    if not r:
        die('no such prototype file: %s' % a.path)
    sys.stdout.write(r['body'])


def cmd_rm(a):
    db = connect(a.file)
    if db.execute('DELETE FROM proto WHERE path=?', (vpath(a.path),)).rowcount == 0:
        die('no such prototype file: %s' % a.path)
    print('%s removed' % vpath(a.path))


def cmd_ls(a):
    db = connect(a.file)
    rows = db.execute('SELECT path,length(body) n,updated FROM proto '
                      'WHERE path LIKE ? ORDER BY path', (a.prefix + '%',)).fetchall()
    if not rows:
        print('the prototype folder is empty.' if not a.prefix else
              'nothing under %s' % a.prefix)
        return
    for r in rows:
        print('%8d  %s  %s' % (r['n'], r['updated'], r['path']))


def cmd_import(a):
    db = connect(a.file)
    if not os.path.isdir(a.dir):
        die('not a directory: %s' % a.dir)
    pre = vpath(a.prefix) + '/' if a.prefix else ''
    pri, extra = links(db, a.issue)
    n, skipped = 0, []
    db.execute('BEGIN IMMEDIATE')
    for root, dirs, files in os.walk(a.dir):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        for f in sorted(files):
            full = os.path.join(root, f)
            if f.startswith('.') or os.path.getsize(full) > 1 << 20:
                skipped.append(full); continue        # a prototype, not a venv
            try:
                body = open(full, encoding='utf-8').read()
            except (UnicodeDecodeError, OSError):
                skipped.append(full); continue        # binary, or unreadable
            rel = vpath(os.path.relpath(full, a.dir))
            db.execute("INSERT INTO proto(path,body,issue) VALUES(?,?,?) ON CONFLICT(path) "
                       "DO UPDATE SET body=excluded.body, updated=datetime('now'), "
                       "issue=coalesce(excluded.issue,proto.issue)",
                       (pre + rel, body, pri or None))
            if pri:
                set_links(db, 'path', pre + rel, extra)
            n += 1
    db.execute('COMMIT')
    print('imported %d files%s' % (n, ' (skipped %d: binary, hidden or >1MB)'
                                   % len(skipped) if skipped else ''))


def render_item(db, r):
    """One issue as a standalone markdown file: header, body, comments."""
    head = ['# #%d %s' % (r['id'], r['title']), '',
            '- kind: %s' % r['kind'], '- status: %s' % r['status'],
            '- state: %s' % state(db, r)]
    if r['assignee']:
        head.append('- assignee: %s' % r['assignee'])
    if r['parent']:
        head.append('- parent: #%s' % r['parent'])
    if r['gist']:
        head.append('- gist: %s' % r['gist'])
    if picked_note(r):
        head.append('- picked: %s' % picked_note(r))
    if r['verdict']:
        head.append('- verdict: %s' % verdict_label(r))
    for o in options(db, r['id']):
        head.append('- option: %s%s' % (opt_label(o),
                                        '  (recommended)' if r['recommends'] == o['id'] else ''))
    if r['recommendation']:
        head.append('- recommendation: %s' % r['recommendation'])
    b = blockers(db, r['id'])
    if b:
        head.append('- blocked by: %s' % ' '.join('#%d' % x for x in b))
    head += ['- created: %s' % r['created'], '- updated: %s' % r['updated'], '']
    parts = ['\n'.join(head)]
    whole = issue_body(db, r)
    if whole.strip():
        parts.append(whole.rstrip() + '\n')
    lead = picked_note(r) if r['status'] == 'closed' else None
    for c in db.execute('SELECT * FROM comment WHERE issue=? ORDER BY id', (r['id'],)):
        text = lead_in(lead, c['body'].rstrip())
        lead = None
        parts.append('## comment %s\n\n%s\n' % (c['created'], text))
    return '\n'.join(parts)


def render_context(db, heading=True):
    """CONTEXT.md, generated from the term store. A glossary and nothing else:
    no implementation detail, per the format the domain-modeling skill sets."""
    out = (['# %s' % the_root(db)['title'], ''] if heading else []) + ['## Language', '']
    grp = None
    for r in db.execute('SELECT * FROM term ORDER BY grp, name'):
        if r['grp'] != grp:
            grp = r['grp']
            if grp:
                out += ['### %s' % grp, '']
        out.append('**%s**:' % r['name'])
        out.append(r['body'].strip() or '(undefined)')
        if avoid_list(r['avoid']):
            out.append('_Avoid_: %s' % ', '.join(avoid_list(r['avoid'])))
        out.append('')
    return '\n'.join(out).rstrip() + '\n'


def render_adr(db, r, num, heading=True):
    """One ADR: a title and a paragraph, with the optional sections only when
    the tracker actually holds them. Status comes from the verdict and
    Considered Options from the alt edges - neither is written by hand."""
    out = ['# %s' % r['adr_title'], ''] if heading else []
    status = ''
    if r['verdict'] == 'superseded' and r['superseded_by']:
        m = adr_no(db, r['superseded_by'])
        status = ('superseded by ADR-%04d' % m if m else
                  'superseded by #%d' % r['superseded_by'])
    elif r['verdict']:
        status = r['verdict']
    if status:
        out += ['- Status: %s' % status, '']
    # gist first, then every comment: the decision as it now reads, followed by
    # the argument and anything added since.
    out += [r['adr_title'], '']
    for c in db.execute('SELECT body FROM comment WHERE issue=? ORDER BY id', (r['id'],)):
        out += [c['body'].strip(), '']
    opts = options(db, r['id'])
    if opts:
        # Titles and one link. Which one was taken, and why the others were
        # not, is settled on the issue - repeating it here is the duplication
        # the rest of this file exists to avoid.
        out += ['## Considered Options', '',
                'Weighed on [#%d](/i/%d):' % (r['id'], r['id']), '']
        out += ['- %s' % opt_label(x) for x in opts]
        out.append('')
    return '\n'.join(out).rstrip() + '\n'


def write_out(path, body):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(body)


def cmd_export(a):
    db = connect(a.file)
    n = 0
    for r in db.execute('SELECT * FROM issue ORDER BY id'):
        write_out(os.path.join(a.dir, 'issues', '%04d-%s.md' % (r['id'], slug(r['title']))),
                  render_item(db, r))
        n += 1
    for r in db.execute('SELECT * FROM research ORDER BY id'):
        write_out(os.path.join(a.dir, 'research', '%04d-%s.md' % (r['id'], slug(r['title']))),
                  r['body'])
        n += 1
    for r in db.execute('SELECT * FROM proto ORDER BY path'):
        write_out(os.path.join(a.dir, 'proto', *r['path'].split('/')), r['body'])
        n += 1
    # CONTEXT.md and docs/adr/ go out in the layout domain-modeling expects,
    # not under a wfr-shaped subdirectory: they are repo files.
    if db.execute('SELECT count(*) c FROM term').fetchone()['c']:
        write_out(os.path.join(a.dir, 'CONTEXT.md'), render_context(db))
        n += 1
    for r in adrs(db):
        write_out(os.path.join(a.dir, 'docs', 'adr',
                               '%04d-%s.md' % (r['adr'], slug(r['adr_title']))),
                  render_adr(db, r, r['adr']))
        n += 1
    print('%d files written under %s/' % (n, a.dir.rstrip('/')))


# ---------------------------------------------------------------- serve

CSS = """
:root{--bg:#faf9f7;--panel:#fff;--ink:#1c1b19;--dim:#6b6862;--line:#e3e0da;
--frontier:#1a7f4b;--claimed:#8a5a00;--blocked:#9a3b3b;--closed:#9b978f;
--map:#b58900;--grilling:#c2185b;--research:#2e7d32;--prototype:#00838f;
--task:#5d5d5d;--spec:#6a3fb5;--impl:#1565c0;
--row-open:#fbf3d9;--row-frontier:#e6f4ea;--row-claimed:#fdf1db;
--row-blocked:#fbe9e7;--row-closed:#f3f2ef;--rail:#c3bfb6}
@media(prefers-color-scheme:dark){:root{--bg:#16171a;--panel:#1e2024;--ink:#e6e4e0;
--dim:#93908a;--line:#2e3138;--frontier:#4ec98a;--claimed:#e0a63a;--blocked:#e2726e;
--closed:#6f6c67;--map:#e0c14a;--grilling:#f06292;--research:#66bb6a;
--prototype:#4dd0e1;--task:#9e9e9e;--spec:#b388ff;--impl:#64b5f6;
--row-open:#2c2711;--row-frontier:#152e1e;--row-claimed:#31260f;
--row-blocked:#321d1c;--row-closed:#1b1c1f;--rail:#4a4f58}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);padding:0 0 60px;
font:14px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
a{color:inherit}
header{padding:10px 0 6px;border-bottom:1px solid var(--line)}
header .wrap,main{max-width:1100px;margin:0 auto}
header .wrap{padding:0 14px}
h1{font-size:15px;margin:0 0 3px;font-weight:600}
.sub{color:var(--dim);font-size:12px}
main{padding:8px 14px}
.k{display:inline-block;padding:0 6px;border-radius:3px;font-size:10.5px;
letter-spacing:.4px;text-transform:uppercase;font-weight:700;border:1px solid;vertical-align:1px}
.tr .k{width:18px;padding:0;text-align:center;letter-spacing:0}
.map{color:var(--map)}.grilling{color:var(--grilling)}.research{color:var(--research)}
.prototype{color:var(--prototype)}.task{color:var(--task)}.spec{color:var(--spec)}
.impl{color:var(--impl)}
.id{color:var(--dim);font-size:12px}
.gist{color:var(--dim);font-size:12.5px}
.done .t{color:var(--closed);text-decoration:line-through;text-decoration-color:var(--line)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%}
.s-frontier{background:var(--frontier)}.s-claimed{background:var(--claimed)}
.s-blocked{background:var(--blocked)}.s-closed{background:var(--closed)}
.s-open{background:var(--map)}
.wait{color:var(--blocked);font-size:11.5px}
.v{font-size:11px;text-transform:uppercase;letter-spacing:.06em;padding:1px 5px;
   border-radius:3px;border:1px solid currentColor}
.v-accepted{color:var(--frontier)}.v-rejected{color:var(--blocked)}
.v-superseded{color:var(--dim)}.v a{color:inherit}
.dec{margin:10px 0}.dec dt{font-weight:600;margin-top:12px}
.dec dd{margin:2px 0 0 18px;color:var(--dim)}
.dec dd .gist{font-size:11.5px}
.who{color:var(--claimed);font-size:11.5px}
.tr{padding:3px 6px;border-bottom:1px solid var(--line);display:flex;align-items:stretch}
.tr>.tx{flex:1;min-width:0}
.tr>i{flex:none;width:15px;position:relative;--y:14px}
.tr>i.b::before,.tr>i.e::before{content:"";position:absolute;left:7px;top:-4px;bottom:-4px;
border-left:1px solid var(--rail)}
.tr>i.e.l::before{bottom:auto;height:calc(var(--y) + 4px)}
.tr>i.e::after{content:"";position:absolute;left:7px;width:8px;
top:var(--y);border-top:1px solid var(--rail)}
.tr.st-open{background:var(--row-open)}
.tr.st-frontier{background:var(--row-frontier)}
.tr.st-claimed{background:var(--row-claimed)}
.tr.st-blocked{background:var(--row-blocked)}
.tr.st-closed{background:var(--row-closed)}
.tr a{text-decoration:none}.tr a:hover .t{text-decoration:underline}
.body{background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:2px 10px;margin:8px 0;overflow-x:auto}
.body pre{background:var(--bg);padding:6px;border-radius:5px;overflow-x:auto}
.body h1,.body h2,.body h3{font-size:14px}
.body ul,.body ol{padding-left:22px;margin:8px 0}
.body li{margin:2px 0}
.body table{border-collapse:collapse;margin:10px 0;font-size:12.5px}
.body th,.body td{border:1px solid var(--line);padding:4px 9px;vertical-align:top}
.body th{background:var(--bg);font-weight:600;text-align:left}
.body blockquote{margin:8px 0;padding-left:12px;border-left:3px solid var(--line);color:var(--dim)}
.cmt{border-top:1px solid var(--line);margin-top:16px}
.cmt h3{font-size:11px;letter-spacing:1px;text-transform:uppercase;color:var(--dim)}
nav{display:flex;gap:2px;margin:6px 0 0}
nav a{padding:3px 8px;text-decoration:none;color:var(--dim);font-size:12px;
border-bottom:2px solid transparent}
nav a:hover{color:var(--ink)}
nav a.on{color:var(--ink);font-weight:600;border-bottom-color:var(--ink)}
.crumbs{font-size:12px;color:var(--dim);padding:4px 0 2px}
.crumbs a{text-decoration:none}
.crumbs a:hover{text-decoration:underline}
.split{display:flex;align-items:stretch;background:var(--panel);margin:8px 0;
border:1px solid var(--line);border-radius:8px;overflow:hidden;height:72vh}
.tree{width:260px;flex:none;border-right:1px solid var(--line);overflow:auto;padding:4px 0}
.tree a{display:block;padding:2px 8px;text-decoration:none;font-size:12.5px;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tree a:hover{background:var(--bg)}
.tree a.sel{background:var(--row-frontier);font-weight:600}
.tree .d{color:var(--prototype)}
.code{flex:1;overflow:auto;min-width:0}
.code pre{margin:0;padding:8px 10px;font-size:12.5px}
.fhead{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);
padding:4px 10px;font-size:12px;color:var(--dim)}
.fhead{display:flex;align-items:center;gap:10px}
.fhead .raw{margin-left:auto}
@media(max-width:700px){.split{flex-direction:column;height:auto}
.tree{width:auto;border-right:none;border-bottom:1px solid var(--line);max-height:32vh}
.code{max-height:60vh}}
"""


NAV = (('/', 'Issues'), ('/g/', 'Glossary'), ('/a/', 'Decisions'),
       ('/r/', 'Research'), ('/p/', 'Prototypes'))


def page(title, sub, inner, tab='/', crumbs=(), h1=None):
    nav = ''.join('<a href="%s"%s>%s</a>' % (href, ' class="on"' if href == tab else '', name)
                  for href, name in NAV)
    crumb = ' &rsaquo; '.join('<a href="%s">%s</a>' % (h, t) if h else '<span>%s</span>' % t
                              for h, t in crumbs)
    return ('<!doctype html><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title><style>%s</style>'
            '<header><div class="wrap"><h1><a href="/">%s</a></h1>'
            '<nav>%s</nav><div class="crumbs">%s</div>'
            '<div class="sub">%s</div></div></header>'
            '<main>%s</main>' % (html.escape(title), CSS,
                                 html.escape(h1 or title), nav, crumb, sub, inner))


def tree_prefix(bars, last):
    """The rail, drawn with borders rather than box glyphs: a glyph is only as
    tall as its own line, so it cannot reach the row below when a title wraps.
    One cell per ancestor - bar if that ancestor has more children coming - then
    this node's elbow, which stops half way down when it is the last child."""
    return ''.join('<i class="%s"></i>' % ('b' if b else '') for b in bars) \
        + '<i class="e%s"></i>' % (' l' if last else '')


def view_tree(db):
    counts = {}
    rows = walk(db)
    for _, _bars, _last, r in rows:
        counts[state(db, r)] = counts.get(state(db, r), 0) + 1
    sub = '%d issues · ' % len(rows) + ' · '.join(
        '<span class="dot s-%s"></span> %d %s' % (s, counts[s], 'root' if s == 'open' else s)
        for s in ('open', 'frontier', 'claimed', 'blocked', 'closed') if s in counts)
    out = []
    # A lone root never needs a rail of its own, so its column is dead indent:
    # drop it. With several roots that column does carry bars, so keep it.
    trim = 1 if sum(1 for d, _b, _l, _r in rows if not d) == 1 else 0
    for depth, bars, last, r in rows:
        st, w = state(db, r), waiting(db, r['id'])
        prefix = tree_prefix(bars[trim:], last) if depth else ''
        out.append(
            '<div class="tr st-%s%s">%s<div class="tx">'
            '<span class="dot s-%s"></span> <a href="/i/%d"><span class="id">#%d</span> '
            '<span class="k %s" title="%s">%s</span> <span class="t">%s</span></a>%s%s</div></div>'
            % (st, ' done' if st == 'closed' else '', prefix, st, r['id'], r['id'],
               r['kind'], r['kind'], r['kind'][0].upper(), html.escape(r['title']),
               ' <span class="v v-%s">%s</span>' % (r['verdict'], verdict_label(r))
               if r['verdict'] else '',
               ' <span class="wait">&#9676; %s</span>'
               % ' '.join('#%d' % x for x in w) if w else ''))
    return page(the_root(db)['title'], sub, ''.join(out), '/', [(None, 'Issues')])


def map_dl(db, chunk):
    """One owned section as a definition list: the question is the term, its
    answer the definition. Built from the issues themselves - the text is read
    only for which issue and in what order."""
    items = []
    for m in re.finditer(r'^- \[[^\]]*\]\(/i/(\d+)\):', chunk, re.M):
        r = db.execute('SELECT * FROM issue WHERE id=?', (int(m.group(1)),)).fetchone()
        if not r:
            continue
        note = line_note(db, r)
        items.append('<dt><a href="/i/%d">%s</a></dt><dd>%s%s</dd>'
                     % (r['id'], html.escape(r['title']),
                        _inline(html.escape(r['gist'])),
                        '<br><span class="gist">(%s)</span>' % html.escape(note)
                        if note else ''))
    return '<dl class="dec">%s</dl>' % ''.join(items) if items else ''


def view_map_body(db, body):
    """The map body, with its two owned sections rendered as definition lists
    and everything else - destination, notes, fog - as ordinary markdown."""
    spans = sorted(((h, sp) for h, sp in ((h, _span(body, h))
                                          for h in (DECISIONS, OUT_OF_SCOPE)) if sp),
                   key=lambda x: x[1][0])
    out, pos = [], 0
    for _, (lo, hi) in spans:
        out.append(markdown(body[pos:lo]))
        out.append(map_dl(db, body[lo:hi]))
        pos = hi
    out.append(markdown(body[pos:]))
    return ''.join(out)


def map_dl(db, chunk):
    """One owned section as a definition list: the question is the term, its
    answer the definition. Built from the issues themselves - the text is read
    only for which issue and in what order."""
    items = []
    for m in re.finditer(r'^- \[[^\]]*\]\(/i/(\d+)\):', chunk, re.M):
        r = db.execute('SELECT * FROM issue WHERE id=?', (int(m.group(1)),)).fetchone()
        if not r:
            continue
        note = line_note(db, r)
        items.append('<dt><a href="/i/%d">%s</a></dt><dd>%s%s</dd>'
                     % (r['id'], html.escape(r['title']),
                        _inline(html.escape(r['gist'])),
                        '<br><span class="gist">(%s)</span>' % html.escape(note)
                        if note else ''))
    return '<dl class="dec">%s</dl>' % ''.join(items) if items else ''


def view_map_body(db, body):
    """The map body, with its two owned sections rendered as definition lists
    and everything else - destination, notes, fog - as ordinary markdown."""
    spans = sorted(((h, sp) for h, sp in ((h, _span(body, h))
                                          for h in (DECISIONS, OUT_OF_SCOPE)) if sp),
                   key=lambda x: x[1][0])
    out, pos = [], 0
    for _, (lo, hi) in spans:
        out.append(markdown(body[pos:lo]))
        out.append(map_dl(db, body[lo:hi]))
        pos = hi
    out.append(markdown(body[pos:]))
    return ''.join(out)


def view_issue(db, iid):
    r = db.execute('SELECT * FROM issue WHERE id=?', (iid,)).fetchone()
    if not r:
        return None
    w, b = waiting(db, iid), blockers(db, iid)
    st = state(db, r)
    bits = ['<span class="dot s-%s"></span> %s' % (st, st)]
    if r['assignee']:
        bits.append('<span class="who">@%s</span>' % html.escape(r['assignee']))
    if r['verdict']:
        lab = ('superseded by <a href="/i/%d">#%d</a>' % (r['superseded_by'], r['superseded_by'])
               if r['verdict'] == 'superseded' and r['superseded_by'] else r['verdict'])
        bits.append('<span class="v v-%s">%s</span>' % (r['verdict'], lab))
    if r['adr']:
        bits.append('<a href="/a/%d">ADR-%04d</a>' % (adr_no(db, iid), adr_no(db, iid)))
    if r['parent']:
        bits.append('child of <a href="/i/%d">#%d</a>' % (r['parent'], r['parent']))

    if b:
        bits.append('blocked by ' + ' '.join('<a href="/i/%d">#%d</a>' % (x, x) for x in b)
                    + ('<span class="wait"> (waiting on %s)</span>'
                       % ' '.join('#%d' % x for x in w) if w else ' (all closed)'))
    whole = issue_body(db, r)
    render = view_map_body if r['kind'] == 'map' and r['parent'] is None else \
        (lambda _db, t: markdown(t))
    inner = ['<div class="body">%s</div>' % render(db, whole)] if whole.strip() else []
    lead = picked_note(r) if r['status'] == 'closed' else None
    for c in db.execute('SELECT * FROM comment WHERE issue=? ORDER BY id', (iid,)):
        # only the first comment is the resolution; later ones are their own
        # contributions and take no prefix.
        text = lead_in(lead, c['body'])
        lead = None
        inner.append('<div class="cmt"><h3>%s</h3>'
                     '<div class="body">%s</div></div>'
                     % (html.escape(c['created']), markdown(text)))
    kids = db.execute('SELECT id,title FROM issue WHERE parent=? ORDER BY id', (iid,)).fetchall()
    if kids:
        inner.append('<div class="cmt"><h3>children</h3>%s</div>' % ''.join(
            '<div class="tr"><a href="/i/%d"><span class="id">#%d</span> '
            '<span class="t">%s</span></a></div>' % (k['id'], k['id'], html.escape(k['title']))
            for k in kids))
    also = ' <span class="gist">also</span>'
    docs, fs = refs(db, iid)
    if docs:
        inner.append('<div class="cmt"><h3>research</h3>%s</div>' % ''.join(
            '<div class="tr"><a href="/r/%d"><span class="id">r%d</span> '
            '<span class="t">%s</span></a>%s</div>'
            % (i, i, html.escape(t), '' if primary else also) for i, (t, primary) in docs))
    if fs:
        inner.append('<div class="cmt"><h3>prototype</h3>%s</div>' % ''.join(
            '<div class="tr"><a href="/p/%s"><span class="t">%s</span></a>%s</div>'
            % (quote(path), html.escape(path), '' if primary else also)
            for path, primary in fs))
    return page('#%d %s' % (r['id'], r['title']),
                '<span class="k %s">%s</span> &nbsp;%s' % (r['kind'], r['kind'], ' · '.join(bits)),
                ''.join(inner) or '<p class="gist">(no body)</p>', '/',
                [('/', 'Issues'), (None, '#%d %s' % (r['id'], html.escape(r['title'])))],
                the_root(db)['title'])


def view_terms(db):
    """The served glossary is the exported CONTEXT.md, rendered - one source,
    so the page and the file can never drift apart."""
    c = db.execute('SELECT count(*) c FROM term').fetchone()['c']
    inner = ('<div class="body">%s</div>' % markdown(render_context(db, heading=False))
             if c else '<p class="gist">The glossary is empty.</p>')
    return page('Glossary', '%d term%s' % (c, '' if c == 1 else 's'), inner,
                '/g/', [(None, 'Glossary')], the_root(db)['title'])


def view_adrs(db):
    rows = adrs(db)
    if not rows:
        return page('Decisions', 'no ADRs yet',
                    '<p class="gist">No decision has been marked worth publishing.</p>',
                    '/a/', [(None, 'Decisions')], the_root(db)['title'])
    out = ''.join(
        '<div class="tr%s"><a href="/a/%d"><span class="id">ADR-%04d</span> '
        '<span class="t">%s</span></a>%s</div>'
        % (' done' if r['verdict'] == 'superseded' else '', r['adr'], r['adr'],
           html.escape(r['adr_title']),
           ' <span class="v v-%s">%s</span>' % (r['verdict'], verdict_label(r))
           if r['verdict'] else '')
        for r in rows)
    return page('Decisions', '%d ADR%s' % (len(rows), '' if len(rows) == 1 else 's'),
                out, '/a/', [(None, 'Decisions')], the_root(db)['title'])


def view_adr(db, num):
    r = db.execute('SELECT * FROM issue WHERE adr=?', (num,)).fetchone()
    if not r:
        return None
    # the page already carries a heading; a second one from the markdown would
    # be a duplicate h1, so the title rides in the crumb instead.
    return page('ADR-%04d %s' % (num, r['adr_title']),
                '<a href="/i/%d">#%d</a>' % (r['id'], r['id']),
                '<div class="body">%s</div>' % markdown(render_adr(db, r, num, False)),
                '/a/', [('/a/', 'Decisions'),
                        (None, 'ADR-%04d %s' % (num, html.escape(r['adr_title'])))],
                the_root(db)['title'])


def issue_links(db, ids):
    return ' '.join('<a href="/i/%d">#%d</a>' % (i, i) for i in ids)


def doc_sub(db, r):
    named = issues_of(db, 'doc', r['id'], r['issue'])
    bits = []
    if named:
        bits.append('answers <a href="/i/%d">#%d %s</a>'
                    % (named[0], named[0], html.escape(issue(db, named[0])['title'])))
        if named[1:]:
            bits.append('also ' + issue_links(db, named[1:]))
    bits.append('updated %s' % html.escape(r['updated']))
    return '<span class="k research">research</span> &nbsp;' + ' · '.join(bits)


def view_research(db):
    rows = db.execute('SELECT * FROM research ORDER BY id').fetchall()
    out = []
    for r in rows:
        out.append('<div class="tr"><a href="/r/%d"><span class="id">r%d</span> '
                   '<span class="t">%s</span></a>%s</div>'
                   % (r['id'], r['id'], html.escape(r['title']),
                      ' <span class="gist">%s</span>'
                      % issue_links(db, issues_of(db, 'doc', r['id'], r['issue']))
                      if r['issue'] else ''))
    return page(the_root(db)['title'],
                '%d research docs · whole markdown artifacts, kept in the file' % len(rows),
                ''.join(out) or '<p class="gist">No research docs yet: '
                'wfr.py research FILE --from notes.md</p>',
                '/r/', [(None, 'Research')], the_root(db)['title'])


def view_doc(db, rid):
    r = db.execute('SELECT * FROM research WHERE id=?', (rid,)).fetchone()
    if not r:
        return None
    return page(r['title'], doc_sub(db, r),
                '<div class="body">%s</div>' % markdown(r['body']), '/r/',
                [('/r/', 'Research'), (None, 'r%d %s' % (r['id'], html.escape(r['title'])))],
                the_root(db)['title'])


def view_proto(db, path):
    """Left: the folder at this level, with .. Right: the raw file."""
    path = path.strip('/')
    row = db.execute('SELECT * FROM proto WHERE path=?', (path,)).fetchone() if path else None
    here = path.rsplit('/', 1)[0] if row and '/' in path else ('' if row else path)
    dirs, files = proto_dir(db, here)
    if path and not row and not (dirs or files):
        return None
    ents = []
    if here:
        up = here.rsplit('/', 1)[0] if '/' in here else ''
        ents.append(('<a class="d" href="/p/%s">..</a>' % quote(up)))
    for d in dirs:
        ents.append('<a class="d" href="/p/%s">%s/</a>'
                    % (quote((here + '/' if here else '') + d), html.escape(d)))
    for f in files:
        fp = (here + '/' if here else '') + f
        ents.append('<a class="%s" href="/p/%s">%s</a>'
                    % ('sel' if fp == path else '', quote(fp), html.escape(f)))
    if row:
        code = ('<div class="fhead"><span>%s</span>%s'
                '<a class="raw" href="/p/%s?raw">raw</a></div>'
                '<pre><code>%s</code></pre>'
                % (html.escape(path),
                   '<span class="ilinks">%s</span>'
                   % issue_links(db, issues_of(db, 'path', path, row['issue']))
                   if row['issue'] else '',
                   quote(path), html.escape(row['body'])))
    else:
        n = db.execute('SELECT count(*) c FROM proto').fetchone()['c']
        code = ('<div class="fhead">%s</div><p class="gist" style="padding:14px">%s</p>'
                % (html.escape(here or '/'),
                   'Pick a file from the tree.' if n else
                   'The prototype folder is empty. Fill it with: wfr.py put FILE PATH'))
    crumbs = [('/p/', 'Prototypes')]
    walked = ''
    for seg in path.split('/') if path else []:
        walked = walked + '/' + seg if walked else seg
        crumbs.append((None if walked == path else '/p/' + quote(walked), html.escape(seg)))
    return page(path or 'Prototypes',
                '%d files in the folder' % db.execute(
                    'SELECT count(*) c FROM proto').fetchone()['c'],
                '<div class="split"><div class="tree">%s</div><div class="code">%s</div></div>'
                % (''.join(ents) or '<p class="gist" style="padding:6px 12px">empty</p>', code),
                '/p/', crumbs, the_root(db)['title'])


def cmd_serve(a):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    path = os.path.abspath(a.file)
    connect(path).close()

    class H(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'

        def reply(self, code, body, ctype='text/html'):
            b = body.encode()
            self.send_response(code)
            self.send_header('Content-Type', '%s; charset=utf-8' % ctype)
            self.send_header('Content-Length', str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            db = connect(path)
            try:
                route, _, qs = self.path.partition('?')
                route = unquote(route)
                if route == '/':
                    return self.reply(200, view_tree(db))
                if route in ('/r', '/r/'):
                    return self.reply(200, view_research(db))
                if route in ('/g', '/g/'):
                    return self.reply(200, view_terms(db))
                if route in ('/a', '/a/'):
                    return self.reply(200, view_adrs(db))
                m = re.fullmatch(r'/a/(\d+)', route)
                if m:
                    v = view_adr(db, int(m.group(1)))
                    return self.reply(200, v) if v else self.reply(
                        404, page('not found', '', '<p>No ADR-%s.</p>' % m.group(1)))
                m = re.fullmatch(r'/i/(\d+)', route)
                if m:
                    v = view_issue(db, int(m.group(1)))
                    return self.reply(200, v) if v else self.reply(
                        404, page('not found', '', '<p>No issue #%s.</p>' % m.group(1)))
                m = re.fullmatch(r'/r/(\d+)', route)
                if m:
                    v = view_doc(db, int(m.group(1)))
                    return self.reply(200, v) if v else self.reply(
                        404, page('not found', '', '<p>No research doc r%s.</p>' % m.group(1)))
                if route == '/p' or route.startswith('/p/'):
                    p = route[3:] if route.startswith('/p/') else ''
                    if qs == 'raw':
                        f = db.execute('SELECT body FROM proto WHERE path=?',
                                       (p.strip('/'),)).fetchone()
                        return self.reply(200, f['body'], 'text/plain') if f else self.reply(
                            404, 'no such file\n', 'text/plain')
                    v = view_proto(db, p)
                    return self.reply(200, v) if v else self.reply(
                        404, page('not found', '', '<p>Nothing at /p/%s.</p>' % html.escape(p)))
                self.reply(404, page('not found', '', '<p>No such page.</p>'))
            finally:
                db.close()

        def do_POST(self):
            self.send_response(405)
            self.send_header('Allow', 'GET')
            self.end_headers()

        do_PUT = do_DELETE = do_PATCH = do_POST

        def log_message(self, *_):
            pass

    srv = HTTPServer(('127.0.0.1', a.port), H)
    print('%s at http://127.0.0.1:%d  (ctrl-c to stop)' % (a.file, a.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print()


# ---------------------------------------------------------------- selftest

def cmd_selftest(_):
    import io
    fails = []

    def ck(cond, what):
        print(('  ok   ' if cond else '  FAIL ') + what)
        if not cond:
            fails.append(what)

    def run(argv, stdin=None):
        old = sys.stdin
        if stdin is not None:
            sys.stdin = io.StringIO(stdin); sys.stdin.isatty = lambda: False
        try:
            main(argv)
        finally:
            sys.stdin = old

    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'test.wf')
        run(['init', f, '--title', 'Test effort'])
        db = connect(f)
        ck(the_map(db)['id'] == 1, 'init seeds the map as #1')
        ck(DECISIONS in the_map(db)['body'], 'map body carries the owned headings')
        # this file is its own only documentation, and every session pays for
        # it in context. A budget, so it cannot quietly bloat again.
        ck(len(HELP) < 14000, 'help stays inside an agent\'s context budget (%d)' % len(HELP))

        run(['add', f, '--kind', 'grilling', '--title', 'First question', '--parent', '1'])
        run(['add', f, '--kind', 'impl', '--title', 'Second, blocked', '--parent', '1'])
        run(['block', f, '3', '--on', '2'])
        ck([r['id'] for r in db.execute("SELECT id FROM issue WHERE status='open'")] == [1, 2, 3],
           'three open issues')

        front = lambda: [r['id'] for r in db.execute(
            "SELECT * FROM issue WHERE status='open' AND assignee='' AND kind<>'map' ORDER BY id")
            if not waiting(db, r['id'])]
        ck(front() == [2], 'frontier is the unblocked issue only, never the map')

        run(['claim', f, '2', 'tester'])
        ck(front() == [], 'a claimed issue leaves the frontier')
        run(['claim', f, '2', ''])
        ck(front() == [2], 'releasing a claim returns it to the frontier')
        run(['claim', f, '2', 'tester'])

        run(['resolve', f, '2'], stdin='Chose the lazy option\n\nBecause it works.\n')
        ck(issue(db, 2)['status'] == 'closed', 'resolve closes the issue')
        ck(front() == [3], 'closing a blocker advances the frontier')
        body = the_map(db)['body']
        ck('- [First question](/i/2): Chose the lazy option' in body, 'gist lands on the map')
        ck(body.index('Chose the lazy') < body.index('## Not yet specified'),
           'the gist lands under Decisions, not in a later section')
        ck(db.execute('SELECT count(*) c FROM comment WHERE issue=2').fetchone()['c'] == 1,
           'the answer body becomes a comment')

        run(['resolve', f, '3', '--oos'], stdin='Past the destination\n')
        body = the_map(db)['body']
        ck('- [Second, blocked](/i/3): Past the destination' in body[body.index('## Out of scope'):],
           '--oos writes under Out of scope, not Decisions')
        ck(db.execute('SELECT count(*) c FROM comment WHERE issue=3').fetchone()['c'] == 0,
           'a subject-only answer leaves no comment')

        # regression: the map must be read under the write lock, or two
        # concurrent resolves each append to a stale body and one is lost.
        inside, real = [], the_map
        globals()['the_map'] = lambda d: (inside.append(bool(d.in_transaction)), real(d))[1]
        run(['add', f, '--kind', 'grilling', '--title', 'Third', '--parent', '1'])
        run(['resolve', f, '4'], stdin='Third answer\n')
        globals()['the_map'] = real
        ck(inside and all(inside), 'resolve reads the map inside its transaction')

        run(['add', f, '--kind', 'grilling', '--title', 'Contested', '--parent', '1'])
        run(['claim', f, '5', 'first'])
        try:
            run(['claim', f, '5', 'second'])
            ck(False, 'a second claim on a held issue is refused')
        except SystemExit:
            ck(issue(db, 5)['assignee'] == 'first',
               'a second claim on a held issue is refused')

        try:
            db.execute("INSERT INTO issue(kind,title) VALUES('grillng','typo')")
            ck(False, 'a mistyped kind is rejected at write time')
        except sqlite3.IntegrityError:
            ck(True, 'a mistyped kind is rejected at write time')

        try:
            append_section('## Nothing here\n', DECISIONS, '- x')
            ck(False, 'a map missing its heading fails loudly')
        except SystemExit:
            ck(True, 'a map missing its heading fails loudly')

        # --- mapless: a tracker whose root is a spec, not a map -----------
        g = os.path.join(d, 'mapless.wf')
        run(['init', g, '--kind', 'spec', '--title', 'A spec effort'])
        db2 = connect(g)
        ck(the_root(db2)['id'] == 1 and the_root(db2)['kind'] == 'spec',
           'init --kind spec seeds a spec root as #1')
        ck(the_root(db2)['body'] == '', 'a non-map root starts with an empty body')
        ck(the_map(db2) is None, 'the_map comes back empty instead of exiting')

        run(['add', g, '--kind', 'impl', '--title', 'Ticket one', '--parent', '1'])
        run(['add', g, '--kind', 'impl', '--title', 'Ticket two', '--parent', '1'])
        run(['block', g, '3', '--on', '2'])
        front2 = lambda: [r['id'] for r in db2.execute(
            "SELECT * FROM issue WHERE status='open' AND assignee=''"
            ' AND parent IS NOT NULL ORDER BY id') if not waiting(db2, r['id'])]
        ck(front2() == [2], 'a mapless frontier is the unblocked child, never the root')
        ck(state(db2, the_root(db2)) == 'open', 'a spec root is open, not on the frontier')
        try:
            run(['resolve', g, '1'], stdin='nope\n')
            ck(False, 'the root of a mapless tracker cannot be resolved')
        except SystemExit:
            ck(True, 'the root of a mapless tracker cannot be resolved')

        run(['resolve', g, '2'], stdin='Did the thing\n\nDetail.\n')
        ck(issue(db2, 2)['status'] == 'closed', 'resolve closes a child with no map')
        ck(db2.execute('SELECT count(*) c FROM comment WHERE issue=2').fetchone()['c'] == 1,
           'the comment still lands when there is no map')
        ck(front2() == [3], 'closing a blocker advances the mapless frontier')
        run(['resolve', g, '3', '--oos'], stdin='Past the destination\n')
        ck(issue(db2, 3)['status'] == 'closed', '--oos closes on a mapless tracker')

        tv2 = view_tree(db2)
        ck('<div class="tr' in tv2, 'the tree view renders a mapless tracker')
        ck('<title>A spec effort</title>' in tv2, 'the page is titled with the root issue')
        ck('1 root' in tv2, 'the summary line labels the root state "root", not "map"')

        db2.execute("INSERT INTO issue(kind,title,parent) VALUES('map','One',1)")
        db2.execute("INSERT INTO issue(kind,title,parent) VALUES('map','Two',1)")
        try:
            the_map(db2)
            ck(False, 'a tracker with two maps still fails loudly')
        except SystemExit:
            ck(True, 'a tracker with two maps still fails loudly')
        db2.close()

        h = markdown('# Head\n\n- a `x` item\n- two\n\n**bold** and [l](/i/1) and <script>\n\n'
                     '```\nraw <b> & stuff\n```\n\n> quoted\n')
        for want in ('<h1>Head</h1>', '<li>a <code>x</code> item</li>', '<strong>bold</strong>',
                     '<a href="/i/1">l</a>', '&lt;script&gt;',
                     '<code>raw &lt;b&gt; &amp; stuff</code>', '<blockquote>quoted</blockquote>'):
            ck(want in h, 'markdown: %s' % want)
        ck('<script>' not in h, 'markdown never emits a raw script tag')
        for bad in ('javascript:alert(1)', 'JavaScript:alert(1)', '//evil.example/x'):
            ck('<a' not in markdown('[x](%s)' % bad),
               'markdown emits no link for %s' % bad)
        ck('<a href="/i/1">' in markdown('[x](/i/1)')
           and '<a href="https://a.example/b">' in markdown('[x](https://a.example/b)'),
           'markdown still links the URLs it should')

        c = markdown('text\n\n    line one\n      indented more\n\nafter\n')
        ck('<pre><code>line one\n  indented more</code></pre>' in c,
           'indented code block keeps its relative indentation')
        ck('<p>after</p>' in c and '<p>text</p>' in c,
           'indented code block does not swallow the prose around it')
        ck('&lt;b&gt;' in markdown('\n    <b> & co\n') and
           '<b>' not in markdown('\n    <b> & co\n'),
           'indented code block is escaped')
        ck('<pre>' not in markdown('- item\n    continued\n'),
           'an indented line inside a list is not a code block')
        ck('<pre>' not in markdown('para\n    indented\n'),
           'no blank line before means no code block')
        w = markdown('- first item\n  wrapped on\n- second item\n')
        ck(w.count('<li>') == 2 and '<p>' not in w,
           'a wrapped list item stays one item, not item + paragraph + item')
        ck('<li>first item wrapped on</li>' in w,
           'the wrapped line joins its own item')
        ck('<li>second item</li>' in w, 'the continuation does not leak into the next item')
        ck(markdown('1. one\n   wrapped\n2. two\n').count('<li>') == 2,
           'numbered items wrap the same way')
        b = markdown('- item\n\nseparate para\n')
        ck(b.count('<li>') == 1 and '<p>separate para</p>' in b,
           'a blank line still ends the list and starts a paragraph')
        o = markdown('1. one\n2. two\n3. three\n')
        ck(o.count('<ol>') == 1 and o.count('<li>') == 3, 'ol: three numbered items')
        ck('<ol start="3">' in markdown('3. three\n4. four\n'),
           'ol: a list starting at 3 keeps its numbering')
        ck('<li value="3">' in markdown('1. one\n3. three\n4. four\n'),
           'ol: a gap in the numbering is kept, not silently closed up')
        ck('value=' not in markdown('1. one\n2. two\n'),
           'ol: an unbroken list needs no per-item numbering')
        ck(markdown('1) a\n2) b\n').count('<li>') == 2, 'ol: the 1) form works too')
        two = markdown('- bullet\n\n1. number\n')
        ck('<ul>' in two and '<ol>' in two and two.index('<ul>') < two.index('<ol>'),
           'ol: a ul and an ol stay separate lists')
        ck('<em>Avoid</em>: purchase' in markdown('_Avoid_: purchase\n'),
           'em: the _Avoid_ form CONTEXT.md is written in renders')
        ck('<em>' not in markdown('snake_case_name\n'),
           'em: underscores inside a word are part of the word')
        ck('<em>' not in markdown('`a_b_c`\n'), 'em: and are left alone in code')
        ck('<em>x</em>' in markdown('*x*\n')
           and '<strong>x</strong>' in markdown('**x**\n'),
           'em: the asterisk form works and does not eat strong')
        ck(markdown('- a\n1. b\n').count('<ul>') == 1
           and markdown('- a\n1. b\n').count('<ol>') == 1,
           'ol: switching marker mid-run splits the list')
        ck('<li>nested</li>' in markdown('- a\n    - nested\n'),
           'ol: an indented item joins the list rather than falling out as text')
        t = markdown('col a | col b | c\n--- | ---: | :---:\n1 | `x` | <b>\n2 | y | z\n')
        ck(t.count('<tr>') == 3 and t.count('</th>') == 3 and t.count('</td>') == 6,
           'table: 1 header row + 2 body rows, 3 columns')
        ck('style="text-align:right"' in t and 'style="text-align:center"' in t,
           'table: ---: and :---: set alignment')
        ck('<code>x</code>' in t and '&lt;b&gt;' in t,
           'table cells are escaped and inline-formatted')
        ck('<td></td>' in markdown('a | b\n--- | ---\n| only |\n'),
           'table: a short row is padded, not dropped')
        ck('<table>' not in markdown('a | b\n--- | ---\n')
           or '<tbody></tbody>' in markdown('a | b\n--- | ---\n'),
           'table: a header with no body rows still renders')
        ck('<table>' not in markdown('a | b\nnot a separator\n'),
           'table: no separator row means no table')
        tv = view_tree(db)
        ck('<div class="tr' in tv, 'the tree view renders')
        tagged = re.findall(r'<div class="tr st-(\w+)', tv)
        ck(len(tagged) == db.execute('SELECT count(*) c FROM issue').fetchone()['c'],
           'every tree row carries a state class')
        ck(tv.count('<i class="e') == sum(1 for d, _b, _l, _r in walk(db) if d),
           'every row but the root draws exactly one elbow')
        ck(tree_prefix((), True) == '<i class="e l"></i>'
           and tree_prefix((True, False), False)
           == '<i class="b"></i><i class=""></i><i class="e"></i>',
           'the rail carries a bar only past an ancestor that still has children coming')
        ck('.tr>i.e.l::before' in CSS and 'height:calc(' in CSS,
           'the last child stops its rail at the elbow instead of running it on')
        ck('<span class="k grilling" title="grilling">G</span>' in tv
           and '<span class="k grilling">grilling</span>' in view_issue(db, 2),
           'the tree badges a kind by its initial; the issue page spells it out')
        ck(len({k[0] for k in KINDS}) == len(KINDS),
           'initials stay unambiguous: no two kinds share a first letter')
        ck(all('--row-%s:' % st in CSS and '.tr.st-%s{' % st in CSS for st in set(tagged)),
           'every state present has a row colour: %s' % sorted(set(tagged)))
        ck('header .wrap,main{max-width:1100px;margin:0 auto}' in CSS,
           'header and main are centred, not left-aligned, on a wide screen')
        ck(view_tree(db).count('<div class="wrap">') == 1,
           'the header content sits in the centring wrapper')
        ck(all(CSS.count('--row-%s:' % st) == 2 for st in
               ('open', 'frontier', 'claimed', 'blocked', 'closed')),
           'every row colour is defined for both light and dark')
        ck(view_issue(db, 2) is not None and view_issue(db, 99) is None,
           'the issue view renders, and 404s on a missing issue')
        for p in (view_tree(db), view_issue(db, 2), view_research(db), view_proto(db, '')):
            ck(p.count('<nav>') == 1 and all('>%s<' % n in p for _, n in NAV),
               'every page carries the three-item nav')
        ck('<a href="/p/" class="on">' in view_proto(db, ''),
           'the nav marks the tab you are on')
        ck('&rsaquo;' in view_issue(db, 2) and '<span>Issues</span>' in view_tree(db),
           'breadcrumbs sit under the nav')

        # --- research: a store of markdown artifacts, not issues ----------
        run(['add', f, '--kind', 'research', '--title', 'What does X do', '--parent', '1'])
        art = os.path.join(d, 'artifact.md')
        open(art, 'w').write('# How X actually works\n\nIt caches.\n')
        run(['research', f, '--from', art, '--issue', '6'])
        doc = db.execute('SELECT * FROM research WHERE id=1').fetchone()
        ck(doc['title'] == 'How X actually works',
           'research --from takes the title from the "# heading"')
        ck(doc['body'].endswith('It caches.\n') and doc['issue'] == 6,
           'the whole artifact is stored verbatim, linked to its issue')
        run(['research', f, '--title', 'Loose note'], stdin='no issue here\n')
        ck(db.execute('SELECT count(*) c FROM research').fetchone()['c'] == 2,
           'a doc need not be linked to an issue')
        run(['research', f, '2', '--issue', '6'])
        ck(db.execute('SELECT issue FROM research WHERE id=2').fetchone()[0] == 6,
           'an id with a flag updates in place')
        ck(db.execute('SELECT body FROM research WHERE id=2').fetchone()[0] == 'no issue here\n',
           'updating the link leaves the body alone')
        run(['research', f, '2', '--issue', '0'])
        ck(db.execute('SELECT issue FROM research WHERE id=2').fetchone()[0] is None,
           '--issue 0 unlinks')
        try:
            run(['research', f, '--title', 'Bad link', '--from', art, '--issue', '99'])
            ck(False, 'a doc cannot name an issue that does not exist')
        except SystemExit:
            ck(True, 'a doc cannot name an issue that does not exist')
        ck(db.execute('SELECT count(*) c FROM research').fetchone()['c'] == 2,
           'the rejected doc was not written')

        rv = view_research(db)
        ck('/r/1' in rv and '/r/2' in rv, 'the research tab lists the doc store')
        ck('>#6<' in rv, 'a linked doc shows the issue it answers')
        dv = view_doc(db, 1)
        ck('<h1>How X actually works</h1>' in dv and 'It caches.' in dv,
           'a doc renders as markdown, not as a code listing')
        ck('<a href="/i/6">#6' in dv, 'a doc links back to its issue')
        ck('<a href="/r/">Research</a> &rsaquo;' in dv,
           'a doc breadcrumbs to Research, not Issues')
        ck(view_doc(db, 99) is None, 'a missing doc 404s')
        ck('<a href="/r/1">' in view_issue(db, 6),
           'the issue lists the research docs that answer it')
        ck(db.execute("SELECT count(*) c FROM proto WHERE path LIKE '%.md'").fetchone()['c'] == 0,
           'a research doc is never a file in the prototype folder')

        # --- one artifact, several issues --------------------------------
        run(['research', f, '1', '--issue', '6', '2', '3'])
        ck(db.execute('SELECT issue FROM research WHERE id=1').fetchone()[0] == 6,
           'the first --issue is the primary')
        ck(issues_of(db, 'doc', 1, 6) == [6, 2, 3], 'the rest are secondary, primary first')
        ck(refs(db, 2)[0] == [(1, ['How X actually works', False])],
           'a secondary issue lists the doc, flagged as not its primary')
        ck(refs(db, 6)[0] == [(1, ['How X actually works', True])],
           'the primary issue lists it as its own')
        ck('also' in view_issue(db, 2) and 'also' not in view_issue(db, 6).split('<h3>research')[1],
           'the issue page marks a secondary link and leaves a primary unmarked')
        ck('also <a href="/i/2">#2</a> <a href="/i/3">#3</a>' in view_doc(db, 1),
           'the doc names every issue it serves')
        run(['research', f, '1', '--issue', '6', '6', '2'])
        ck(issues_of(db, 'doc', 1, 6) == [6, 2], 'a repeated issue is not linked twice')
        try:
            run(['research', f, '1', '--issue', '6', '99'])
            ck(False, 'one bad id rejects the whole link list')
        except SystemExit:
            ck(issues_of(db, 'doc', 1, 6) == [6, 2],
               'one bad id rejects the whole link list, changing nothing')
        run(['research', f, '1', '--issue', '0'])
        ck(issues_of(db, 'doc', 1, None) == [] and
           db.execute('SELECT count(*) c FROM link WHERE doc=1').fetchone()['c'] == 0,
           '--issue 0 clears the primary and the secondaries together')
        run(['research', f, '1', '--issue', '6'])

        # --- the prototype folder ----------------------------------------
        run(['put', f, 'demo/main.py', '--issue', '6'], stdin='print("hi")\n')
        run(['put', f, 'demo/lib/util.py'], stdin='X = 1\n')
        run(['put', f, 'notes.txt'], stdin='scratch\n')
        ck(db.execute('SELECT count(*) c FROM proto').fetchone()['c'] == 3,
           'put stores three files in the virtual folder')
        run(['put', f, 'notes.txt'], stdin='rewritten\n')
        ck(db.execute("SELECT body FROM proto WHERE path='notes.txt'").fetchone()[0]
           == 'rewritten\n', 'put replaces a file rather than duplicating it')
        ck(proto_dir(db, '') == (['demo'], ['notes.txt']),
           'the root of the folder lists its dirs and files, not the whole tree')
        ck(proto_dir(db, 'demo') == (['lib'], ['main.py']), 'a subdirectory lists its own level')
        for bad in ('../etc/passwd', 'a/../../b', ''):
            try:
                vpath(bad); ck(False, 'vpath rejects %r' % bad)
            except SystemExit:
                ck(True, 'vpath rejects %r' % bad)
        ck(vpath('/a//b/./c') == 'a/b/c', 'vpath normalises a messy path')

        pv = view_proto(db, 'demo/main.py')
        ck('&gt;..&lt;' not in pv and '>..</a>' in pv, 'the file tree offers .. inside a subdir')
        ck('>..</a>' not in view_proto(db, ''), 'the root of the folder has no ..')
        ck('print(&quot;hi&quot;)' in pv or 'print("hi")' in pv,
           'the code pane shows the raw file')
        ck('class="sel"' in pv, 'the tree marks the file being shown')
        ck('<a href="/i/6">#6</a>' in pv, 'a linked prototype file names its issue')
        ck('/p/demo/main.py' in view_issue(db, 6),
           'the issue lists the prototype files linked to it')
        run(['put', f, 'demo/main.py'], stdin='print("hi")\n')
        ck(db.execute("SELECT issue FROM proto WHERE path='demo/main.py'").fetchone()[0] == 6,
           'rewriting a file keeps the link it already had')
        ck('<div class="tree">' in pv and '<div class="code">' in pv,
           'the prototype view is split: tree and code')
        ck(view_proto(db, 'nope/nope') is None, 'a path with nothing under it 404s')
        ck(view_proto(db, 'demo') is not None, 'a directory renders without a file selected')
        ck('float' not in CSS, 'nothing in the file header floats onto its neighbour')
        ck('&lt;script&gt;' in view_proto(db, 'x.html')
           if db.execute("INSERT INTO proto(path,body) VALUES('x.html','<script>')") else True,
           'file bodies are escaped, never executed')
        db.execute("DELETE FROM proto WHERE path='x.html'")

        run(['put', f, 'demo/main.py', '--issue', '6', '2'], stdin='print("hi")\n')
        ck(issues_of(db, 'path', 'demo/main.py', 6) == [6, 2],
           'a prototype file spans issues the same way')
        ck([p for p, _ in refs(db, 2)[1]] == ['demo/main.py'],
           'the secondary issue lists the file')
        fh = view_proto(db, 'demo/main.py')
        ck('<span class="ilinks">' in fh and 'class="raw"' in fh,
           'the file header keeps its issue links and its raw link apart')
        run(['put', f, 'demo/main.py', '--issue', '6'], stdin='print("hi")\n')
        ck(issues_of(db, 'path', 'demo/main.py', 6) == [6],
           'a shorter --issue list replaces the old one rather than adding to it')
        run(['put', f, 'gone.py', '--issue', '6', '2'], stdin='x\n')
        run(['rm', f, 'gone.py'])
        ck(db.execute("SELECT count(*) c FROM link WHERE path='gone.py'").fetchone()['c'] == 0,
           'dropping a file drops its links with it, leaving none dangling')

        run(['rm', f, 'notes.txt'])
        ck(db.execute("SELECT count(*) c FROM proto WHERE path='notes.txt'").fetchone()['c'] == 0,
           'rm drops one file')

        # --- pulling it all out ------------------------------------------
        d2 = os.path.join(d, 'out')
        run(['export', f, d2])
        ck(os.path.exists(os.path.join(d2, 'proto', 'demo', 'lib', 'util.py')),
           'export writes prototype files into real directories')
        ck(open(os.path.join(d2, 'proto', 'demo', 'main.py')).read() == 'print("hi")\n',
           'an exported prototype file is byte-identical')
        research_out = sorted(os.listdir(os.path.join(d2, 'research')))
        ck(research_out == ['0001-how-x-actually-works.md', '0002-loose-note.md'],
           'the doc store exports to research/: %s' % research_out)
        ck(open(os.path.join(d2, 'research', research_out[0])).read()
           == '# How X actually works\n\nIt caches.\n',
           'an exported doc is the artifact it came in as, byte for byte')
        issues_out = sorted(os.listdir(os.path.join(d2, 'issues')))
        ck(len(issues_out) == 6 and issues_out[-1].startswith('0006-'),
           'every issue exports to issues/, research-kind included')
        txt = open(os.path.join(d2, 'issues', issues_out[1])).read()
        ck('# #2 First question' in txt and 'Because it works.' in txt,
           'an exported issue carries its header and its comments')

        d3 = os.path.join(d, 'in')
        os.makedirs(os.path.join(d3, 'sub'))
        open(os.path.join(d3, 'sub', 'a.py'), 'w').write('a = 1\n')
        open(os.path.join(d3, '.hidden'), 'w').write('nope\n')
        run(['import', f, d3, '--as', 'imported'])
        ck(db.execute("SELECT body FROM proto WHERE path='imported/sub/a.py'").fetchone()[0]
           == 'a = 1\n', 'import walks a real directory into the folder')
        ck(db.execute("SELECT count(*) c FROM proto WHERE path LIKE '%hidden%'").fetchone()['c'] == 0,
           'import skips dotfiles')

        # --- options and recommendations -------------------------------------
        import contextlib
        h = os.path.join(d, 'opt.wf')
        run(['init', h, '--title', 'Store choice'])
        run(['add', h, '--kind', 'grilling', '--title', 'A: which store', '--parent', '1'])
        run(['add', h, '--kind', 'grilling', '--title', 'Q: which store', '--parent', '1'])
        for t in ('sqlite', 'postgres', 'duckdb'):
            run(['option', h, '3', '--add', t])
        run(['block', h, '2', '--on', '3'])
        dbh = connect(h)
        ck([o['title'] for o in options(dbh, 3)] == ['sqlite', 'postgres', 'duckdb'],
           'a question owns its options, in the order asked')
        ck([o['label'] for o in options(dbh, 3)] == [1, 2, 3],
           'labels are assigned per question, from 1')
        ck([r['id'] for r in dbh.execute(
            "SELECT id FROM issue WHERE status='open' AND assignee=''"
            ' AND parent IS NOT NULL ORDER BY id')] == [2, 3],
           'options are not issues, so the frontier is only the questions')

        run(['recommend', h, '3', '--option', '1'], stdin='one file, no server\n')
        ck(issue(dbh, 3)['recommends'] == 1
           and 'no server' in issue(dbh, 3)['recommendation'],
           'the recommendation names an option and says why')
        try:
            run(['recommend', h, '3', '--option', '99'], stdin='nope\n')
            ck(False, 'a recommendation can only name an option of that question')
        except SystemExit:
            ck(issue(dbh, 3)['recommends'] == 1,
               'a recommendation can only name an option of that question')

        run(['resolve', h, '3'],
            stdin='sqlite, but for durability not simplicity\n\nThe reason given was'
                  ' the wrong one.\n')
        ck(issue(dbh, 3)['verdict'] == '', 'a resolved question carries no verdict at all')
        bh = the_map(dbh)['body']
        ck('- [Q: which store](/i/3): weighed 3 options - sqlite, but for durability'
           in bh, 'the question takes the line and counts what was weighed')
        ck(len(options(dbh, 3)) == 3, 'resolving changes nothing about the options')

        try:
            run(['adr', h, '3'])
            ck(False, 'an ADR needs its own title')
        except SystemExit:
            ck(not issue(dbh, 3)['adr'], 'marking without --title is refused')
        run(['adr', h, '3', '--title', 'SQLite for durability'])
        a3 = render_adr(dbh, issue(dbh, 3), 1)
        ck('Weighed on [#3](/i/3):' in a3, 'Considered Options links the issue once')
        v3 = view_issue(dbh, 3)
        ck('<h2>Options</h2>' in v3 and '<ol>' in v3,
           'serve renders options as a header and an ordered list')
        ck('<h2>Recommendation</h2>' in v3 and 'Option 1.' in v3,
           'and the recommendation as a header, a paragraph, and which item')
        ck(v3.index('<h2>Options</h2>') < v3.index('<div class="cmt">')
           and '<h3>Options</h3>' not in v3,
           'both live inside the main body box, not boxes of their own')

        # an owned section replaces whatever prose was under that heading
        run(['set', h, '3', 'body', '-'],
            stdin='The question.\n\n## Options\n\nstale hand-written list\n')
        v3 = view_issue(dbh, 3)
        ck('stale hand-written list' not in v3 and '<ol>' in v3,
           'the written section is replaced by the one built from the options')
        ck('The question.' in v3, 'and the prose around it is left alone')

        run(['recommend', h, '2'], stdin='nothing to choose between; just do it\n')
        v2 = view_issue(dbh, 2)      # #2 was never given options
        ck('<h2>Options</h2>' not in v2 and '<h2>Recommendation</h2>' in v2,
           'a question with no options still renders its recommendation')
        ck('Option ' not in v2,
           'and names no item, because item 0 is not an option that exists')
        ck('- 1. sqlite\n- 2. postgres\n- 3. duckdb' in a3,
           'and lists the titles by their stable numbers')
        ck('durability' not in a3.split('Considered Options')[1],
           'it does not repeat which was taken, nor why the rest were not')

        run(['add', h, '--kind', 'grilling', '--title', 'Scratch', '--parent', '1'])
        for t in ('keep', 'drop', 'also keep'):
            run(['option', h, '4', '--add', t])
        run(['recommend', h, '4', '--option', '2'], stdin='the one to drop\n')
        run(['option', h, '4', '--rm', '2'])
        ck([o['title'] for o in options(dbh, 4)] == ['keep', 'also keep'],
           'an option can be dropped while the question is open')
        ck([o['label'] for o in options(dbh, 4)] == [1, 3],
           'and the numbers that remain do not shift: 1, 3')
        ck(next_label(dbh, 4) == 4, 'a dropped number is never reused')
        ck(issue(dbh, 4)['recommends'] is None,
           'dropping the recommended option clears the pointer that named it')

        # --- where the answer landed ------------------------------------------
        newest = lambda: dbh.execute('SELECT MAX(id) m FROM issue').fetchone()['m']
        ck(picked_note(issue(dbh, 3)) is None,
           'an issue resolved without --picked claims nothing')

        run(['add', h, '--kind', 'grilling', '--title', 'Landed on one', '--parent', '1'])
        one = newest()
        run(['option', h, str(one), '--add', 'first'])
        run(['option', h, str(one), '--add', 'second'])
        try:
            run(['resolve', h, str(one), '--picked', '9'], stdin='nope\n')
            ck(False, '--picked must name an option of that question')
        except SystemExit:
            ck(issue(dbh, one)['status'] == 'open',
               '--picked must name an option of that question')
        run(['resolve', h, str(one), '--picked', '2'], stdin='the second\n\nBecause.\n')
        ck(issue(dbh, one)['picked'] == 2 and picked_note(issue(dbh, one)) == 'Option 2.',
           'a pick is recorded and reads as the item number')
        ck('<p><strong>Option 2.</strong></p>' in view_issue(dbh, one),
           'the pick stands as its own paragraph above the reasoning')
        ck('**Option 2.**\n\nBecause.' in render_item(dbh, issue(dbh, one)),
           'and the exported comment does too')

        run(['add', h, '--kind', 'grilling', '--title', 'Landed on none', '--parent', '1'])
        none_ = newest()
        run(['option', h, str(none_), '--add', 'neither this'])
        run(['resolve', h, str(none_), '--picked', '0'],
            stdin='something else entirely\n\nWhy.\n')
        ck(picked_note(issue(dbh, none_)) == 'None of the options.',
           'picked 0 says the answer was invented rather than chosen')
        ck('<p><strong>None of the options.</strong></p>' in view_issue(dbh, none_),
           'a claim of its own stands as its own paragraph, not a label on one')

        # the two deadlocks that used to be silent
        try:
            run(['block', h, '3', '--on', '2'])
            ck(False, 'a blocking cycle is refused')
        except SystemExit:
            ck(waiting(dbh, 3) == [], 'a blocking cycle is refused')
        try:
            run(['set', h, '2', 'kind', 'map'])
            ck(False, 'a second map is refused')
        except SystemExit:
            ck(issue(dbh, 2)['kind'] == 'grilling', 'a second map is refused')

        # --- revising a decision -------------------------------------------
        def nlines(i):
            """Lines for issue i inside the owned sections only - a lookalike
            out in the fog is prose, and must not count."""
            bd = the_map(dbh)['body']
            return sum(len(_line_re(i).findall(bd[lo:hi])) for lo, hi in
                       filter(None, (_span(bd, DECISIONS), _span(bd, OUT_OF_SCOPE))))
        sect = lambda i: line_section(the_map(dbh)['body'], i)

        fog = the_map(dbh)['body'].replace(
            '## Not yet specified',
            '## Not yet specified\n- [not a decision](/i/3): fog prose, hands off')
        run(['set', h, '1', 'body', '-'], stdin=fog)

        before = re.findall(r'\(/i/(\d+)\):', the_map(dbh)['body'])
        run(['gist', h, '3', 'sqlite, for now'])
        ck(nlines(3) == 1, 'gist rewrites in place rather than appending')
        ck(re.findall(r'\(/i/(\d+)\):', the_map(dbh)['body']) == before,
           'a revised line holds its position; the section is not reordered')
        ck('- [Q: which store](/i/3): weighed 3 options - sqlite, for now'
           in the_map(dbh)['body'], 'the new summary is on the map, the count rebuilt')
        ck('durability' not in the_map(dbh)['body'], 'and the old one is gone')
        ck('fog prose, hands off' in the_map(dbh)['body'],
           'a lookalike line in the fog is left alone')

        # a body rewrite that omits the decisions must not delete them
        def owned_lines():
            bd = the_map(dbh)['body']
            return sum(bd[lo:hi].count('](/i/') for lo, hi in
                       filter(None, (_span(bd, DECISIONS), _span(bd, OUT_OF_SCOPE))))
        before_n = owned_lines()
        ck(before_n > 0, 'the map has decisions to lose in the first place')

        # the legitimate round trip: owned sections back verbatim, fog rewritten
        cur = the_map(dbh)['body']
        run(['set', h, '1', 'body', '-'],
            stdin=cur.replace('- [not a decision](/i/3): fog prose, hands off', 'new fog'))
        ck(owned_lines() == before_n and 'new fog' in the_map(dbh)['body']
           and 'fog prose, hands off' not in the_map(dbh)['body'],
           'set rewrites the fog freely while the owned sections round-trip')

        for bad, why in (
                ('## Destination\n\nx\n\n## %s\n\n## Not yet specified\n\n'
                 '## %s\n' % (DECISIONS, OUT_OF_SCOPE),
                 'set refuses a body that drops a decision, rather than silently '
                 'restoring it'),
                (the_map(dbh)['body'].replace('## ' + OUT_OF_SCOPE,
                                              '## ' + OUT_OF_SCOPE + '\n- mine'),
                 'and refuses one that adds to an owned section, rather than '
                 'silently discarding it'),
                ('no headings here\n', 'and one missing the headings entirely')):
            try:
                run(['set', h, '1', 'body', '-'], stdin=bad)
                ck(False, why)
            except SystemExit:
                ck(owned_lines() == before_n and 'mine' not in the_map(dbh)['body'], why)

        run(['gist', h, '3', '--oos'])
        ck(sect(3) == OUT_OF_SCOPE and nlines(3) == 1,
           'gist moves a line between the owned sections, leaving nothing behind')
        run(['gist', h, '3', '--decision'])
        ck(sect(3) == DECISIONS and nlines(3) == 1, 'and moves it back')
        try:
            run(['gist', h, '2'])
            ck(False, 'an open issue has no line to rewrite')
        except SystemExit:
            ck(True, 'an open issue has no line to rewrite')

        # --- superseding -----------------------------------------------------
        run(['resolve', h, '2', '--supersedes', '3'],
            stdin='postgres after all\n\nThe effort grew a second writer.\n')
        ck(issue(dbh, 3)['verdict'] == 'superseded'
           and issue(dbh, 3)['superseded_by'] == 2, 'the old decision points forward')
        ck(nlines(3) == 1, 'the superseded line is rewritten, not duplicated')
        ck('- [Q: which store](/i/3): superseded by #2 - sqlite, for now'
           in the_map(dbh)['body'], 'it keeps its own summary and names its successor')
        try:
            run(['resolve', h, '4', '--supersedes', '3'], stdin='again\n')
            ck(False, 'a superseded decision cannot be superseded twice')
        except SystemExit:
            ck(issue(dbh, 3)['superseded_by'] == 2,
               'a superseded decision cannot be superseded twice')

        seen2 = io.StringIO()
        with contextlib.redirect_stdout(seen2):
            run(['map', h]); run(['show', h, '3'])
        ck('SUPERSEDED BY #2' in seen2.getvalue(), 'map and show name the successor')
        ck('1. sqlite' in seen2.getvalue(),
           'show lists the options the question weighed')
        ck('superseded by <a href="/i/2">#2</a>' in view_issue(dbh, 3),
           'and the served page links it')
        vm = view_issue(dbh, 1)
        ck('<dl class="dec">' in vm and '<dt><a href="/i/3">Q: which store</a></dt>' in vm,
           'the map renders its decisions as a definition list, question first')
        ck('<dd>sqlite, for now<br><span class="gist">(superseded by #2)</span></dd>' in vm,
           'the answer is the definition, and what qualifies it sits on its own line')
        ck('<h2>Not yet specified</h2>' in vm,
           'the sections the map does not own stay ordinary markdown')
        ck('2. **postgres**' in render_item(dbh, issue(dbh, 3)),
           'the exported issue carries its options')

        # --- glossary --------------------------------------------------------
        run(['term', h, 'Order', '--def', 'A customer request for goods.',
             '--avoid', 'purchase, transaction', '--issue', '2'])
        ck(term_row(dbh, 'order')['name'] == 'Order',
           'a term is keyed case-blind: "order" finds "Order"')
        ck(term_row(dbh, 'Order')['issue'] == 2,
           'a term can name the issue that settled it')
        run(['term', h, 'Order', '--def', 'A customer request for goods, priced.'])
        ck('priced' in term_row(dbh, 'Order')['body']
           and avoid_list(term_row(dbh, 'Order')['avoid']) == ['purchase', 'transaction'],
           'refining a definition leaves the avoid list alone')
        ck([c['name'] for c in term_clash(dbh, 'Purchase')] == ['Order'],
           'an avoided word points back at the canonical term, case-blind')
        try:
            run(['term', h, 'transaction', '--def', 'nope'])
            ck(False, 'defining an avoided word as its own term is refused')
        except SystemExit:
            ck(term_row(dbh, 'transaction') is None,
               'defining an avoided word as its own term is refused')
        ck('**Order**:' in render_context(dbh)
           and '_Avoid_: purchase, transaction' in render_context(dbh),
           'CONTEXT.md renders in the format the skill asks for')

        # --- decision records ------------------------------------------------
        ck(adr_no(dbh, 3) == 1, '#3 was marked in the options block, as ADR-0001')
        run(['adr', h, '2', '--title', 'Second decision'])
        ck([r['id'] for r in adrs(dbh)] == [3, 2], 'ADRs list in the order marked')
        ck(adr_no(dbh, 2) == 2, 'the number is the order of marking, not of issue id')
        run(['add', h, '--kind', 'grilling', '--title', 'Older, marked later',
             '--parent', '1'])
        late = newest()
        run(['resolve', h, str(late)], stdin='closed later\n')
        run(['adr', h, str(late), '--title', 'Later decision'])
        ck(adr_no(dbh, 3) == 1 and adr_no(dbh, 2) == 2 and adr_no(dbh, late) == 3,
           'marking another issue never renumbers an ADR already published')
        run(['adr', h, str(late), '--title', 'Later decision'])
        ck(adr_no(dbh, late) == 3, 'marking twice is idempotent, not a new number')
        try:
            run(['adr', h, '1', '--title', 'Should not matter'])
            ck(False, 'an open issue cannot be an ADR')
        except SystemExit:
            ck(not issue(dbh, 1)['adr'], 'an open issue cannot be an ADR')
        a3 = render_adr(dbh, issue(dbh, 3), 1)
        ck('- Status: superseded by ADR-0002' in a3,
           'a superseded ADR names its successor by ADR number, not issue id')

        d3 = os.path.join(d, 'ctx')
        run(['export', h, d3])
        ck(os.path.exists(os.path.join(d3, 'CONTEXT.md')),
           'export writes CONTEXT.md at the root, not under a wfr subdirectory')
        adrf = sorted(os.listdir(os.path.join(d3, 'docs', 'adr')))
        ck([f[:5] for f in adrf] == ['0001-', '0002-', '0003-'],
           'and docs/adr/NNNN-slug.md, one file per ADR and no collisions')
        ck(markdown(render_context(dbh, heading=False)) in view_terms(dbh),
           'the Definitions tab renders exactly what export writes')
        ck(markdown(render_adr(dbh, issue(dbh, 2), 2, False)) in view_adr(dbh, 2),
           'and so does the Decisions tab')
        ck(view_adr(dbh, 2).count('<h1>') == 1,
           'the ADR page has one h1: the markdown does not repeat the chrome')
        ck(issue(dbh, 2)['adr_title'] in view_adr(dbh, 2).split('</header>')[0],
           'the ADR title rides in the crumb, where a reader looks for it')
        ck(render_adr(dbh, issue(dbh, 2), 2).startswith('# '),
           'the exported file still opens with its own title')
        ck(view_adr(dbh, 9) is None, 'an ADR number nothing carries 404s')
        dbh.close()

        # --- a spec retrofitted into a map --------------------------------
        sp = os.path.join(d, 'spec.wf')
        run(['init', sp, '--title', 'Started as a spec', '--kind', 'spec'])
        try:
            run(['add', sp, '--kind', 'grilling', '--title', 'Q'])
            ck(False, 'add refuses without --parent: where it hangs is a choice')
        except SystemExit:
            ck(True, 'add refuses without --parent: where it hangs is a choice')
        run(['add', sp, '--kind', 'grilling', '--title', 'Q', '--parent', '1'])
        dbs = connect(sp)
        ck([r['id'] for r in dbs.execute('SELECT id FROM issue WHERE parent IS NULL')] == [1],
           'so a second root cannot be made by omission')
        run(['add', sp, '--kind', 'grilling', '--title', 'Follow-up', '--parent', '2'])
        ck(issue(dbs, 3)['parent'] == 2,
           'a question opened by another hangs off that one, not the root')

        ck(the_root(dbs)['body'].strip() == '', 'a spec root starts with no skeleton')
        run(['set', sp, '1', 'kind', 'map'])
        ck(all(_span(the_root(dbs)['body'], h) for h in (DECISIONS, OUT_OF_SCOPE)),
           'promoting an issue to a map seeds the headings resolve writes to')
        run(['resolve', sp, '2'], stdin='it works now\n')
        ck('- [Q](/i/2): it works now' in the_root(dbs)['body'],
           'so resolve has somewhere to write, with no hand-editing')
        run(['gist', sp, '2', 'and gist too'])
        ck('and gist too' in the_root(dbs)['body'], 'and so does gist')

        # a heading the stored body never had may be added back
        stripped = the_root(dbs)['body'].replace('## ' + OUT_OF_SCOPE, '')
        dbs.execute('UPDATE issue SET body=? WHERE id=1', (stripped,))
        run(['set', sp, '1', 'body', '-'], stdin=stripped + '\n## %s\n' % OUT_OF_SCOPE)
        ck(_span(the_root(dbs)['body'], OUT_OF_SCOPE) is not None,
           'a missing owned heading can be put back: absent is not altered')
        dbs.close()

        # a wfr.py-made file has no proto table until wfr2 opens it
        old = os.path.join(d, 'old.wf')
        db3 = sqlite3.connect(old)
        db3.executescript(SCHEMA)
        db3.execute("INSERT INTO issue(id,kind,title) VALUES(1,'map','Old')")
        db3.commit(); db3.close()
        db3 = connect(old)
        ck(db3.execute("SELECT count(*) c FROM sqlite_master WHERE name IN"
                       " ('proto','research','term')").fetchone()['c'] == 3,
           'opening an old wfr.py tracker adds its stores in place')
        ck('verdict' in {r[1] for r in db3.execute('PRAGMA table_info(issue)')},
           'and the verdict column, defaulted so an older wfr.py still writes')
        db3.close()

        # the glossary readout: a missing term leaves no trace of itself, so
        # frontier carries the count to where the round already looks
        g = os.path.join(d, 'gloss.wf')
        run(['init', g, '--title', 'Glossary readout'])
        run(['add', g, '--kind', 'grilling', '--title', 'A question', '--parent', '1'])

        def frontier_out():
            buf = io.StringIO()
            old_out = sys.stdout
            sys.stdout = buf
            try:
                run(['frontier', g])
            finally:
                sys.stdout = old_out
            return buf.getvalue()

        ck('glossary' not in frontier_out(),
           'no resolved grill, no glossary readout: nothing to compare yet')
        run(['resolve', g, '2'], stdin='settled\n')
        ck('1 grilling resolved · 0 in the glossary' in frontier_out(),
           'a resolved grill with no term shows the gap on the frontier')
        run(['term', g, 'Widget', '--def', 'A widget is a thing.'])
        ck('1 grilling resolved · 1 in the glossary' in frontier_out(),
           'and the count follows the glossary')
        db.close()

    print('\n%s' % ('FAILED: ' + '; '.join(fails) if fails else 'all checks passed'))
    return 1 if fails else 0


# ---------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser(prog=PROG, add_help=False,
                                 description='wayfinder tracker in one file')
    ap.add_argument('-h', '--help', action='store_true')
    sub = ap.add_subparsers(dest='cmd')

    def P(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument('file')
        return p

    p = P('init'); p.add_argument('--title', required=True)
    p.add_argument('--kind', choices=KINDS, default='map')
    p = P('add')
    p.add_argument('--kind', required=True, choices=KINDS)
    p.add_argument('--title', required=True)
    p.add_argument('--parent', type=int, required=True)
    p.add_argument('--body', default='')
    p = P('set'); p.add_argument('id', type=int); p.add_argument('pairs', nargs='+')
    p = P('block'); p.add_argument('id', type=int); p.add_argument('--on', type=int, nargs='+', required=True)
    p = P('unblock'); p.add_argument('id', type=int); p.add_argument('--on', type=int, nargs='+', required=True)
    p = P('claim'); p.add_argument('id', type=int); p.add_argument('who', nargs='?')
    p = P('comment'); p.add_argument('id', type=int)
    p = P('resolve'); p.add_argument('id', type=int)
    p.add_argument('--oos', '--out-of-scope', action='store_true', dest='oos')
    p.add_argument('--supersedes', type=int, metavar='M')
    p.add_argument('--picked', type=int, metavar='N', default=None)
    p.add_argument('--adr', action='store_true')
    p.add_argument('--adr-title', dest='adr_title', metavar='TITLE', default='')
    p = P('gist'); p.add_argument('id', type=int)
    p.add_argument('text', nargs='?')
    g = p.add_mutually_exclusive_group()
    g.add_argument('--oos', '--out-of-scope', action='store_true', dest='oos')
    g.add_argument('--decision', action='store_true')
    p = P('option'); p.add_argument('issue', type=int)
    p.add_argument('--add', metavar='TITLE')
    p.add_argument('--body', default=''); p.add_argument('--rm', type=int, metavar='N')
    p = P('recommend'); p.add_argument('issue', type=int)
    p.add_argument('--option', type=int, metavar='N')
    p = P('show'); p.add_argument('id', type=int)
    p = P('term'); p.add_argument('name', nargs='?')
    p.add_argument('--def', dest='definition'); p.add_argument('--avoid')
    p.add_argument('--group'); p.add_argument('--issue', type=int)
    p.add_argument('--rm', action='store_true')
    p = P('adr'); p.add_argument('id', type=int, nargs='?')
    p.add_argument('--no', action='store_true')
    p.add_argument('--title', metavar='TITLE', default='')
    P('map'); P('frontier')
    p = P('research'); p.add_argument('id', type=int, nargs='?')
    p.add_argument('--title'); p.add_argument('--issue', type=int, nargs='+')
    p.add_argument('--from', dest='frm', metavar='PATH'); p.add_argument('--body')
    p = P('put'); p.add_argument('path'); p.add_argument('--issue', type=int, nargs='+')
    p = P('cat'); p.add_argument('path')
    p = P('rm'); p.add_argument('path')
    p = P('ls'); p.add_argument('prefix', nargs='?', default='')
    p = P('import'); p.add_argument('dir'); p.add_argument('--as', dest='prefix', default='')
    p.add_argument('--issue', type=int, nargs='+')
    p = P('export'); p.add_argument('dir')
    p = P('serve'); p.add_argument('--port', type=int, default=8080)
    sub.add_parser('help'); sub.add_parser('selftest')

    a = ap.parse_args(argv)
    if a.help or a.cmd in (None, 'help'):
        print(HELP.replace('wfr.py', PROG))
        return 0
    if a.cmd in ('block', 'unblock'):
        a.unblock = a.cmd == 'unblock'
    fn = globals()['cmd_' + {'unblock': 'block'}.get(a.cmd, a.cmd)]
    return fn(a) or 0


if __name__ == '__main__':
    sys.exit(main())
