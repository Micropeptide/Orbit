"""The web page's Claude Code-style transcript helpers (web/index.html): tool names,
targets, the one-line result summaries, JSON summaries and todo parsing. The pure
functions are lifted out of the page and run under Node; skipped without Node."""
import json, os, re, shutil, subprocess, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(os.path.dirname(HERE), "web", "index.html")

NAMES = ["fmtSecs", "toolLabel", "toolName", "shortPath", "toolTarget", "nLines", "plural",
         "resultSummary", "jsonSummary", "parsePlan", "todoMark"]
CONSTS = ["TOOLNAME", "TOOLVERB", "TOOLFAM", "FAMWORD"]


def lift():
    with open(PAGE, encoding="utf-8") as f: src = f.read()
    out = []
    for c in CONSTS:
        m = re.search(r"^const " + c + r"=\{.*?\};\n", src, re.S | re.M)
        assert m, c
        out.append(m.group(0))
    for n in NAMES:
        m = re.search(r"^function " + n + r"\(.*?\n(?=function |const |let |// |/\*|\n)", src, re.S | re.M)
        assert m, n
        out.append(m.group(0))
    return "\n".join(out)


@unittest.skipUnless(shutil.which("node"), "needs node")
class TestTranscriptHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = lift()

    def js(self, expr):
        code = self.lib + "\nconsole.log(JSON.stringify(" + expr + "));"
        r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_names_follow_claude_code(self):
        self.assertEqual(self.js("['read_file','Edit','run_shell','Grep','web_search','Task','mcp__srv__do_thing','server.tool_x']"
                                 ".map(toolName)"),
                         ["Read", "Update", "Bash", "Search", "Web Search", "Agent", "do thing", "tool x"])

    def test_targets(self):
        self.assertEqual(self.js("toolTarget('Read',{file_path:'/a/b/c/d.py'})"), "c/d.py")
        self.assertEqual(self.js("toolTarget('Bash',{command:'git   status'})"), "git status")
        self.assertEqual(self.js("toolTarget('Grep',{pattern:'def main',path:'/x/y/z'})"), "def main in y/z")
        # Codex runs every command through a login shell; the row shows the command
        self.assertEqual(self.js("toolTarget('shell',{command:\"/bin/zsh -lc 'ls | head -3'\"})"), "ls | head -3")
        self.assertEqual(self.js("toolTarget('shell',{command:['bash','-lc','echo hi']})"), "echo hi")

    def test_result_summaries(self):
        cases = {
            "resultSummary('Read',{output:'a\\nb\\nc\\n'})": "Read 3 lines",
            "resultSummary('Write',{output:'ok',args:{file_path:'/p/q/n.md',content:'1\\n2'}})": "Wrote 2 lines to q/n.md",
            "resultSummary('Update',{output:'x',diff:{added:4,removed:1}})": "Added 4 lines, removed 1 line",
            "resultSummary('Search',{output:'No matches found'})": "No matches found",
            "resultSummary('Bash',{output:'exit=0\\nstdout:\\nhello\\nworld\\n'})": "hello  +1 line",
            "resultSummary('Bash',{output:'exit=2\\nstdout:\\n\\nstderr:\\nboom'})": "exit 2 · boom",
            "resultSummary('Bash',{output:''})": "(No output)",
            "resultSummary('Read',{output:''})": "(No content)",
            "resultSummary('Bash',{output:'bad thing\\nmore',ok:false})": "bad thing",
            "resultSummary('Bash',{stopped:true})": "stopped before it came back",
            "resultSummary('portfolio',{output:'{\"cash\": 10, \"positions\": [1,2]}'})": "cash: 10 · positions: 2 items",
        }
        for expr, want in cases.items():
            self.assertEqual(self.js(expr), want, expr)

    def test_json_cut_short_still_summarised(self):
        got = self.js("resultSummary('x',{output:'{\"start\": 1000.0, \"cash\": 753.27, \"positions\": [{\"a\":'})")
        self.assertTrue(got.startswith("start: 1000.0 · cash: 753.27"), got)

    def test_todo_marks(self):
        steps = self.js("parsePlan('0. [x] one\\n1. [ ] two\\n2. [ ] three')")
        self.assertEqual([(s["done"], s["active"]) for s in steps], [(True, False), (False, True), (False, False)])
        steps = self.js("parsePlan('0. [x] one\\n1. [ ] two\\n2. [>] three').map(todoMark)")
        self.assertEqual(steps, ["☒", "☐", "◼"])


if __name__ == "__main__":
    unittest.main()
