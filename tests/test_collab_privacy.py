"""What a member may learn about the host's Mac, and the page-loading routes added for the shared page (tail, polling presence, the host dashboard)."""
import json, os, sys, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
from test_collab_server import Base      # noqa: E402
import collab_policy as P                # noqa: E402


SOMEONE = "/" + "Users" + "/somebody"          # another person's home folder, written so that no path appears in this file


class TestNoHostPaths(Base):
    def setUp(self):
        super().setUp()
        self.mid, self.mtok = self.join("Mei")
        self.secret_paths = [self.work, os.path.join(self.tmp, "home"), self.tmp]
        wd = self.work
        self.st.append_system(self.pid, "model_turn_start", {"turn": "t1", "model": "opus", "model_id": "claude-cli:opus", "label": "private-label", "payer": "the host", "initiated_by": [self.mid], "cwd": wd, "summary": []}, chat="main")
        self.st.append_system(self.pid, "tool_request", {"turn": "t1", "tool": "read_file", "args_summary": f"read {wd}/data/a.csv and {os.path.join(self.tmp, 'home')}/.ssh/x", "touches": [f"{wd}/data/a.csv"], "requested_by": self.mid}, chat="main")
        self.st.append_system(self.pid, "guard_decision", {"turn": "t1", "verdict": "deny", "reason": f"{wd}/secret is outside what you may read; also " + SOMEONE + "/notes"}, chat="main")
        self.st.append_model_message(self.pid, "main", "opus", f"I changed {wd}/data/a.csv", {"initiated_by": self.mid, "model_label": "Claude Opus", "turn": "t1"})

    def dumps(self, token, path):
        st, j, _ = self.call("GET", path, token=token)
        self.assertEqual(st, 200, j)
        return json.dumps(j)

    def assert_clean(self, text):
        for bad in self.secret_paths + [SOMEONE, "claude-cli:opus", "private-label"]:
            self.assertNotIn(bad, text)

    def test_a_members_project_info_names_no_host_folder(self):
        text = self.dumps(self.mtok, f"/api/collab/p/{self.pid}")
        self.assert_clean(text)
        self.assertEqual(json.loads(text)["working_dir"], "the project folder")

    def test_a_members_events_and_stream_name_no_host_folder_or_private_label(self):
        text = self.dumps(self.mtok, f"/api/collab/p/{self.pid}/events?after=0&limit=500")
        self.assert_clean(text)
        ev = [e for e in json.loads(text)["events"] if e["type"] == "model_turn_start"][0]["payload"]
        self.assertEqual((ev["label"], ev["cwd"]), ("opus", "the project folder"))          # the handle people type, not the host's own label
        self.assertIn("data/a.csv", text)                                                  # a path inside the project stays useful, as a relative one
        tail = self.dumps(self.mtok, f"/api/collab/p/{self.pid}/events?tail=1&limit=50")
        self.assert_clean(tail)

    def test_search_and_export_name_no_host_folder(self):
        self.assert_clean(self.dumps(self.mtok, f"/api/collab/p/{self.pid}/search?q=changed"))
        st, raw, _ = self.call("GET", f"/api/collab/p/{self.pid}/export?format=orbit&chat=main", token=self.mtok)
        self.assertEqual(st, 200)
        self.assert_clean(raw.decode() if isinstance(raw, bytes) else json.dumps(raw))

    def test_an_error_message_names_no_host_folder(self):
        st, j, _ = self.call("GET", f"/api/collab/p/{self.pid}/filetext?path={self.work}/nope.txt", token=self.mtok)
        self.assertNotIn(self.work, json.dumps(j))

    def test_the_owner_sees_their_own_paths(self):
        text = self.dumps(self.otok, f"/api/collab/p/{self.pid}")
        self.assertIn(self.work, text)
        ev = [e for e in json.loads(self.dumps(self.otok, f"/api/collab/p/{self.pid}/events?after=0&limit=500"))["events"] if e["type"] == "model_turn_start"][0]["payload"]
        self.assertEqual(ev["cwd"], self.work)

    def test_the_hosts_record_itself_is_not_changed(self):
        start = [e for e in self.st.chat_events(self.pid, "main") if e["type"] == "model_turn_start"][0]["payload"]
        self.assertEqual((start["cwd"], start["label"]), (self.work, "private-label"))   # models and the host's own tools still get the true values

    def test_a_files_own_text_is_never_rewritten(self):
        with open(os.path.join(self.work, "notes.txt"), "w") as f: f.write(f"see {self.work}/x\n")
        mid, tok = self.join("Ed", role="editor")
        self.st.set_grant(self.pid, self.owner, mid, dict(self.st.grant_of(self.pid, mid), files_edit=True, files_browse=True, read_paths=[self.work], write_paths=[self.work]))
        st, j, _ = self.call("GET", f"/api/collab/p/{self.pid}/filetext?path=notes.txt", token=tok)
        if st == 200: self.assertIn(self.work, j["content"])


class TestTailAndPresence(Base):
    def setUp(self):
        super().setUp()
        self.mid, self.mtok = self.join("Mei")
        for i in range(30): self.st.submit_as(self.pid, self.mid, {"id": f"i{i}", "type": "msg", "chat": "main", "payload": {"text": f"hello {i}"}})

    def test_tail_returns_the_end_of_the_chat_and_says_there_is_more(self):
        st, j, _ = self.call("GET", f"/api/collab/p/{self.pid}/events?tail=1&limit=10", token=self.mtok)
        self.assertEqual(st, 200)
        texts = [e["payload"]["text"] for e in j["events"] if e["type"] == "msg"]
        self.assertEqual(texts[-1], "hello 29"); self.assertTrue(j["more_before"]); self.assertEqual(j["head"], j["next"])
        self.assertEqual([e["seq"] for e in j["events"]], sorted(e["seq"] for e in j["events"]))
        first = j["events"][0]["seq"]
        st, k, _ = self.call("GET", f"/api/collab/p/{self.pid}/events?before={first}&limit=10", token=self.mtok)
        self.assertEqual(k["events"][-1]["seq"], first - 1)
        st, all_, _ = self.call("GET", f"/api/collab/p/{self.pid}/events?before=100000&limit=500", token=self.mtok)
        self.assertFalse(all_["more_before"])

    def test_tail_hides_chats_a_member_may_not_read(self):
        other, _t = self.join("Ed")
        st, c, _ = self.call("POST", f"/api/collab/p/{self.pid}/chats", {"name": "Private", "private": True, "members": [other]}, token=self.otok)
        self.assertEqual(st, 200, c)
        self.st.submit_as(self.pid, self.owner, {"id": "p1", "type": "msg", "chat": c["chat"], "payload": {"text": "owner only"}})
        st, j, _ = self.call("GET", f"/api/collab/p/{self.pid}/events?tail=1&limit=100", token=self.mtok)
        self.assertNotIn("owner only", json.dumps(j))

    def test_a_page_that_polls_is_counted_as_here(self):
        self.call("GET", f"/api/collab/p/{self.pid}/events?tail=1", token=self.mtok)
        st, pv, _ = self.call("GET", f"/api/collab/p/{self.pid}", token=self.otok)
        self.assertIn(self.mid, pv["online"])


class TestActivity(Base):
    def test_activity_counts_without_any_text(self):
        mid, _ = self.join("Mei")
        self.st.submit_as(self.pid, mid, {"id": "x1", "type": "msg", "chat": "main", "payload": {"text": "SECRET WORDS"}})
        self.st.append_system(self.pid, "model_turn_start", {"turn": "t", "model": "opus", "label": "Opus", "initiated_by": [mid], "cwd": self.work, "summary": []}, chat="main")
        self.st.append_system(self.pid, "approval_request", {"request": "r1", "turn": "t", "tool": "run_shell", "args_summary": "rm x", "touches": [], "requested_by": mid, "reason": "x", "need": 1, "flags": []}, chat="main")
        a = self.st.activity(self.pid)
        self.assertEqual((a["messages_24h"], a["turns_24h"], a["approvals_waiting"], a["people_active_24h"]), (1, 1, 1, 1))
        self.assertEqual(a["models_24h"], [{"model": "Opus", "turns": 1}])
        self.assertNotIn("SECRET", json.dumps(a))
        self.assertTrue(a["last_activity"] and time.time() - a["last_activity"] < 60)


if __name__ == "__main__":
    unittest.main()
