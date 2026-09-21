"""Two things the model never saw and one it waited too long for: the skills you have
saved, the cacheable front of a request, and a provider that stops sending."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q
import providers as P


class TestSkillsAreNamedInThePrompt(unittest.TestCase):
    def setUp(self):
        self.saved = q.skills_list
        self.addCleanup(setattr, q, "skills_list", self.saved)

    def fake(self, n, title="does a thing"):
        q.skills_list = lambda: [{"name": f"skill-{i}", "title": title, "chars": 100}
                                 for i in range(n)]

    def test_each_skill_is_named_with_what_it_is_for(self):
        self.fake(3)
        sec = q.skills_section()
        self.assertIn("- skill-0: does a thing", sec)
        self.assertIn("use_skill", sec)

    def test_no_skills_means_nothing_in_the_prompt(self):
        self.fake(0)
        self.assertEqual(q.skills_section(), "")

    def test_descriptions_are_dropped_before_names_are(self):
        self.fake(40, title="a description long enough to matter " * 3)
        sec = q.skills_section(budget=2000)
        self.assertIn("- skill-39", sec)                       # every name survives
        self.assertNotIn("long enough to matter", sec)         # the prose does not

    def test_a_list_too_long_even_for_names_says_how_many_are_left(self):
        self.fake(4000)
        sec = q.skills_section(budget=1500)
        self.assertLess(len(sec), 1600)
        self.assertIn("more (list_skills)", sec)

    def test_frontmatter_is_read_rather_than_shown(self):
        body = "---\nname: hoffman2\ndescription: Run compute on the cluster\n---\n\n# Hoffman2\n"
        self.assertEqual(q._skill_title(body), "Run compute on the cluster")
        self.assertEqual(q._skill_title("# Plain skill\n\ntext"), "Plain skill")


class TestTheCacheableFrontOfARequest(unittest.TestCase):
    def test_the_breakpoint_lands_on_the_last_message(self):
        msgs = [{"role": "user", "content": "a"},
                {"role": "assistant", "content": [{"type": "text", "text": "b"}]},
                {"role": "user", "content": "c"}]
        P._cache_breakpoint(msgs)
        self.assertNotIn("cache_control", str(msgs[0]))
        self.assertIn("cache_control", str(msgs[-1]))

    def test_it_moves_rather_than_accumulating(self):
        """There are only four breakpoints to spend, and a stale one in the middle pays
        to cache a prefix nobody will ask for again."""
        msgs = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
        P._cache_breakpoint(msgs)
        msgs.append({"role": "user", "content": "c"})
        P._cache_breakpoint(msgs)
        self.assertEqual(str(msgs).count("cache_control"), 1)
        self.assertIn("cache_control", str(msgs[-1]))

    def test_an_empty_conversation_does_not_break_it(self):
        msgs = []
        P._cache_breakpoint(msgs)
        self.assertEqual(msgs, [])


class TestAStalledStream(unittest.TestCase):
    def test_the_socket_is_tightened_once_tokens_arrive(self):
        class Sock:
            def __init__(self): self.t = None
            def settimeout(self, v): self.t = v
        class Resp:
            def __init__(self): self.fp = type("f", (), {"raw": type("r", (), {"_sock": Sock()})()})()
        r = Resp()
        self.assertTrue(q._tighten_stream(r, 120))
        self.assertEqual(r.fp.raw._sock.t, 120.0)

    def test_a_response_that_hides_its_socket_is_not_an_error(self):
        self.assertFalse(q._tighten_stream(object(), 120))

    def test_the_idle_window_is_a_setting(self):
        self.assertGreater(float(q.DEFAULTS["stream_idle_timeout_s"]), 0)
        self.assertGreater(float(q.DEFAULTS["first_token_timeout_s"]),
                           float(q.DEFAULTS["stream_idle_timeout_s"]),
                           "a cold local model takes minutes to the first token")


if __name__ == "__main__":
    unittest.main()
