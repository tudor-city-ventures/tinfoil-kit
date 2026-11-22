// Runs the github-scripts in .github/workflows/pr-gate.yml against fake pull requests and issues and a fake GitHub
// API, and the issue check against what GitHub writes for each form in .github/ISSUE_TEMPLATE.
// Usage: node tests/pr_gate_test.js
const fs = require("fs");
const path = require("path");

const yml = fs.readFileSync(path.join(__dirname, "..", ".github", "workflows", "pr-gate.yml"), "utf8").split("\n");
const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;
function script(job) {    // the `script: |` block of that job
  const at = yml.findIndex((l, i) => /^\s+script: \|\s*$/.test(l) && i > yml.indexOf(`  ${job}:`));
  const indent = yml[at + 1].match(/^ */)[0].length;
  const body = [];
  for (const l of yml.slice(at + 1)) {
    if (l.trim() && l.match(/^ */)[0].length < indent) break;
    body.push(l.slice(indent));
  }
  return new AsyncFunction("github", "context", "core", body.join("\n"));
}
const gate = script("gate");
const guard = script("protected-files");
const forms = script("forms");
const TEMPLATES = path.join(__dirname, "..", ".github", "ISSUE_TEMPLATE");

const REPO = { owner: "tudor-city-ventures", repo: "tinfoilkit" };
const ACCEPTED = { labels: [{ name: "accepted" }] };

async function run({ pr = {}, issues = {}, action = "opened", sender }) {
  const calls = [];
  const p = {
    number: 50, title: "Add a thing", body: "", author_association: "NONE",
    user: { login: "drive-by" }, head: { repo: { full_name: "drive-by/tinfoilkit" } }, ...pr,
  };
  const github = { rest: {
    issues: {
      get: async ({ issue_number }) => {
        if (!issues[issue_number]) throw Object.assign(new Error("Not Found"), { status: 404 });
        return { data: { number: issue_number, state: "open", labels: [], ...issues[issue_number] } };
      },
      createComment: async (a) => { calls.push("comment"); p.comment = a.body; },
      addLabels: async (a) => calls.push(`label ${a.labels}`),
    },
    pulls: { update: async (a) => calls.push(a.state) },
  } };
  const context = { repo: REPO, payload: { action, pull_request: p, sender: sender || p.user } };
  await gate(github, context, { info() {}, warning() {} });
  return { closed: calls.includes("closed"), calls, comment: p.comment };
}

let passed = 0, failed = 0;
function check(name, ok) {
  if (ok) passed++;
  else { failed++; console.log(`FAIL: ${name}`); }
}
async function expect(name, opts, closed) {
  const r = await run(opts);
  check(`${name}: expected ${closed ? "closed" : "left open"}, calls ${JSON.stringify(r.calls)}`, r.closed === closed);
  return r;
}

(async () => {
  const r = await expect("no issue linked", {}, true);
  check("the comment says what to do", /`accepted`/.test(r.comment) && /CONTRIBUTING\.md/.test(r.comment));
  check("it's labeled auto-closed", r.calls.includes("label auto-closed"));
  await expect("no description at all", { pr: { body: null } }, true);

  await expect("Closes an accepted issue", { pr: { body: "Closes #12" }, issues: { 12: ACCEPTED } }, false);
  await expect("mentions it mid-sentence", { pr: { body: "This does what (#12) asks." }, issues: { 12: ACCEPTED } }, false);
  await expect("mentions it in the title", { pr: { title: "Fix the thing in #12" }, issues: { 12: ACCEPTED } }, false);
  await expect("links its URL", { pr: { body: "Fixes https://github.com/Tudor-City-Ventures/tinfoilkit/issues/12" }, issues: { 12: ACCEPTED } }, false);
  await expect("owner/repo#12", { pr: { body: "Resolves tudor-city-ventures/tinfoilkit#12" }, issues: { 12: ACCEPTED } }, false);
  await expect("one of several references is accepted", { pr: { body: "See #3 and #12" }, issues: { 3: {}, 12: ACCEPTED } }, false);

  await expect("issue isn't accepted", { pr: { body: "Closes #13" }, issues: { 13: { labels: [{ name: "enhancement" }] } } }, true);
  await expect("accepted issue is closed", { pr: { body: "Closes #12" }, issues: { 12: { ...ACCEPTED, state: "closed" } } }, true);
  await expect("number is a pull request", { pr: { body: "Closes #12" }, issues: { 12: { ...ACCEPTED, pull_request: {} } } }, true);
  await expect("number doesn't exist", { pr: { body: "Closes #999" } }, true);
  await expect("another repo's issue", { pr: { body: "Closes other/repo#12 and https://github.com/other/repo/issues/12" }, issues: { 12: ACCEPTED } }, true);

  await expect("branch in this repo", { pr: { head: { repo: { full_name: "tudor-city-ventures/tinfoilkit" } } } }, false);
  for (const a of ["OWNER", "MEMBER", "COLLABORATOR", "CONTRIBUTOR"]) await expect(a, { pr: { author_association: a } }, false);
  await expect("first-time contributor", { pr: { author_association: "FIRST_TIME_CONTRIBUTOR" } }, true);
  await expect("fork was deleted", { pr: { head: { repo: null } } }, true);

  await expect("maintainer reopened it", { action: "reopened", sender: { login: "travisbloom" } }, false);
  await expect("author reopened it, still no issue", { action: "reopened" }, true);
  await expect("author reopened it after linking one", { action: "reopened", pr: { body: "Closes #12" }, issues: { 12: ACCEPTED } }, false);

  // protected-files: outside pull requests that touch CI, reviews or release signing fail the check.
  async function files(names, pr = {}) {
    let failure = null;
    const list = names.map((n) => (Array.isArray(n) ? { filename: n[0], previous_filename: n[1] } : { filename: n }));
    const p = { number: 50, changed_files: list.length, head: { repo: { full_name: "drive-by/tinfoilkit" } }, ...pr };
    const github = { rest: { pulls: { listFiles: "listFiles" } }, paginate: async () => list };
    await guard(github, { repo: REPO, payload: { pull_request: p } }, { info() {}, setFailed(m) { failure = m; } });
    return failure;
  }
  check("an ordinary change passes", !(await files(["tools/kit.py", "kit.json", ".github/CONTRIBUTING.md", "site/index.html"])));
  for (const f of [".github/workflows/check.yml", ".github/workflows/new.yaml", ".github/CODEOWNERS", ".github/dependabot.yml",
                   ".github/release.sh", ".gitattributes", "tools/release-signers", "tools/pins.json"]) {
    const m = await files(["README.md", f]);
    check(`${f} fails it, by name`, !!m && m.includes(f));
  }
  check("renaming a workflow away fails it", !!(await files([["old.yml", ".github/workflows/check.yml"]])));
  check("a look-alike path passes", !(await files(["tests/.github/workflows/x.yml", "docs/CODEOWNERS.md", "tools/release-signers.md", "tests/pins.json"])));
  check("a branch in this repo skips it", !(await files([".github/workflows/check.yml"], { head: { repo: { full_name: "Tudor-City-Ventures/tinfoilkit" } } })));
  check("a deleted fork is still checked", !!(await files([".github/CODEOWNERS"], { head: { repo: null } })));
  check("more files than GitHub lists fails it", !!(await files(["README.md"], { changed_files: 3001 })));

  // forms: outside issues that didn't come through a form are closed.
  async function issue(opts = {}) {
    const calls = [];
    const i = { number: 60, body: "", author_association: "NONE", user: { login: "drive-by", type: "User" }, ...opts };
    const github = { rest: { issues: {
      createComment: async (a) => { calls.push("comment"); i.comment = a.body; },
      update: async (a) => calls.push(`${a.state} ${a.state_reason}`),
      addLabels: async (a) => calls.push(`label ${a.labels}`),
    } } };
    await forms(github, { repo: REPO, payload: { action: "opened", issue: i } }, { info() {}, warning() {} });
    return { closed: calls.includes("closed not_planned"), calls, comment: i.comment };
  }
  async function expectIssue(name, opts, closed) {
    const r = await issue(opts);
    check(`issue ${name}: expected ${closed ? "closed" : "left open"}, calls ${JSON.stringify(r.calls)}`, r.closed === closed);
    return r;
  }
  // What GitHub writes for an issue sent with a form: a "### label" heading per field, ticked boxes under checkboxes.
  function filled(yml) {
    const out = [];
    let boxes = false;
    for (const l of yml.split("\n")) {
      let m;
      if (/^  - type: /.test(l)) boxes = /checkboxes/.test(l);
      if ((m = l.match(/^      label: (.*)$/))) out.push(`### ${m[1]}`, "", boxes ? "" : "Something real", "");
      else if (boxes && (m = l.match(/^        - label: (.*)$/))) out.push(`- [X] ${m[1]}`);
    }
    return out.join("\n");
  }
  const templates = fs.readdirSync(TEMPLATES).filter((f) => f.endsWith(".yml") && f !== "config.yml");
  check("there are issue forms", templates.length >= 2);
  for (const f of templates) {
    const yml = fs.readFileSync(path.join(TEMPLATES, f), "utf8");
    await expectIssue(`sent with ${f}`, { body: filled(yml) }, false);
    check(`${f} labels new issues needs-triage`, /^labels: \[.*\bneeds-triage\b.*\]$/m.test(yml));
  }
  check("blank issues are off", /^blank_issues_enabled: false$/m.test(fs.readFileSync(path.join(TEMPLATES, "config.yml"), "utf8")));

  const r2 = await expectIssue("made with the API", { body: "Your app is broken, please fix ASAP!!" }, true);
  check("the comment points to the forms", /\/issues\/new\/choose/.test(r2.comment));
  check("it's labeled auto-closed", r2.calls.includes("label auto-closed"));
  await expectIssue("with no body", { body: null }, true);
  await expectIssue("with the heading but no ticked box", { body: "### Before you start\n\n- [ ] I searched" }, true);
  await expectIssue("from a first-time contributor", { author_association: "FIRST_TIME_CONTRIBUTOR" }, true);
  for (const a of ["OWNER", "MEMBER", "COLLABORATOR", "CONTRIBUTOR"]) await expectIssue(`from ${a}`, { author_association: a }, false);
  await expectIssue("from one of the repo's apps", { user: { login: "dependabot[bot]", type: "Bot" } }, false);

  console.log(failed ? `${failed} FAILED, ${passed} passed` : `ALL ${passed} PASSED`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.log(`FAIL: ${e.stack}`); process.exit(1); });
