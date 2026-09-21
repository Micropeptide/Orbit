"""Some settings belong to a chat, not to Orbit. A chat on a small local model wants
easy mode and a hosted reviewer; the one next to it does not, and switching between them
should not mean setting both again."""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestPerChatSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-chatpref-")
        saved = q.CE._work_dir
        q.CE._work_dir = lambda: self.tmp
        self.addCleanup(setattr, q.CE, "_work_dir", saved)
        self.saved_easy = q.S.get("easy_mode")
        self.addCleanup(q.S.__setitem__, "easy_mode", self.saved_easy)
        q.S["easy_mode"] = False

    def test_a_chat_keeps_its_own_answer(self):
        self.assertFalse(q.chat_setting("easy_mode", "chat-A"))
        q.set_chat_setting("chat-A", "easy_mode", True)
        self.assertTrue(q.chat_setting("easy_mode", "chat-A"))
        self.assertFalse(q.chat_setting("easy_mode", "chat-B"))
        self.assertFalse(q.S.get("easy_mode"), "the global setting was changed")

    def test_clearing_it_follows_orbit_again(self):
        q.set_chat_setting("chat-A", "easy_mode", True)
        q.set_chat_setting("chat-A", "easy_mode", None)
        self.assertFalse(q.chat_setting("easy_mode", "chat-A"))
        q.S["easy_mode"] = True
        self.assertTrue(q.chat_setting("easy_mode", "chat-A"))

    def test_the_side_work_model_is_per_chat_too(self):
        q.set_chat_setting("chat-A", "helper_model", "claude-cli:haiku")
        saved = getattr(q.TURN_CTX, "sid", None)
        self.addCleanup(setattr, q.TURN_CTX, "sid", saved)
        q.TURN_CTX.sid = "chat-A"
        self.assertEqual(q.chat_setting("helper_model"), "claude-cli:haiku")
        q.TURN_CTX.sid = "chat-B"
        self.assertEqual(q.chat_setting("helper_model"), q.S.get("helper_model"))

    def test_only_the_named_settings_can_be_per_chat(self):
        """A chat cannot quietly keep its own copy of something global, such as where
        the model server listens."""
        self.assertEqual(q.set_chat_setting("chat-A", "server", {"port": 9}), {})
        self.assertNotIn("server", q.CE.chat_prefs("chat-A"))
        for key in ("easy_mode", "helper_model", "auto_review", "verify_turns"):
            self.assertIn(key, q.PER_CHAT)

    def test_no_chat_means_orbits_own_setting(self):
        saved = getattr(q.TURN_CTX, "sid", None)
        self.addCleanup(setattr, q.TURN_CTX, "sid", saved)
        q.TURN_CTX.sid = None
        q.S["easy_mode"] = True
        self.assertTrue(q.chat_setting("easy_mode"))


if __name__ == "__main__":
    unittest.main()


class TestAHelperFollowsTheChat(unittest.TestCase):
    """A helper started by the task tool has no chat of its own, but it is working in
    yours: it must read this chat's easy mode and side-work model, and the grants you
    gave for the rest of this chat must cover it. It must NOT share the chat's token
    accounting — its context is its own."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-helper-")
        saved = q.CE._work_dir
        q.CE._work_dir = lambda: self.tmp
        self.addCleanup(setattr, q.CE, "_work_dir", saved)
        for name in ("sid", "settings_sid"):
            self.addCleanup(setattr, q.TURN_CTX, name, getattr(q.TURN_CTX, name, None))
        q.S["easy_mode"] = False
        self.addCleanup(q.S.__setitem__, "easy_mode", False)

    def test_the_chats_settings_reach_a_helper(self):
        q.set_chat_setting("chat-A", "easy_mode", True)
        q.TURN_CTX.sid = None                 # a helper's own turn has no sid
        q.TURN_CTX.settings_sid = "chat-A"
        self.assertTrue(q.chat_setting("easy_mode"))

    def test_and_the_grants_you_gave_for_this_chat(self):
        q.SESSION_RULES.pop("chat-A", None)
        self.addCleanup(q.SESSION_RULES.pop, "chat-A", None)
        q.add_session_rule("read_file", "*", "", sid="chat-A")
        q.TURN_CTX.sid = None
        q.TURN_CTX.settings_sid = "chat-A"
        self.assertTrue(q.session_rules())

    def test_the_chats_own_sid_still_wins(self):
        q.set_chat_setting("chat-A", "easy_mode", True)
        q.TURN_CTX.sid = "chat-B"
        q.TURN_CTX.settings_sid = "chat-A"
        self.assertFalse(q.chat_setting("easy_mode"),
                         "an answer in chat B must not read chat A's settings")
