"""Projects from the Claude desktop app's sidebar groups: found by themselves, their
Claude Code chats filed under them, and choices made in Orbit kept. A fake Claude app
folder and temporary config files only; nothing real is read or written."""
import json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestClaudeProjects(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-cp-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        app = os.path.join(self.tmp, "Claude")
        self.work = os.path.join(self.tmp, "work", "assays")
        os.makedirs(self.work)
        thread = os.path.join(app, "claude-code-sessions", "ws", "th")
        os.makedirs(thread)
        # two chats in "Assays" (one whose app id differs from its CLI id), one in "Notes"
        for local, cli, cwd in (("local_a1", "cli-a1", self.work), ("local_a2", "a2", self.work),
                                ("local_n1", "n1", None)):
            d = {"sessionId": local, "cliSessionId": cli, "title": local}
            if cwd: d["cwd"] = cwd
            json.dump(d, open(os.path.join(thread, local + ".json"), "w"))
        self.cfg = os.path.join(app, "claude_desktop_config.json")
        self.write_groups([{"id": "cg-aaaa1111", "name": "Assays"}, {"id": "cg-bbbb2222", "name": "Notes"}],
                          {"code:local_a1": "cg-aaaa1111", "code:local_a2": "cg-aaaa1111",
                           "code:local_n1": "cg-bbbb2222"})
        saved = {k: getattr(q, k) for k in ("CLAUDE_APP_DIR", "PROJECTS", "CHAT_PROJECTS",
                                             "CLAUDE_DISMISSED", "CONFIG_HISTORY")}
        self.addCleanup(lambda: [setattr(q, k, v) for k, v in saved.items()])
        q.CLAUDE_APP_DIR = app
        for k, f in (("PROJECTS", "projects.json"), ("CHAT_PROJECTS", "chat-projects.json"),
                     ("CLAUDE_DISMISSED", "dismissed.json"), ("CONFIG_HISTORY", "history")):
            setattr(q, k, os.path.join(self.tmp, f))
        q._CLAUDE_GROUPS.update(key=None, ids_at=0.0)
        self.addCleanup(q._CLAUDE_GROUPS.update, key=None, ids_at=0.0)

    def write_groups(self, groups, assignments):
        json.dump({"preferences": {"epitaxyPrefs": {"dframe-group-scopes": {"ws/th": {
            "groups": groups, "assignments": assignments, "order": {}}}}}}, open(self.cfg, "w"))
        st = os.stat(self.cfg)
        os.utime(self.cfg, (st.st_atime, st.st_mtime + 5))   # a new mtime even within the same second
        q._CLAUDE_GROUPS.update(key=None)

    def projects(self):
        return {v["name"]: (k, v) for k, v in q.projects_load().items()}

    def test_groups_become_projects_with_their_folder(self):
        by = q.claude_projects_sync()
        ps = self.projects()
        self.assertEqual(set(ps), {"Assays", "Notes"})
        self.assertEqual(ps["Assays"][1]["claude_group"], "cg-aaaa1111")
        self.assertEqual(ps["Assays"][1]["folder"], os.path.abspath(self.work))   # both chats work there
        self.assertNotIn("folder", ps["Notes"][1])                                # no folder known
        self.assertEqual(q.claude_projects_sync(), by)                            # nothing new the second time

    def test_chats_are_filed_by_the_cli_session_id(self):
        rows = [{"id": "cq-cli-a1", "project": None}, {"id": "cq-a2", "project": None},
                {"id": "cq-n1", "project": None}, {"id": "20260101-x", "project": None}]
        q.claude_projects_apply(rows)
        ps = self.projects()
        self.assertEqual([r["project"] for r in rows],
                         [ps["Assays"][0], ps["Assays"][0], ps["Notes"][0], None])
        self.assertEqual(q.chat_project("cq-n1"), ps["Notes"][0])

    def test_a_rename_in_claude_follows_unless_renamed_here(self):
        q.claude_projects_sync()
        pid = self.projects()["Notes"][0]
        self.write_groups([{"id": "cg-aaaa1111", "name": "Assays"}, {"id": "cg-bbbb2222", "name": "Lab notes"}], {})
        q.claude_projects_sync()
        self.assertEqual(q.projects_load()[pid]["name"], "Lab notes")
        q.project_upsert(pid, name="My notes")
        self.write_groups([{"id": "cg-aaaa1111", "name": "Assays"}, {"id": "cg-bbbb2222", "name": "Notes again"}], {})
        q.claude_projects_sync()
        self.assertEqual(q.projects_load()[pid]["name"], "My notes")

    def test_a_project_deleted_here_does_not_come_back(self):
        q.claude_projects_sync()
        pid = self.projects()["Notes"][0]
        saved = q.session_list
        q.session_list = lambda: []
        try: q.project_delete(pid)
        finally: q.session_list = saved
        q.claude_projects_sync()
        self.assertNotIn("Notes", self.projects())
        self.assertIn("Assays", self.projects())

    def test_moving_a_chat_in_orbit_outranks_claude(self):
        q.claude_projects_sync()
        q.session_assign("cq-n1", "")                  # no file here yet: kept on the side
        rows = [{"id": "cq-n1", "project": None}]
        q.claude_projects_apply(rows)
        self.assertIsNone(rows[0]["project"])
        self.assertIsNone(q.chat_project("cq-n1"))
        # a chat Orbit has saved: the choice is written into it
        rows = [{"id": "cq-a2", "project": "p-other", "project_set": True}]
        q.claude_projects_apply(rows)
        self.assertEqual(rows[0]["project"], "p-other")

    def test_turned_off(self):
        saved = q.S.get("claude_projects", True)
        q.S["claude_projects"] = False
        self.addCleanup(q.S.__setitem__, "claude_projects", saved)
        self.assertEqual(q.claude_projects_sync(), {})
        self.assertEqual(q.projects_load(), {})

    def test_no_claude_app(self):
        q.CLAUDE_APP_DIR = os.path.join(self.tmp, "nowhere")
        q._CLAUDE_GROUPS.update(key=None, ids_at=0.0)
        self.assertEqual(q.claude_app_groups(), ({}, {}))
        self.assertEqual(q.claude_projects_sync(), {})


if __name__ == "__main__":
    unittest.main()
