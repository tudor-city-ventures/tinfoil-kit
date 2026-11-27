#!/usr/bin/env python3
"""Install the agent skills for working on the phone app: Expo's, Callstack's and Vercel's guides for Expo and React
Native, which Claude Code and other coding agents read.

The same installer as the website's (site/skills.py), with these pins, into mobile/.claude/skills/, which git ignores:

    cd mobile && npm run skills          (or: python3 mobile/skills.py; --latest checks the pins)
"""

import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("site_skills", os.path.join(HERE, "..", "site", "skills.py"))
skills = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skills)

EXPO = "plugins/expo/skills/"
skills.SOURCES = [  # publisher's repo, pinned commit, its license file, {skill: folder in the repo}
    (
        "expo/skills",
        "8f2b6c0c65533e695243aa401eaa1cb6f1fe86c2",
        "LICENSE",
        {
            name: EXPO + name
            for name in (
                "expo-overview",
                "expo-project-structure",
                "expo-router",
                "expo-native-ui",
                "expo-ui",
                "expo-design-system",
                "expo-data-fetching",
                "expo-module",
                "expo-dev-client",
                "expo-upgrade",
                "eas-app-stores",
            )
        },
    ),
    (
        "callstackincubator/agent-skills",
        "59e9d17446a248b21d86f078fcd0bd2d36db1ca4",
        "LICENSE",
        {
            "react-native-best-practices": "skills/react-native-best-practices",
            "github-actions": "skills/github-actions",
        },
    ),
    (
        "callstack/react-native-testing-library",
        "5a05c26926077b507b9dcca235063432a23068e1",
        "LICENSE",
        {"react-native-testing": "skills/react-native-testing"},
    ),
    (
        "vercel-labs/agent-skills",
        "5a37a6329fbad3666c3207392a6a7c0110e92efb",
        None,  # MIT, says its README
        {"vercel-react-native-skills": "skills/react-native-skills"},
    ),
]
skills.DEST = os.path.join(HERE, ".claude", "skills")

if __name__ == "__main__":
    try:
        skills.latest() if "--latest" in sys.argv[1:] else skills.install()
    except subprocess.CalledProcessError as e:
        sys.exit(f"git {e.cmd[1]} failed: {(e.stderr or '').strip()}\nNothing was changed.")
