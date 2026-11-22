# Contributing to Tinfoil Kit

Thanks for helping. One person maintains the kit, so the process keeps their time on changes it needs.

## How a change gets in

1. **Open an issue first,** with one of the forms. Search the open and closed issues before you do. "Something broke" and "Mistake on the website or in the guide" label it `bug`; "New feature or change" labels it `feature`.
2. **Show a feature.** Put a screenshot, mockup, sketch or short screen recording of what someone would see in "What it looks like", and say in a few plain sentences, in your own words, what changes and why it matters when the internet is down. The maintainer reads every proposal: one padded with AI-written filler is closed, and so is one with no picture or video, until you edit one in.
3. **Wait for the `accepted` label.** It means the maintainer wants the change and will review a pull request for it. Talk it through on the issue.
4. **Open one pull request for it** that says `Closes #123` in its description. It takes the issue's label, `bug` or `feature`. A feature's description shows the change working, in screenshots or a short screen recording, or a check fails until it does.
5. **Show it works.** Run the checks [AGENTS.md](../AGENTS.md#verify) lists for what you changed and paste the output. Changes to the page or the website come with screenshots.

A bot closes issues filed without a form (with `gh` or the API, say), feature proposals with no picture or video, and pull requests that don't link an accepted issue. People who've had a pull request merged here needn't use a form or link an accepted issue, but the rest applies. Anyone without write access can have two pull requests open at a time. A pull request that changes the workflows, CODEOWNERS, Dependabot's settings, `.gitattributes`, the release key or how the Mac app is signed fails a check, and only the maintainer can merge it.

## Setting up

You need Go 1.21 or newer (`tools/tinfoilkit/build.sh` then fetches the exact version it pins), Node 22, Python 3.9 or newer and curl. The quick gate also runs shellcheck and ruff 0.17.5 (`pip install ruff==0.17.5`) when they're installed; CI always does.

```bash
git clone https://github.com/tudor-city-ventures/tinfoil-kit.git && cd tinfoil-kit
npm ci --ignore-scripts   # Prettier, ESLint and axe-core, for the checks: nothing in the kit uses them
tests/check.sh            # the quick gate: builds the kit's program, then runs the quick tests against mocks
```

A checkout is a kit too: `./kit` builds its program the first time, and `downloads/` and `data/` are git-ignored. But a real `./kit sync` downloads hundreds of GB, so the tests use mocks of every download source instead. To work on the website: `cd site && npm ci --ignore-scripts && npm run dev`.

## Where things are

The kit's program is in `tools/tinfoilkit/` (Go) and its page in `tools/portal.html`; `kit.json` lists what a kit downloads; the double-click scripts (`SETUP.command` and the rest) sit at the top; `mac/` is the Mac app, `site/` the website and `tests/` the tests. [AGENTS.md](../AGENTS.md#map) has the full map, and [docs/DESIGN.md](../docs/DESIGN.md) how it all works and why.

## Good places to start

- **Library sources.** Suggest one with the feature form, with its exact name from `./kit search WORDS` and a screenshot of it. AGENTS.md has [the steps](../AGENTS.md#adding-or-replacing-a-library-source).
- **Reports from real computers.** The tests run against mocks, so a bug report from a real Mac or PC, with the output, is the most useful thing you can send.
- Issues labeled `good first issue`.

## AI tools

They're welcome: this repo is built with them, and AGENTS.md is written for them. The person who opens an issue or pull request answers for it:

- Read and understand every line before you send it, and answer review questions yourself.
- Say in the pull request which tools you used and for what.
- Don't let an agent open issues or pull requests on its own, and don't post AI text you haven't checked. Accounts that do get blocked.

## Sign-off

Sign off every commit with `git commit -s`. It adds a `Signed-off-by: Your Name <you@example.com>` line, which certifies the [Developer Certificate of Origin](https://developercertificate.org/): you wrote the change, or otherwise have the right to submit it under the [MIT license](../LICENSE). Only a person can sign off, never an AI.

A check fails on pull requests with unsigned commits. Fix them with `git commit --amend -s --no-edit` (or `git rebase --signoff main` for several commits) and force-push.

## Code rules

[AGENTS.md](../AGENTS.md#rules) has them, for people and agents alike: Go's standard library, bash 3.2, no symlinks, every download source overridable for the tests. Its Workflow section is for the maintainer's own agents; you follow this file instead.

## Also

- Report security problems privately, as [SECURITY.md](SECURITY.md) says.
- Everyone here follows the [code of conduct](CODE_OF_CONDUCT.md).
