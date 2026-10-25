"""Every SKILL.md has valid frontmatter, and every example command in it is
accepted by the real command line (so the skills never teach a wrong flag)."""

import contextlib
import io
import json
import os
import re
import shlex
import unittest

from _base import ROOT

from indtrader.cli.parser import build_parser

SKILLS = os.path.join(ROOT, "skills")


def skill_files():
    for name in sorted(os.listdir(SKILLS)):
        p = os.path.join(SKILLS, name, "SKILL.md")
        if os.path.exists(p):
            yield name, p


class TestSkills(unittest.TestCase):
    def test_twenty_two_skills(self):
        self.assertEqual(len(list(skill_files())), 22)

    def test_frontmatter(self):
        for name, p in skill_files():
            with open(p, encoding="utf-8") as f:
                text = f.read()
            m = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", text)
            self.assertTrue(m, name)
            self.assertEqual(m.group(1), name)
            desc = json.loads(m.group(2))
            self.assertIn("Use when", desc, name)
            self.assertLess(len(desc), 1024, name)

    def test_example_commands_parse(self):
        parser = build_parser()
        seen = 0
        for name, p in skill_files():
            with open(p, encoding="utf-8") as f:
                text = f.read()
            for line in re.findall(r'python "Indian Trader Skill/it.py" ([^\n`]+)', text):
                cmd = line.split("  #")[0].strip()
                if cmd.endswith("..."):
                    continue
                argv = shlex.split(cmd)
                with contextlib.redirect_stderr(io.StringIO()):
                    try:
                        parser.parse_args(argv)
                    except SystemExit:
                        self.fail("%s: example does not parse: %s" % (name, cmd))
                seen += 1
        self.assertGreater(seen, 50)


class TestDocumentation(unittest.TestCase):
    """Every command shown in the README and the guides parses."""

    def test_doc_commands_parse(self):
        parser = build_parser()
        docs = [os.path.join(ROOT, "README.md")] + [os.path.join(ROOT, "docs", f) for f in os.listdir(os.path.join(ROOT, "docs"))
                                                    if f.endswith(".md")]
        seen = 0
        for path in docs:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for line in re.findall(r'python (?:"Indian Trader Skill/it.py"|it\.py) ([^\n`|]+)', text):
                cmd = re.split(r"\s+#", line)[0].strip()
                if "<" in cmd or cmd.endswith("...") or cmd.startswith("-h"):
                    continue
                with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    try:
                        parser.parse_args(shlex.split(cmd))
                    except SystemExit:
                        self.fail("%s: command does not parse: %s" % (os.path.basename(path), cmd))
                seen += 1
        self.assertGreater(seen, 15)


AGENTS = os.path.join(ROOT, "agents")


class TestClaudeAgents(unittest.TestCase):
    """Every Claude agent definition has valid frontmatter and only teaches commands that parse."""

    def files(self):
        return sorted((f[:-3], os.path.join(AGENTS, f)) for f in os.listdir(AGENTS) if f.endswith(".md"))

    def test_eleven_claude_agents(self):
        self.assertEqual(len(self.files()), 11)

    def test_frontmatter_and_commands(self):
        parser = build_parser()
        for name, path in self.files():
            with open(path, encoding="utf-8") as f:
                text = f.read().replace("\r\n", "\n")
            m = re.match(r"---\nname: (.+)\ndescription: (.+)\ntools: (.+)\n---\n", text)
            self.assertTrue(m, name)
            self.assertEqual(m.group(1), name)
            self.assertIn("Use when", json.loads(m.group(2)), name)
            for line in re.findall(r'python "Indian Trader Skill/it.py" ([^\n`]+)', text):
                cmd = line.split("  #")[0].strip()
                if "<" in cmd or cmd.endswith("..."):
                    continue
                with contextlib.redirect_stderr(io.StringIO()):
                    try:
                        parser.parse_args(shlex.split(cmd))
                    except SystemExit:
                        self.fail("%s: command does not parse: %s" % (name, cmd))

    def test_installed_copies_match(self):
        installed = os.path.join(os.path.dirname(ROOT), ".claude", "agents")
        if not os.path.isdir(installed):
            self.skipTest("no .claude/agents next to the project")
        for name, path in self.files():
            with open(path, encoding="utf-8") as a, open(os.path.join(installed, name + ".md"), encoding="utf-8") as b:
                self.assertEqual(a.read().replace("\r\n", "\n"), b.read().replace("\r\n", "\n"), name)


if __name__ == "__main__":
    unittest.main()
