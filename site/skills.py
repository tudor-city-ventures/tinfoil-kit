#!/usr/bin/env python3
"""Install the agent skills for working on the website: guides that Claude Code and other coding agents read.

They aren't kept in this repo. Each comes from its publisher's repo, at the commit pinned below, into
site/.claude/skills/, which git ignores and every run replaces:

    cd site && npm run skills          (or: python3 site/skills.py)

The copies keep only the Markdown and the license, and they never run a command when they load or pre-approve a tool.
To move a pin, run it with --latest, read the changes at the link it prints, then change the commit here.
Needs git.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

SOURCES = [   # publisher's repo, pinned commit, its license file, {skill: folder in the repo}
    ('vercel-labs/agent-skills', '5a37a6329fbad3666c3207392a6a7c0110e92efb', None,   # MIT, says its README
     {'vercel-react-best-practices': 'skills/react-best-practices', 'web-design-guidelines': 'skills/web-design-guidelines'}),
    ('shadcn-ui/ui', 'bfa64ff4d1cb7317d2403ecb176df6826d4caffc', 'LICENSE.md', {'shadcn': 'skills/shadcn'}),
    ('coreyhaines31/marketingskills', '5b2b400eec1e7e1cec76245a715d0b0d4fd2a9c1', 'LICENSE',
     {'ai-seo': 'skills/ai-seo', 'schema': 'skills/schema'}),
]
SKIP = {'AGENTS.md', 'README.md', '_template.md'}   # a compiled copy of the rules, notes for people, a template
DEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.claude', 'skills')


def tame(text):
    """A SKILL.md minus what would act on its own: allowed-tools and hooks in its header, and !`command` lines,
    which Claude Code runs as the skill loads."""
    lines, out, skipping = text.replace('\r\n', '\n').split('\n'), [], False
    header = len(lines) > 1 and lines[0] == '---' and '---' in lines[1:]
    end = lines.index('---', 1) if header else 0
    for i, line in enumerate(lines):
        if 0 < i < end:
            if re.match(r'(allowed-tools|hooks)\s*:', line):
                skipping = True
                continue
            if skipping and (line[:1] in (' ', '\t', '-') or not line.strip()):
                continue
            skipping = False
        out.append(line)
    return re.sub(r'!`([^`\n]+)`', r"`\1` (run it yourself if you need it: this copy doesn't run commands)", '\n'.join(out))


def git(*args, cwd=None):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def fetch(repo, commit, paths, into):
    """Just those paths of the repo at that commit: git checks every file against the commit's hash."""
    git('init', '-q', into)
    git('remote', 'add', 'origin', f'https://github.com/{repo}.git', cwd=into)
    git('sparse-checkout', 'set', '--no-cone', *('/' + p for p in paths), cwd=into)
    git('fetch', '-q', '--depth', '1', '--filter=blob:none', 'origin', commit, cwd=into)
    git('checkout', '-q', commit, cwd=into)


def install():
    new = DEST + '.new'
    shutil.rmtree(new, ignore_errors=True)
    for repo, commit, license, skills in SOURCES:
        with tempfile.TemporaryDirectory() as tmp:
            fetch(repo, commit, [p + '/' for p in skills.values()] + ([license] if license else []), tmp)
            for name, folder in skills.items():
                src, files = os.path.join(tmp, folder), 0
                for root, _, names in os.walk(src):
                    for f in names:
                        if not f.endswith('.md') or f in SKIP or os.path.islink(os.path.join(root, f)):
                            continue
                        rel = os.path.relpath(os.path.join(root, f), src)
                        with open(os.path.join(root, f), encoding='utf-8') as fh:
                            text = fh.read()
                        os.makedirs(os.path.dirname(os.path.join(new, name, rel)), exist_ok=True)
                        with open(os.path.join(new, name, rel), 'w', encoding='utf-8') as fh:
                            fh.write(tame(text) if rel == 'SKILL.md' else text)
                        files += 1
                if not os.path.isfile(os.path.join(new, name, 'SKILL.md')):
                    sys.exit(f'{repo} has no SKILL.md in {folder} at {commit[:12]}')
                if license:
                    shutil.copyfile(os.path.join(tmp, license), os.path.join(new, name, license))
                print(f'{name}: {files} files from {repo} at {commit[:12]}')
    shutil.rmtree(DEST, ignore_errors=True)   # the old copy goes only once the new one is complete
    os.rename(new, DEST)
    print(f'Installed in {os.path.relpath(DEST)}')


def latest():
    for repo, commit, _, _ in SOURCES:
        head = git('ls-remote', f'https://github.com/{repo}.git', 'HEAD').split()[0]
        if head == commit:
            print(f'{repo}: up to date')
        else:
            print(f'{repo}: newer commit {head}. Read the changes first: https://github.com/{repo}/compare/{commit}...{head}')


if __name__ == '__main__':
    if not shutil.which('git'):
        sys.exit('Installing the agent skills needs git.')
    try:
        latest() if '--latest' in sys.argv[1:] else install()
    except subprocess.CalledProcessError as e:
        sys.exit(f'git {e.cmd[1]} failed: {(e.stderr or "").strip()}\nNothing was changed.')
