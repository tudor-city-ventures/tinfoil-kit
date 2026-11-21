// Runs the github-script in .github/workflows/pr-gate.yml against fake pull requests and a fake GitHub API.
// Usage: node tests/pr_gate_test.js
const fs = require("fs");
const path = require("path");

const yml = fs.readFileSync(path.join(__dirname, "..", ".github", "workflows", "pr-gate.yml"), "utf8").split("\n");
const at = yml.findIndex((l) => /^\s+script: \|\s*$/.test(l));
const indent = yml[at + 1].match(/^ */)[0].length;
const body = [];
for (const l of yml.slice(at + 1)) {
  if (l.trim() && l.match(/^ */)[0].length < indent) break;
  body.push(l.slice(indent));
}
const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;
const gate = new AsyncFunction("github", "context", "core", body.join("\n"));

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

  console.log(failed ? `${failed} FAILED, ${passed} passed` : `ALL ${passed} PASSED`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.log(`FAIL: ${e.stack}`); process.exit(1); });
