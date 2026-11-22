# Contributing to Tinfoil Kit

Thanks for helping. One person maintains the kit, so the process keeps their time on changes it needs.

## How a change gets in

1. **Open an issue first,** with one of the forms. Search the open and closed issues before you do.
2. **Wait for the `accepted` label.** It means the maintainer wants the change and will review a pull request for it. Talk it through on the issue.
3. **Open one pull request for it** that says `Closes #123` in its description.
4. **Show it works.** Run the checks [AGENTS.md](../AGENTS.md#verify) lists for what you changed and paste the output. Changes to the page or the website come with screenshots.

A bot closes issues filed without a form (with `gh` or the API, say) and pull requests that don't link an accepted issue. People who've had a pull request merged here skip both. Anyone without write access can have two pull requests open at a time. A pull request that changes the workflows, CODEOWNERS, Dependabot's settings, `.gitattributes`, the release key or how the Mac app is signed fails a check, and only the maintainer can merge it.

## Good places to start

- **Library sources.** Suggest one with the idea form, with its exact name from `./kit search WORDS`. AGENTS.md has [the steps](../AGENTS.md#adding-or-replacing-a-library-source).
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

[AGENTS.md](../AGENTS.md) has them, for people and agents alike: Go's standard library, bash 3.2, no symlinks, every download source overridable for the tests. Skip its Workflow section, which is for the maintainers.

## Also

- Report security problems privately, as [SECURITY.md](SECURITY.md) says.
- Everyone here follows the [code of conduct](CODE_OF_CONDUCT.md).
