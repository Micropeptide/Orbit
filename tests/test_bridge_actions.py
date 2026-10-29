"""Orbit's helper tools that act on Orbit itself: the person's own chats, Crew runs, shared projects and cluster models.

The rules under test: an app may do none of this until the person turns it on for that app; everything that changes something, and every read of a chat's text, waits for the
person's yes in Orbit (whatever the app's approval setting is); one yes for a chat covers that chat for two hours and no other; limits count; a reply is text, not an order."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import science_bridge as B                                        # noqa: E402
from test_science_bridge import Base, FakeBackend                 # noqa: E402


class ActBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.chat_rows = [{"id": "c1", "title": "Methylation notes", "model": "claude", "mtime": 900.0, "n": 12, "project": "p1"},
                          {"id": "c2", "title": "Peak calling", "model": "qwen", "mtime": 800.0, "n": 4, "project": None}]
        self.texts = {"c1": [{"who": "person", "text": "hello"}, {"who": "orbit", "text": "hi, how can I help"}], "c2": [{"who": "orbit", "text": "private words"}]}
        self.chat_running = set(); self.acts = []
        self.crews = [{"id": "r1", "title": "Pipeline", "state": "running", "round": 2, "best": 7.5, "reason": ""}]
        self.projects = [{"id": "p_aaaaaaaaaaaa", "name": "Notebook", "members": 3, "frozen": False}]
        self.servers = [{"id": "qwen-h2", "label": "Qwen on HPC", "state": "ready", "where": "HPC GPU", "note": "serving"}]

    def chats(self, query, project, limit, archived): return [r for r in self.chat_rows if query.lower() in r["title"].lower()][:limit]
    def chat_info(self, sid):
        r = next((r for r in self.chat_rows if r["id"] == sid), None)
        if r is None: raise B.BridgeError("no such chat")
        return {"title": r["title"], "model": r["model"], "folder": None}
    def chat_messages(self, sid, last): return {"messages": self.texts[sid][-last:], "running": sid in self.chat_running}
    def crew_runs(self): return list(self.crews)
    def shared_list(self): return list(self.projects)
    def cluster_models(self): return list(self.servers)
    def act(self, name, args, app):
        self.acts.append((name, dict(args), app))
        if name == "chat_new": return {"text": "started chat n1", "sid": "n1"}
        if name == "shared_invite": return {"text": "invitation link: https://example.org/join?p=x&i=y&s=z"}
        return {"text": f"{name} done"}


class ActBase(Base):
    def setUp(self):
        super().setUp()
        self.be = ActBackend(); self.b.backend = self.be
        self.tmp_work = os.path.join(self.tmp, "work"); os.makedirs(self.tmp_work)
        self.settings(actions="ask", workdirs=[self.tmp_work])

    def waiting(self): return [j for j in self.b.inbox() if j["state"] == "waiting"]
    def yes(self, job=None):
        job = job or self.waiting()[0]["id"]; return self.b.decide(job, True)
    def jid(self, text): return text.split()[1]


class TestOffByDefault(Base):
    def setUp(self):
        super().setUp(); self.be = ActBackend(); self.b.backend = self.be

    def test_a_new_app_may_do_none_of_it(self):
        for name, args in [("orbit_chats", {}), ("orbit_chat_read", {"chat": "c1"}), ("orbit_chat_send", {"chat": "c1", "text": "x"}), ("orbit_chat_new", {"text": "x"}),
                           ("orbit_crew_runs", {}), ("orbit_crew_start", {"brief": "x", "builders": ["m"]}), ("orbit_crew_control", {"run": "r1", "action": "stop"}),
                           ("orbit_shared_projects", {}), ("orbit_shared_invite", {"project": "p_aaaaaaaaaaaa"}), ("orbit_shared_pause", {"project": "p_aaaaaaaaaaaa"}),
                           ("orbit_shared_resume", {"project": "p_aaaaaaaaaaaa"}), ("orbit_cluster_models", {}), ("orbit_cluster_model", {"server": "qwen-h2", "action": "start"})]:
            with self.assertRaises(B.BridgeError, msg=name) as cm: self.call(name, **args)
            self.assertIn("Settings > Helpers", str(cm.exception))
        self.assertEqual(self.be.acts, [])

    def test_the_setting_is_validated(self):
        with self.assertRaises(ValueError): self.settings(actions="always")
        self.assertEqual(self.settings(actions="ask")["clients"][0]["actions"], "ask")


class TestReads(ActBase):
    def test_lists_need_no_yes(self):
        self.assertIn("Methylation notes", self.call("orbit_chats")); self.assertNotIn("Peak calling", self.call("orbit_chats", query="methyl"))
        self.assertIn("Pipeline", self.call("orbit_crew_runs")); self.assertIn("Notebook", self.call("orbit_shared_projects")); self.assertIn("Qwen on HPC", self.call("orbit_cluster_models"))
        self.assertEqual(self.waiting(), [])

    def test_the_text_of_a_chat_waits_for_a_yes(self):
        out = self.call("orbit_chat_read", chat="c1"); self.assertIn("waiting for the person's yes", out); self.assertNotIn("how can I help", out)
        j = self.waiting()[0]; self.assertIn("Methylation notes", j["task"]); self.assertIn("read", j["task"])
        self.assertIn("Claude Science", self.be.notices[-1][0]); self.yes()
        self.assertIn("how can I help", self.call("orbit_job", job=self.jid(out)))

    def test_one_yes_covers_that_chat_only_and_for_two_hours(self):
        out = self.call("orbit_chat_read", chat="c1"); self.yes()
        self.assertIn("how can I help", self.call("orbit_chat_read", chat="c1"))
        self.assertIn("waiting", self.call("orbit_chat_read", chat="c2")); self.assertEqual(len(self.waiting()), 1)
        self.clock[0] += 2 * 3600 + 5
        self.assertIn("waiting", self.call("orbit_chat_read", chat="c1"))

    def test_a_chat_that_is_not_there_is_refused_at_once(self):
        with self.assertRaises(B.BridgeError): self.call("orbit_chat_read", chat="nope")
        with self.assertRaises(B.BridgeError): self.call("orbit_chat_read", chat="../../etc")

    def test_waiting_for_a_granted_chat_to_finish_answering(self):
        self.call("orbit_chat_read", chat="c1"); self.yes(); self.be.chat_running.add("c1")
        orig = self.b.sleep
        def finish(s): self.be.chat_running.discard("c1"); self.be.texts["c1"].append({"who": "orbit", "text": "the answer"}); orig(s)
        self.b.sleep = finish; self.assertIn("the answer", self.call("orbit_chat_read", chat="c1", wait_s=60))


class TestActions(ActBase):
    def test_even_with_approval_none_a_change_asks(self):
        self.settings(approval="none")
        out = self.call("orbit_chat_send", chat="c1", text="please run it"); self.assertIn("waiting for the person's yes", out); self.assertEqual(self.be.acts, [])

    def test_send_into_a_chat_then_the_same_chat_goes_straight_through(self):
        out = self.call("orbit_chat_send", chat="c1", text="first"); self.assertEqual(self.be.acts, [])
        self.assertIn("Methylation notes", self.waiting()[0]["task"]); self.yes()
        self.assertEqual(self.be.acts, [("chat_send", {"sid": "c1", "text": "first"}, "Claude Science")]); self.assertIn("chat_send done", self.call("orbit_job", job=self.jid(out)))
        self.assertIn("chat_send done", self.call("orbit_chat_send", chat="c1", text="second")); self.assertEqual(len(self.be.acts), 2); self.assertEqual(self.waiting(), [])
        self.call("orbit_chat_send", chat="c2", text="other"); self.assertEqual(len(self.be.acts), 2); self.assertEqual(len(self.waiting()), 1)

    def test_no_means_it_never_runs(self):
        out = self.call("orbit_chat_send", chat="c1", text="x"); self.b.decide(self.waiting()[0]["id"], False)
        self.assertIn("said no", self.call("orbit_job", job=self.jid(out))); self.assertEqual(self.be.acts, [])

    def test_nobody_answering_lets_it_lapse(self):
        out = self.call("orbit_chat_send", chat="c1", text="x"); self.clock[0] += B.APPROVAL_WAIT_S + 5
        self.assertIn("expired", self.call("orbit_job", job=self.jid(out))); self.assertEqual(self.be.acts, [])

    def test_a_new_chat_names_its_model_and_folder_and_is_then_the_apps_own(self):
        with self.assertRaises(B.BridgeError): self.call("orbit_chat_new", text="go", folder="/etc")            # not a folder the person listed
        out = self.call("orbit_chat_new", text="go", model="qwen", folder=self.tmp_work, title="Batch 1"); t = self.waiting()[0]["task"]
        self.assertIn("qwen", t); self.assertIn(self.tmp_work, t); self.yes()
        self.assertEqual(self.be.acts[0][0], "chat_new"); self.assertEqual(self.be.acts[0][1]["folder"], os.path.realpath(self.tmp_work))
        self.be.texts["n1"] = [{"who": "orbit", "text": "working"}]; self.be.chat_rows.append({"id": "n1", "title": "Batch 1", "model": "qwen", "mtime": 1, "n": 1, "project": None})
        self.assertIn("working", self.call("orbit_chat_read", chat="n1"))                                       # no second yes for a chat it started

    def test_crew_start_checks_its_inputs_and_waits(self):
        for bad in ({"brief": "", "builders": ["m"]}, {"brief": "x", "builders": []}, {"brief": "x", "builders": ["m"], "folder": "/etc"}, {"brief": "x", "builders": ["m"], "hours": 1000}):
            with self.assertRaises(B.BridgeError, msg=str(bad)): self.call("orbit_crew_start", **bad)
        self.call("orbit_crew_start", brief="Improve the pipeline", builders=["claude"], reviewer="qwen", title="Improve", folder=self.tmp_work, hours=2); self.assertEqual(self.be.acts, [])
        self.assertIn("Improve the pipeline", self.waiting()[0]["task"]); self.yes(); self.assertEqual(self.be.acts[0][0], "crew_start"); self.assertEqual(self.be.acts[0][1]["builders"], ["claude"])

    def test_crew_control(self):
        with self.assertRaises(B.BridgeError): self.call("orbit_crew_control", run="r1", action="delete")
        self.call("orbit_crew_control", run="r1", action="stop"); self.yes(); self.assertEqual(self.be.acts[0][:2], ("crew_control", {"run": "r1", "action": "stop", "note": ""}))

    def test_invitations_wait_and_the_link_comes_back_to_the_app(self):
        with self.assertRaises(B.BridgeError): self.call("orbit_shared_invite", project="p_aaaaaaaaaaaa", role="owner")
        with self.assertRaises(B.BridgeError): self.call("orbit_shared_invite", project="nope")
        out = self.call("orbit_shared_invite", project="p_aaaaaaaaaaaa", role="viewer", uses=1, days=3); self.assertIn("viewer", self.waiting()[0]["task"]); self.yes()
        self.assertIn("https://example.org/join", self.call("orbit_job", job=self.jid(out)))

    def test_pausing_a_project_is_immediate_and_resuming_asks(self):
        self.assertIn("shared_pause done", self.call("orbit_shared_pause", project="p_aaaaaaaaaaaa")); self.assertEqual(self.waiting(), [])
        self.call("orbit_shared_resume", project="p_aaaaaaaaaaaa"); self.assertEqual(len(self.waiting()), 1)

    def test_cluster_models(self):
        with self.assertRaises(B.BridgeError): self.call("orbit_cluster_model", server="qwen-h2", action="delete")
        with self.assertRaises(B.BridgeError): self.call("orbit_cluster_model", server="no/such", action="start")
        self.call("orbit_cluster_model", server="qwen-h2", action="start"); self.assertIn("GPU", self.waiting()[0]["task"]); self.yes()
        self.assertEqual(self.be.acts[0][:2], ("cluster_model", {"server": "qwen-h2", "action": "start"}))

    def test_the_same_request_twice_is_one_request(self):
        a = self.call("orbit_cluster_model", server="qwen-h2", action="stop"); b = self.call("orbit_cluster_model", server="qwen-h2", action="stop")
        self.assertEqual(self.jid(a), self.jid(b)); self.assertEqual(len(self.waiting()), 1)

    def test_limits_apply(self):
        self.settings(max_per_day=2)
        self.call("orbit_cluster_model", server="a1", action="stop"); self.call("orbit_cluster_model", server="a2", action="stop")
        with self.assertRaises(B.BridgeError) as cm: self.call("orbit_cluster_model", server="a3", action="stop")
        self.assertIn("daily limit", str(cm.exception))

    def test_too_many_waiting_at_once(self):
        self.settings(max_per_day=0)
        for i in range(B.MAX_WAITING): self.call("orbit_cluster_model", server=f"s{i}", action="stop")
        with self.assertRaises(B.BridgeError): self.call("orbit_cluster_model", server="s99", action="stop")

    def test_a_failure_in_orbit_is_reported_not_hidden(self):
        def boom(name, args, app): raise B.BridgeError("no such server")
        self.be.act = boom; out = self.call("orbit_cluster_model", server="qwen-h2", action="start"); self.yes()
        self.assertIn("no such server", self.call("orbit_job", job=self.jid(out)))

    def test_the_inbox_labels_these_requests(self):
        self.call("orbit_cluster_model", server="qwen-h2", action="start"); j = self.waiting()[0]; self.assertEqual(j["kind"], "action"); self.assertTrue(j["write"])


class TestToolList(unittest.TestCase):
    def test_every_new_tool_is_listed_with_a_closed_schema(self):
        names = {t["name"] for t in B.TOOLS}
        for n in ("orbit_chats", "orbit_chat_read", "orbit_chat_send", "orbit_chat_new", "orbit_crew_runs", "orbit_crew_start", "orbit_crew_control", "orbit_shared_projects",
                  "orbit_shared_invite", "orbit_shared_pause", "orbit_shared_resume", "orbit_cluster_models", "orbit_cluster_model"): self.assertIn(n, names)
        for t in B.TOOLS: self.assertFalse(t["inputSchema"]["additionalProperties"], t["name"])


if __name__ == "__main__":
    unittest.main()


class TestUnknownModelHint(unittest.TestCase):
    """A model id the helper door does not offer is refused, and the refusal names the nearest ids that do work (the same model often lives under another provider)."""
    @classmethod
    def setUpClass(cls):
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader("orbit_ui_unknown_model", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "orbit-ui"))
        spec = importlib.util.spec_from_loader(loader.name, loader); cls.ui = importlib.util.module_from_spec(spec); loader.exec_module(cls.ui)

    def backend(self):
        be = self.ui._ScienceBackend()
        be._rows = lambda: [{"id": i, "tier": "light"} for i in ("codex-cli:gpt-5.6-luna", "harness:opencode-go/gpt-6-luna", "harness:opencode-zen/gpt-6-luna", "claude-cli:haiku")] + [{"id": "claude-cli:opus", "tier": "off"}]
        be.server_llms = lambda: [{"id": "hpc:qwen", "state": "active"}]
        return be

    def test_it_suggests_where_the_name_does_live(self):
        e = self.backend()._unknown_model("codex-cli:gpt-6-luna")
        self.assertIsInstance(e, B.BridgeError)
        for want in ("codex-cli:gpt-5.6-luna", "harness:opencode-go/gpt-6-luna", "harness:opencode-zen/gpt-6-luna"): self.assertIn(want, str(e))
        self.assertNotIn("claude-cli:opus", str(e)); self.assertIn("orbit_models", str(e))

    def test_nothing_close_gives_a_plain_refusal(self):
        e = str(self.backend()._unknown_model("zzz-nothing")); self.assertNotIn("Did you mean", e); self.assertIn("orbit_models", e)
