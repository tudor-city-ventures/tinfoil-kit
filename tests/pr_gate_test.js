// Runs the github-scripts in .github/workflows/pr-gate.yml against fake pull requests and issues and a fake GitHub
// API, and the issue check against what GitHub writes for each form in .github/ISSUE_TEMPLATE.
// Usage: node tests/pr_gate_test.js
const fs = require("fs");
const path = require("path");

const yml = fs.readFileSync(path.join(__dirname, "..", ".github", "workflows", "pr-gate.yml"), "utf8").split("\n");
const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;
function script(job) {
  // the `script: |` block of that job
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

const REPO = { owner: "tudor-city-ventures", repo: "tinfoil-kit" };
const ACCEPTED = { labels: [{ name: "accepted" }] };
const BUG = { labels: [{ name: "accepted" }, { name: "bug" }] };
const FEATURE = { labels: [{ name: "feature" }, { name: "accepted" }] };
// What GitHub writes when someone drags a picture or a video into a description
const SCREENSHOT = "![the Map tab](https://github.com/user-attachments/assets/4e6b1c0a-8f1d-4c3e-9a51-2f7d0c9e1b23)";
const VIDEO = "https://github.com/user-attachments/assets/9b0f3d2e-1c4a-4e8b-b7a6-5d2c1e0f9a87";
// What GitHub says someone may do in this repo: admin, write, read or none. null: the request fails.
function repos(permission) {
  return {
    getCollaboratorPermissionLevel: async ({ owner, repo, username }) => {
      if (owner !== REPO.owner || repo !== REPO.repo) throw Object.assign(new Error("Not Found"), { status: 404 });
      if (permission === null) throw Object.assign(new Error("Forbidden"), { status: 403 });
      return { data: { permission, user: { login: username } } };
    },
  };
}

async function run({ pr = {}, issues = {}, action = "opened", sender, permission = "read" }) {
  const calls = [];
  const p = {
    number: 50,
    title: "Add a thing",
    body: "",
    author_association: "NONE",
    user: { login: "drive-by" },
    head: { repo: { full_name: "drive-by/tinfoil-kit" } },
    ...pr,
  };
  const github = {
    rest: {
      issues: {
        get: async ({ issue_number }) => {
          if (!issues[issue_number]) throw Object.assign(new Error("Not Found"), { status: 404 });
          return { data: { number: issue_number, state: "open", labels: [], ...issues[issue_number] } };
        },
        createComment: async (a) => {
          calls.push("comment");
          p.comment = a.body;
        },
        addLabels: async (a) => calls.push(`label ${a.labels}`),
      },
      pulls: { update: async (a) => calls.push(a.state) },
      repos: repos(permission),
    },
  };
  const context = { repo: REPO, payload: { action, pull_request: p, sender: sender || p.user } };
  let failure = null;
  await gate(github, context, {
    info() {},
    warning() {},
    setFailed(m) {
      failure = m;
    },
  });
  return { closed: calls.includes("closed"), calls, comment: p.comment, failure };
}

let passed = 0,
  failed = 0;
function check(name, ok) {
  if (ok) passed++;
  else {
    failed++;
    console.log(`FAIL: ${name}`);
  }
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
  await expect(
    "mentions it mid-sentence",
    { pr: { body: "This does what (#12) asks." }, issues: { 12: ACCEPTED } },
    false,
  );
  await expect("mentions it in the title", { pr: { title: "Fix the thing in #12" }, issues: { 12: ACCEPTED } }, false);
  await expect(
    "links its URL",
    { pr: { body: "Fixes https://github.com/Tudor-City-Ventures/tinfoil-kit/issues/12" }, issues: { 12: ACCEPTED } },
    false,
  );
  await expect(
    "owner/repo#12",
    { pr: { body: "Resolves tudor-city-ventures/tinfoil-kit#12" }, issues: { 12: ACCEPTED } },
    false,
  );
  await expect(
    "one of several references is accepted",
    { pr: { body: "See #3 and #12" }, issues: { 3: {}, 12: ACCEPTED } },
    false,
  );

  await expect(
    "issue isn't accepted",
    { pr: { body: "Closes #13" }, issues: { 13: { labels: [{ name: "enhancement" }] } } },
    true,
  );
  await expect(
    "accepted issue is closed",
    { pr: { body: "Closes #12" }, issues: { 12: { ...ACCEPTED, state: "closed" } } },
    true,
  );
  await expect(
    "number is a pull request",
    { pr: { body: "Closes #12" }, issues: { 12: { ...ACCEPTED, pull_request: {} } } },
    true,
  );
  await expect("number doesn't exist", { pr: { body: "Closes #999" } }, true);
  await expect(
    "another repo's issue",
    { pr: { body: "Closes other/repo#12 and https://github.com/other/repo/issues/12" }, issues: { 12: ACCEPTED } },
    true,
  );

  await expect(
    "branch in this repo",
    { pr: { head: { repo: { full_name: "tudor-city-ventures/tinfoil-kit" } } } },
    false,
  );
  for (const a of ["OWNER", "MEMBER", "COLLABORATOR", "CONTRIBUTOR"])
    await expect(a, { pr: { author_association: a } }, false);
  let t = await expect(
    "a past contributor's feature",
    { pr: { author_association: "CONTRIBUTOR", body: "Closes #12" }, issues: { 12: FEATURE } },
    false,
  );
  check(
    "a past contributor's feature is labeled, and needs pictures too",
    t.calls.includes("label feature") && !!t.failure,
  );
  t = await expect(
    "a maintainer's feature from a fork",
    { pr: { author_association: "MEMBER", body: "Closes #12" }, issues: { 12: FEATURE } },
    false,
  );
  check("a maintainer's pull request is left alone", !t.calls.length && !t.failure);
  // An event can say NONE for a maintainer (a private org membership), so write access to the repo counts too.
  for (const permission of ["admin", "write"]) {
    t = await expect(
      `a fork's pull request from someone with ${permission} access`,
      { pr: { body: "Closes #12" }, issues: { 12: FEATURE }, permission },
      false,
    );
    check(`${permission} access is left alone like a maintainer`, !t.calls.length && !t.failure);
  }
  await expect("read access isn't enough", { permission: "read" }, true);
  await expect("no access at all", { permission: "none" }, true);
  await expect("GitHub won't say what they may do", { permission: null }, true);
  await expect("first-time contributor", { pr: { author_association: "FIRST_TIME_CONTRIBUTOR" } }, true);
  await expect("fork was deleted", { pr: { head: { repo: null } } }, true);

  await expect("maintainer reopened it", { action: "reopened", sender: { login: "travisbloom" } }, false);
  await expect("author reopened it, still no issue", { action: "reopened" }, true);
  await expect(
    "author reopened it after linking one",
    { action: "reopened", pr: { body: "Closes #12" }, issues: { 12: ACCEPTED } },
    false,
  );
  for (const action of ["edited", "synchronize"]) {
    const r = await expect(`${action}, no issue linked`, { action }, false);
    check(`${action}, no issue linked: no comment either`, !r.calls.includes("comment"));
  }

  // The accepted issue's kind, bug or feature, goes on the pull request, and a feature shows itself working.
  let k = await expect("a bug fix", { pr: { body: "Closes #12" }, issues: { 12: BUG } }, false);
  check("a bug fix is labeled bug, and passes", k.calls.includes("label bug") && !k.failure);
  k = await expect(
    "a feature with a screenshot",
    { pr: { body: `Closes #12\n\n${SCREENSHOT}` }, issues: { 12: FEATURE } },
    false,
  );
  check("a feature is labeled feature, and passes with a screenshot", k.calls.includes("label feature") && !k.failure);
  k = await expect(
    "a feature without pictures",
    { pr: { body: "Closes #12\n\nIt adds a button." }, issues: { 12: FEATURE } },
    false,
  );
  check(
    "a feature without pictures stays open, labeled, and fails the check with a comment saying what to add",
    k.calls.includes("label feature") && /screen recording/.test(k.failure) && /drag them in/.test(k.comment),
  );
  k = await expect(
    "a feature edited, still without pictures",
    { action: "edited", pr: { body: "Closes #12" }, issues: { 12: FEATURE } },
    false,
  );
  check(
    "an edit without pictures fails the check again, with no second comment",
    !!k.failure && !k.calls.includes("comment"),
  );
  for (const [what, body] of [
    ["a video uploaded to GitHub", `Closes #12\n\n${VIDEO}\n`],
    ["an HTML image", 'Closes #12 <img width="600" alt="map" src="https://github.com/user-attachments/assets/1a2b">'],
    ["a link to a video", "Closes #12, demo: https://www.loom.com/share/0123abcd"],
    ["a YouTube link", "Closes #12\nhttps://youtu.be/dQw4w9WgXcQ"],
    ["a link to an image file", "Closes #12, see https://example.org/shots/map.png"],
  ]) {
    k = await expect(`a feature with ${what}`, { pr: { body }, issues: { 12: FEATURE } }, false);
    check(`a feature with ${what} passes`, !k.failure);
  }
  k = await expect(
    "a feature whose only picture is in the template's comment",
    { pr: { body: `Closes #12\n<!-- like this: ${SCREENSHOT} -->` }, issues: { 12: FEATURE } },
    false,
  );
  check("a picture inside a comment doesn't count", !!k.failure);
  k = await expect(
    "already labeled",
    { pr: { body: `Closes #12 ${SCREENSHOT}`, labels: [{ name: "feature" }] }, issues: { 12: FEATURE } },
    false,
  );
  check("a label it already has isn't added again", !k.calls.some((c) => c.startsWith("label")));
  k = await expect(
    "an accepted issue of neither kind",
    { pr: { body: "Closes #12" }, issues: { 12: ACCEPTED } },
    false,
  );
  check("an accepted issue of neither kind adds no label and passes", !k.calls.length && !k.failure);

  // protected-files: outside pull requests that touch CI, reviews or release signing fail the check.
  async function files(names, pr = {}) {
    let failure = null;
    const list = names.map((n) => (Array.isArray(n) ? { filename: n[0], previous_filename: n[1] } : { filename: n }));
    const p = { number: 50, changed_files: list.length, head: { repo: { full_name: "drive-by/tinfoil-kit" } }, ...pr };
    const github = { rest: { pulls: { listFiles: "listFiles" } }, paginate: async () => list };
    await guard(
      github,
      { repo: REPO, payload: { pull_request: p } },
      {
        info() {},
        setFailed(m) {
          failure = m;
        },
      },
    );
    return failure;
  }
  check(
    "an ordinary change passes",
    !(await files(["tools/tinfoilkit/sync.go", "kit.json", ".github/CONTRIBUTING.md", "site/app/page.jsx"])),
  );
  for (const f of [
    ".github/workflows/check.yml",
    ".github/workflows/new.yaml",
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
    ".github/release.sh",
    ".gitattributes",
    "tools/release-signers",
    "tools/pins.json",
    "mac/build.sh",
  ]) {
    const m = await files(["README.md", f]);
    check(`${f} fails it, by name`, !!m && m.includes(f));
  }
  check("renaming a workflow away fails it", !!(await files([["old.yml", ".github/workflows/check.yml"]])));
  check(
    "a look-alike path passes",
    !(await files([
      "tests/.github/workflows/x.yml",
      "docs/CODEOWNERS.md",
      "tools/release-signers.md",
      "tests/pins.json",
      "mac/app.sh",
    ])),
  );
  check(
    "a branch in this repo skips it",
    !(await files([".github/workflows/check.yml"], {
      head: { repo: { full_name: "Tudor-City-Ventures/tinfoil-kit" } },
    })),
  );
  check("a deleted fork is still checked", !!(await files([".github/CODEOWNERS"], { head: { repo: null } })));
  check("more files than GitHub lists fails it", !!(await files(["README.md"], { changed_files: 3001 })));

  // forms: outside issues that didn't come through a form are closed.
  async function issue({ action = "opened", permission = "read", ...opts } = {}) {
    const calls = [];
    const i = {
      number: 60,
      body: "",
      state: "open",
      labels: [],
      author_association: "NONE",
      user: { login: "drive-by", type: "User" },
      ...opts,
    };
    const github = {
      rest: {
        issues: {
          createComment: async (a) => {
            calls.push("comment");
            i.comment = a.body;
          },
          update: async (a) => calls.push(a.state_reason ? `${a.state} ${a.state_reason}` : a.state),
          addLabels: async (a) => calls.push(`label ${a.labels}`),
          removeLabel: async (a) => calls.push(`unlabel ${a.name}`),
        },
        repos: repos(permission),
      },
    };
    await forms(github, { repo: REPO, payload: { action, issue: i } }, { info() {}, warning() {} });
    return { closed: calls.includes("closed not_planned"), calls, comment: i.comment };
  }
  async function expectIssue(name, opts, closed) {
    const r = await issue(opts);
    check(
      `issue ${name}: expected ${closed ? "closed" : "left open"}, calls ${JSON.stringify(r.calls)}`,
      r.closed === closed,
    );
    return r;
  }
  // What GitHub writes for an issue sent with a form: a "### label" heading per field, ticked boxes under checkboxes.
  function filled(yml, answer = "Something real") {
    const out = [];
    let boxes = false;
    for (const l of yml.split("\n")) {
      let m;
      if (/^ {2}- type: /.test(l)) boxes = /checkboxes/.test(l);
      if ((m = l.match(/^ {6}label: (.*)$/))) out.push(`### ${m[1]}`, "", boxes ? "" : answer, "");
      else if (boxes && (m = l.match(/^ {8}- label: (.*)$/))) out.push(`- [X] ${m[1]}`);
    }
    return out.join("\n");
  }
  const templates = fs.readdirSync(TEMPLATES).filter((f) => f.endsWith(".yml") && f !== "config.yml");
  check("there are issue forms", templates.length >= 3);
  const created = new Set(
    [
      ...fs
        .readFileSync(path.join(__dirname, "..", ".github", "workflows", "pr-gate.yml"), "utf8")
        .matchAll(/gh label create (\S+)/g),
    ].map((m) => m[1]),
  );
  for (const n of ["accepted", "auto-closed", "needs-triage", "needs-pictures", "bug", "feature"])
    check(`the labels job makes the ${n} label`, created.has(n));
  let features = 0;
  for (const f of templates) {
    const yml = fs.readFileSync(path.join(TEMPLATES, f), "utf8");
    const labels = (yml.match(/^labels: \[(.*)\]$/m) || ["", ""])[1].split(",").map((l) => l.trim());
    check(`${f} labels new issues needs-triage`, labels.includes("needs-triage"));
    check(`${f} labels new issues bug or feature`, labels.filter((l) => l === "bug" || l === "feature").length === 1);
    check(
      `${f}'s labels all exist`,
      labels.every((l) => created.has(l)),
    );
    await expectIssue(
      `sent with ${f}, with a screenshot`,
      { body: filled(yml, `Something real\n\n${SCREENSHOT}`) },
      false,
    );
    // A feature proposal needs a picture or a video; the other forms don't.
    const feature = labels.includes("feature");
    features += feature;
    check(`${f}: a feature asks for a picture`, !feature || /^ {6}label: What it looks like$/m.test(yml));
    const r = await expectIssue(`sent with ${f}, with no picture`, { body: filled(yml) }, feature);
    if (feature) {
      check(
        "a feature with no picture is labeled needs-pictures, and told how to reopen it",
        r.calls.includes("label needs-pictures,auto-closed") &&
          /What it looks like/.test(r.comment) &&
          /reopens/.test(r.comment),
      );
      const closed = {
        action: "edited",
        state: "closed",
        labels: [{ name: "needs-pictures" }, { name: "auto-closed" }],
      };
      let e = await issue({ ...closed, body: filled(yml, `Something real\n\n${SCREENSHOT}`) });
      check(
        "a picture edited in reopens it and takes the labels off",
        e.calls.includes("open") &&
          e.calls.includes("unlabel needs-pictures") &&
          e.calls.includes("unlabel auto-closed"),
      );
      e = await issue({ ...closed, body: filled(yml) });
      check("an edit with still no picture leaves it closed", !e.calls.length);
      e = await issue({ ...closed, labels: [{ name: "auto-closed" }], body: filled(yml, SCREENSHOT) });
      check("an issue closed for another reason stays closed when edited", !e.calls.length);
      e = await issue({ ...closed, author_association: "OWNER", body: filled(yml, SCREENSHOT) });
      check("the maintainer's edits change nothing", !e.calls.length);
    }
  }
  check("one form is for features", features === 1);
  await expectIssue(
    "labeled feature, with no picture",
    { body: "### Before you start\n\n- [X] I searched\n\n### Idea\n\nA button", labels: [{ name: "feature" }] },
    true,
  );
  check(
    "blank issues are off",
    /^blank_issues_enabled: false$/m.test(fs.readFileSync(path.join(TEMPLATES, "config.yml"), "utf8")),
  );

  const r2 = await expectIssue("made with the API", { body: "Your app is broken, please fix ASAP!!" }, true);
  check("the comment points to the forms", /\/issues\/new\/choose/.test(r2.comment));
  check("it's labeled auto-closed", r2.calls.includes("label auto-closed"));
  await expectIssue("with no body", { body: null }, true);
  await expectIssue("with the heading but no ticked box", { body: "### Before you start\n\n- [ ] I searched" }, true);
  await expectIssue("from a first-time contributor", { author_association: "FIRST_TIME_CONTRIBUTOR" }, true);
  for (const a of ["OWNER", "MEMBER", "COLLABORATOR", "CONTRIBUTOR"])
    await expectIssue(`from ${a}`, { author_association: a }, false);
  const feature = filled(fs.readFileSync(path.join(TEMPLATES, "feature.yml"), "utf8"));
  await expectIssue(
    "a past contributor's feature with no picture",
    { author_association: "CONTRIBUTOR", body: feature },
    true,
  );
  await expectIssue("the maintainer's feature with no picture", { author_association: "OWNER", body: feature }, false);
  // An event can say NONE for a maintainer (a private org membership), so write access to the repo counts too.
  for (const permission of ["admin", "write"]) {
    const m = await expectIssue(
      `made with the API by someone with ${permission} access`,
      { body: "Help wanted: Windows setup", labels: [{ name: "feature" }], permission },
      false,
    );
    check(`${permission} access is left alone like a maintainer`, !m.calls.length);
  }
  await expectIssue("made with the API, with read access", { body: "Fix this", permission: "read" }, true);
  await expectIssue("made with the API, with no access", { body: "Fix this", permission: "none" }, true);
  await expectIssue("made with the API, and GitHub won't say", { body: "Fix this", permission: null }, true);
  await expectIssue(
    "not from a form, but with a feature's heading",
    { body: "### What it looks like\n\nNothing yet" },
    true,
  );
  check(
    "an issue not from a form is closed for that, not for its pictures",
    !(await issue({ body: "### What it looks like\n\nNothing yet" })).calls.includes(
      "label needs-pictures,auto-closed",
    ),
  );
  await expectIssue("from one of the repo's apps", { user: { login: "dependabot[bot]", type: "Bot" } }, false);

  const lists = [...yml.join("\n").matchAll(/const SHOWS = \[[\s\S]*?\];/g)].map((m) => m[0].replace(/^\s+/gm, ""));
  check("the gate and forms jobs look for pictures the same way", lists.length === 2 && lists[0] === lists[1]);

  console.log(failed ? `${failed} FAILED, ${passed} passed` : `ALL ${passed} PASSED`);
  process.exit(failed ? 1 : 0);
})().catch((e) => {
  console.log(`FAIL: ${e.stack}`);
  process.exit(1);
});
