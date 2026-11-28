"""Conservative CI routing. Unknown/shared changes and policy edits run everything."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

ONLINE = {
    "cloud/deploy/Dockerfile.online-auth",
    "cloud/deploy/Dockerfile.online-auth.dockerignore",
    "cloud/deploy/compose.online-auth.yaml",
    "cloud/deploy/requirements-online-auth.txt",
    "cloud/deploy/online-auth-smoke.sh",
}
SHA = re.compile(r"[0-9a-f]{40}")

def classify(paths):
    """Only positive allowlists are eligible for reduced suites."""
    paths = set(paths)
    if not paths:
        return "full"
    def docs(p):
        return p.startswith("docs/") and p.endswith(".md")
    def online(p):
        return p in ONLINE or (p.startswith("cloud/deploy/online_") and
            p.endswith((".py", ".sql"))) or (p.startswith("tests/test_cloud_online_") and p.endswith(".py"))
    def cloud(p):
        return (p.startswith("cloud/") or p.startswith("tests/test_cloud_")
                or p.startswith("tests/cloud_") or p.startswith("tests/fixtures/cloud_cv_"))
    if all(docs(p) for p in paths):
        return "docs"
    if all(docs(p) or online(p) for p in paths):
        return "online"
    if all(docs(p) or cloud(p) for p in paths):
        return "cloud"
    return "full"

def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)

def event_scope(event_name, event):
    try:
        if event_name == "pull_request":
            base = event["pull_request"]["base"]["sha"]
            head = event["pull_request"]["head"]["sha"]
        elif event_name == "push" and event.get("ref") == "refs/heads/master" and not event.get("forced"):
            base, head = event["before"], event["after"]
        else:
            return "full"
        if not all(isinstance(s, str) and SHA.fullmatch(s) and s != "0"*40 for s in (base, head)):
            return "full"
        if event_name == "pull_request":
            base = git("merge-base", base, head).decode("ascii").strip()
            if not SHA.fullmatch(base):
                return "full"
        else:
            git("merge-base", "--is-ancestor", base, head)
        # No rename detection: both paths of a move are classified. Deletions
        # of code conservatively run all suites.
        entries = git("diff", "--name-status", "--no-renames", "-z", base, head, "--").split(b"\0")
        if entries[-1] != b"" or len(entries) % 2 != 1:
            return "full"
        paths=[]
        for status, raw in zip(entries[:-1:2], entries[1:-1:2]):
            path=raw.decode("utf-8",errors="strict")
            if status not in (b"A",b"M") and not (status==b"D" and path.startswith("docs/") and path.endswith(".md")):
                return "full"
            paths.append(path)
        return classify(paths)
    except (KeyError, OSError, UnicodeError, ValueError, TypeError, subprocess.CalledProcessError):
        return "full"

class ScopeTests(unittest.TestCase):
    def test_scopes(self):
        cases = [
            (["docs/CLOUD_GUIDE.md"],"docs"),
            (["cloud/deploy/online_init.py","docs/CLOUD_GUIDE.md"],"online"),
            (["cloud/deploy/compose.online-auth.yaml","tests/test_cloud_online_auth.py"],"online"),
            (["cloud/auth.py","cloud/deploy/online_init.py"],"cloud"),
            (["cloud/frontend/bootstrap.js","tests/test_cloud_history_ui.js"],"cloud"),
            (["cloud/deploy/interactive.py"],"cloud"),
            (["cloud/migrations/001_auth.sql"],"cloud"),
            (["cvstudio_engine.py","cloud/app.py"],"full"),
            (["index.html"],"full"),
            (["requirements-cloud.txt"],"full"),
            (["package.json"],"full"),
            ([".github/workflows/ci.yml"],"full"),
            ([".github/ci_scope.py"],"full"),
            (["docs/non-markdown.sh"],"full"),
            (["unknown.txt"],"full"),
            ([], "full"),
        ]
        for paths, expected in cases:
            with self.subTest(paths=paths):
                self.assertEqual(classify(paths),expected)
    def test_fail_closed(self):
        for name,event in (("workflow_dispatch",{}),("push",{"ref":"refs/tags/v1"}),
                           ("push",{"ref":"refs/heads/master","forced":True}),("pull_request",{})):
            self.assertEqual(event_scope(name,event),"full")

    def test_git_diff_routing(self):
        from unittest.mock import patch
        base, head = "a"*40, "b"*40
        event={"pull_request":{"base":{"sha":base},"head":{"sha":head}}}
        for diff, expected in (
            (b"M\\0cloud/deploy/online_init.py\\0", "online"),
            (b"A\\0cloud/app.py\\0M\\0docs/guide.md\\0", "cloud"),
            (b"M\\0docs/guide.md\\0", "docs"),
            (b"D\\0cloud/app.py\\0", "full"),
            (b"M\\0cloud/app.py\\0M\\0cvstudio_engine.py\\0", "full"),
            (b"M\\0cloud/app.py", "full"),
        ):
            # These escaped bytes are decoded into actual NUL-delimited git output.
            with self.subTest(diff=diff), patch(__name__+".git",side_effect=[base.encode()+b"\n",diff.replace(b"\\0",b"\0")]):
                self.assertEqual(event_scope("pull_request",event),expected)
        with patch(__name__+".git",side_effect=subprocess.CalledProcessError(1,"git")):
            self.assertEqual(event_scope("pull_request",event),"full")

def main():
    if sys.argv[1:]==["--self-test"]:
        unittest.main(argv=[sys.argv[0]])
        return
    try:
        event=json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        scope=event_scope(os.environ["GITHUB_EVENT_NAME"],event)
    except (KeyError,OSError,ValueError,TypeError):
        scope="full"
    print("CI scope:",scope)
    with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as output:
        output.write(f"scope={scope}\n")

if __name__=="__main__":
    main()
