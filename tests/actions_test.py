#!/usr/bin/env python3
"""Checks the GitHub workflows for the ways Actions get abused to get past review.

Write tokens only where WRITES allows them, actions pinned to full commit SHAs from GitHub (plus Scorecard),
no outsider-triggered events that run with a write token, no ${{ }} pasted into shell or script code, GitHub's
own runners only, and no git credentials left behind. Also that sizes.yml's commit job lets a weekly refresh change
only sizes and checked download names in tools/regions.json. Usage: python3 tests/actions_test.py
"""
import re
import sys
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

# The only jobs that get a write token, and what each may write. Anything else is read-only.
WRITES = {
    ("pr-gate.yml", "gate"): {"issues", "pull-requests"},      # closes outside PRs without an accepted issue
    ("pr-gate.yml", "labels"): {"issues"},                     # creates the gate's labels, run by hand
    ("sizes.yml", "commit"): {"contents"},                     # commits builder sizes and places; runs no kit code
    ("pins.yml", "commit"): {"contents"},                      # commits program pins; runs no kit code
    ("scorecard.yml", "analysis"): {"security-events", "id-token"},   # publishes the Scorecard results
}
# Actions from GitHub itself and OpenSSF's Scorecard, at a full commit SHA: a tag can be moved to new code.
ALLOWED = re.compile(r"^(actions/[\w.-]+|github/codeql-action/[\w.-]+|ossf/scorecard-action)@[0-9a-f]{40}$")
# Events an outsider can fire that run this repo's workflows with a write token and secrets.
PRIVILEGED = {"pull_request_target", "workflow_run", "issue_comment", "pull_request_review",
              "pull_request_review_comment", "discussion", "discussion_comment"}
GATE = "pr-gate.yml"    # the one pull_request_target workflow: GitHub's API through github-script, nothing else


def parse(text):
    """Flattens a workflow into (path, value, comment, line) per key, with block scalars (run: |) whole.
    Enough YAML for workflows: block mappings and sequences; flow values ([a, b]) stay text."""
    out, stack, lines, i, items = [], [], text.split("\n"), 0, 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        body = raw.strip()
        if not body or body.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        while body == "-" or body.startswith("- "):
            while stack and (stack[-1][0] > indent or (stack[-1][0] == indent and stack[-1][1][0] == "-")):
                stack.pop()
            items += 1
            stack.append((indent, f"-{items}"))
            body, indent = body[2:].lstrip(), indent + 2
        if not body:
            continue
        m = re.match(r"""^("[^"]*"|'[^']*'|[^\s:#'"][^:#]*?)\s*:(?:\s+(.*)|$)""", body)
        key, value = (m.group(1).strip("'\""), m.group(2) or "") if m else (None, body)
        if key is not None:
            while stack and stack[-1][0] >= indent:
                stack.pop()
            stack.append((indent, key))
        path = tuple(n for _, n in stack)
        if key is not None and re.match(r"^[|>][-+]?\d*\s*(#.*)?$", value):
            start, block = i, []
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip(" ")) > indent):
                block.append(lines[i])
                i += 1
            out.append((path, "\n".join(block), "", start))
            continue
        # A value ends at " #" unless it's quoted, as in YAML: "x@sha # v5" is x@sha with the comment v5.
        if value[:1] in ("'", '"') and value.find(value[0], 1) > 0:
            end = value.find(value[0], 1)
            value, comment = value[1:end], value[end + 1:]
        else:
            hit = re.search(r"\s#", value)
            value, comment = (value[:hit.start()], value[hit.start():]) if hit else (value, "")
        out.append((path, value.strip(), comment.strip().lstrip("#").strip(), i))
    return out


def problems(name, text):
    nodes, errs = parse(text), []
    jobs = {p[1] for p, _, _, _ in nodes if len(p) > 1 and p[0] == "jobs"}

    top = [(p, v) for p, v, _, _ in nodes if p[0] == "permissions"]
    if not top:
        errs.append("no top-level permissions:, so jobs get the repo's default token, which may write")
    errs += [f"top-level permissions give {'/'.join(p[1:]) or 'everything'} {v}; give write only to the job that "
             f"needs it" for p, v in top if v in ("write", "write-all")]
    for p, v, _, n in nodes:
        if len(p) >= 3 and p[0] == "jobs" and p[2] == "permissions" and v in ("write", "write-all"):
            scope = p[3] if len(p) > 3 else "everything"
            if scope not in WRITES.get((name, p[1]), set()):
                errs.append(f"line {n}: job {p[1]} gets {scope}: write, which WRITES in tests/actions_test.py doesn't allow")

    events = {p[1] for p, _, _, _ in nodes if len(p) > 1 and p[0] == "on"}
    events |= {e for p, v, _, _ in nodes if p == ("on",) for e in re.findall(r"[\w-]+", v)}
    for e in sorted(events & PRIVILEGED):
        if not (e == "pull_request_target" and name == GATE):
            errs.append(f"triggers on {e}, which runs with a write token on outsiders' input")
    if "pull_request_target" in events:
        for p, v, _, n in nodes:
            if p[-1] == "uses" and not v.startswith("actions/github-script@"):
                errs.append(f"line {n}: {v} in a pull_request_target workflow; use the API through github-script")
        if re.search(r"head\.sha|head\.ref|head_ref|refs/pull/", text):
            errs.append("a pull_request_target workflow names the pull request's code; it must never fetch or run it")

    for p, v, comment, n in nodes:
        if p[-1] == "uses":
            if not ALLOWED.match(v):
                errs.append(f"line {n}: {v} isn't an action from GitHub or Scorecard pinned to a full commit SHA")
            elif not re.match(r"v\d", comment):
                errs.append(f"line {n}: {v} needs its version as a comment (# v5), for Dependabot and readers")
            if v.startswith("actions/checkout@"):
                creds = [w for q, w, _, _ in nodes if q == p[:-1] + ("with", "persist-credentials")]
                if creds != ["false"] and "contents" not in WRITES.get((name, p[1]), set()):
                    errs.append(f"line {n}: checkout leaves the token in .git/config; add persist-credentials: false")
        elif "${{" in v and ((p[-1] == "run" and p[-2][0] == "-") or (p[-2:] == ("with", "script") and p[-3][0] == "-")):
            errs.append(f"line {n}: ${{{{ }}}} pasted into {p[-1]} code; pass the value in through env: instead")
        elif p[-1] == "runs-on" and not re.match(r"^(ubuntu|macos|windows)-[\w.]+$", v):
            errs.append(f"line {n}: runs-on {v}; only GitHub's own runners, since a self-hosted one would run "
                        f"outsiders' code on our machine")
    errs += [f"uses the secret {s}; keep the repo free of secrets" for s in
             sorted(set(re.findall(r"secrets\.(\w+)", text)) - {"GITHUB_TOKEN"})]
    if not jobs:
        errs.append("found no jobs, so the parser is out of step with this file")
    return errs


# Each must be caught, so the checks above can't quietly stop working.
JOB = "permissions: {}\non: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
PIN = "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5"
BAD = {
    "a tag instead of a SHA": JOB + "      - uses: actions/checkout@v5\n        with:\n          persist-credentials: false\n",
    "a third-party action": JOB + "      - uses: someone/thing@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v1\n",
    "a SHA with no version comment": JOB + "      - uses: actions/cache@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09\n",
    "saved git credentials": JOB + f"      - uses: {PIN}\n",
    "no top-level permissions": JOB.replace("permissions: {}\n", "") + "      - run: true\n",
    "write at the top": JOB.replace("{}", "\n  contents: write") + "      - run: true\n",
    "write-all in a job": JOB.replace("    steps:", "    permissions: write-all\n    steps:") + "      - run: true\n",
    "an unlisted write": JOB.replace("    steps:", "    permissions:\n      statuses: write\n    steps:") + "      - run: true\n",
    "issue_comment": JOB.replace("on: push", "on:\n  issue_comment:") + "      - run: true\n",
    "workflow_run": JOB.replace("on: push", "on: [push, workflow_run]") + "      - run: true\n",
    "pull_request_target outside the gate": JOB.replace("on: push", "on:\n  pull_request_target:") + "      - run: true\n",
    "an expression in run": JOB + "      - run: |\n          echo hi\n          echo \"${{ github.event.issue.title }}\"\n",
    "an expression in a one-line run": JOB + "      - run: echo ${{ inputs.words }}\n",
    "an expression in script": JOB + "      - uses: actions/github-script@ed597411d8f924073f98dfc5c65a23a2325f34cd # v8\n"
                                     "        with:\n          script: |\n            core.info('${{ github.head_ref }}')\n",
    "a self-hosted runner": JOB.replace("ubuntu-latest", "[self-hosted, linux]") + "      - run: true\n",
    "a secret": JOB + "      - run: deploy\n        env:\n          KEY: ${{ secrets.DEPLOY_KEY }}\n",
}
GATE_BAD = {
    "checkout in the gate": f"permissions: {{}}\non:\n  pull_request_target:\njobs:\n  gate:\n    runs-on: ubuntu-latest\n"
                            f"    steps:\n      - uses: {PIN}\n        with:\n          persist-credentials: false\n",
    "fetching the pull request in the gate": "permissions: {}\non:\n  pull_request_target:\njobs:\n  gate:\n"
                                             "    runs-on: ubuntu-latest\n    steps:\n      - run: git fetch origin refs/pull/1/head\n",
}


def regions_check():
    """Runs sizes.yml's merge of a new tools/regions.json, one change at a time: sizes and checked downloads come
    through, ids, names and anything else don't."""
    import copy, json, shutil, subprocess, tempfile, textwrap
    root = WORKFLOWS.parent.parent
    code = textwrap.dedent((WORKFLOWS / "sizes.yml").read_text().split("tools/regions.json <<'PY'\n", 1)[1]
                           .split("\n          PY\n", 1)[0])
    committed = root / "tools" / "regions.json"
    base = json.loads(committed.read_text(encoding="utf-8"))
    def first(d):
        return d["regions"][0]
    def same(*keys):
        return lambda m: all(first(m)[k] == first(base)[k] for k in keys)
    cases = [("nothing new", lambda d: None, lambda m: m == base),
             ("new sizes", lambda d: first(d)["mb"].update(tiles=1), lambda m: first(m)["mb"]["tiles"] == 1),
             ("a renamed place, with new sizes", lambda d: first(d).update(name="x", mb={"tiles": 1}),
              lambda m: first(m)["name"] == first(base)["name"] and first(m)["mb"] == {"tiles": 1}),
             ("a command in an id", lambda d: first(d).update(id="us/x; sh"), lambda m: m == base),
             ("a new nickname and home", lambda d: first(d).update(also=["x"], home={"label": "x"}), same("also", "home")),
             ("a download elsewhere", lambda d: first(d).update(pbf="https://x/a-latest.osm.pbf"), same("pbf")),
             ("a path up", lambda d: first(d).update(pbf="../a-latest.osm.pbf", photon="a//photon-db-x-1.0-latest.tar.bz2"),
              same("pbf", "photon")),
             ("a file that isn't Wikipedia", lambda d: d["languages"]["en"].update(zim="x_en_all_maxi"), lambda m: m == base),
             ("a size as text", lambda d: first(d)["mb"].update(tiles="1"), same("mb")),
             ("an unknown language", lambda d: first(d)["langs"].append("zz"), same("langs")),
             ("a new place", lambda d: d["regions"].append(dict(first(d), id="xx")), lambda m: m == base)]
    errs = []
    with tempfile.TemporaryDirectory() as t:
        new, out = Path(t) / "new.json", Path(t) / "regions.json"
        for what, change, holds in cases:
            d = copy.deepcopy(base)
            change(d)
            new.write_text(json.dumps(d), encoding="utf-8")
            shutil.copy(committed, out)
            ran = subprocess.run([sys.executable, "-I", "-c", code, str(new), str(out)], capture_output=True).returncode == 0
            if not (ran and holds(json.loads(out.read_text(encoding="utf-8")))):
                errs.append(f"sizes.yml's regions.json merge gets {what} wrong")
        if out.read_bytes() != committed.read_bytes():
            errs.append("sizes.yml writes regions.json in another layout than build_regions.py")
    return len(cases) + 1, errs


def main():
    passed, failed = 0, 0
    for f in sorted(WORKFLOWS.glob("*.y*ml")):
        for e in problems(f.name, f.read_text()):
            print(f"FAIL: {f.name}: {e}")
            failed += 1
        passed += 1
    for what, text in list(BAD.items()) + list(GATE_BAD.items()):
        if problems(GATE if what in GATE_BAD else "x.yml", text):
            passed += 1
        else:
            print(f"FAIL: the checks miss {what}")
            failed += 1
    n, errs = regions_check()
    for e in errs:
        print(f"FAIL: {e}")
    passed, failed = passed + n - len(errs), failed + len(errs)
    print(f"{failed} FAILED, {passed} passed" if failed else f"ALL {passed} PASSED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
