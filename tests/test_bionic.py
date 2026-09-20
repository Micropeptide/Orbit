"""Bionic, the model host on this Mac: what it has, whether it is serving, and how
those models reach the picker and the Claude Code harness. Bionic is never really
asked here -- its CLI and its HTTP endpoint are both stood in for."""
import json, os, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import bionic as B
import harness as H
import providers as P

LS = [{"type": "llm", "modelKey": "qwen3.8-27b-mlx", "displayName": "Qwen3.8 27B",
       "maxContextLength": 262144, "vision": True, "trainedForToolUse": True},
      {"type": "llm", "modelKey": "small-1b", "displayName": "Small 1B", "maxContextLength": 32768},
      {"type": "embedding", "modelKey": "nomic-embed", "displayName": "Nomic Embed"}]
PS = [{"modelKey": "qwen3.8-27b-mlx", "displayName": "Qwen3.8 27B", "contextLength": 119552,
       "sizeBytes": 16081498475, "status": "idle", "lastUsedTime": 1_789_000_000_000}]


class Fake:
    """Bionic as it answers: `lms` output, and whether the server is up."""
    def __init__(self, up=False, port=1234, installed=True):
        self.up, self.port, self.installed, self.starts = up, port, installed, 0

    def lms(self, args, timeout=25):
        if not self.installed: return None
        if args[:2] == ["server", "status"]: return {"running": self.up, "port": self.port}
        if args == ["ls"]: return LS
        if args == ["ps"]: return PS
        return None

    def serving(self, p=None, timeout=1.0):
        return [m["modelKey"] for m in LS] if self.up and int(p or 0) == self.port else []

    def start(self, argv, **kw):
        self.starts += 1
        self.up = True
        class R: stdout = "Success!"; stderr = ""
        return R()


class BionicTest(unittest.TestCase):
    def use(self, fake):
        saved = {k: getattr(B, k) for k in ("_lms", "serving", "installed")}
        self.addCleanup(lambda: [setattr(B, k, v) for k, v in saved.items()])
        B._lms = fake.lms
        B.serving = fake.serving
        B.installed = lambda: fake.installed
        B._PORT.update(at=0.0, n=0)
        B._LIST.update(at=0.0, rows=[])
        B._PROBE.update(at=0.0, port=0, ids=[])
        self.addCleanup(B._PORT.update, at=0.0, n=0)
        self.addCleanup(B._LIST.update, at=0.0, rows=[])
        return fake


class TestWhatBionicHas(BionicTest):
    def test_only_models_you_can_talk_to_are_listed(self):
        self.use(Fake(up=True))
        rows = B.models(max_age=0)
        self.assertEqual([r["model"] for r in rows], ["qwen3.8-27b-mlx", "small-1b"])
        self.assertEqual(rows[0]["label"], "Qwen3.8 27B")

    def test_a_loaded_model_reports_the_window_it_actually_has(self):
        self.use(Fake(up=True))
        rows = {r["model"]: r for r in B.models(max_age=0)}
        self.assertEqual(rows["qwen3.8-27b-mlx"]["context"], 119552)   # as loaded
        self.assertTrue(rows["qwen3.8-27b-mlx"]["loaded"])
        self.assertEqual(rows["small-1b"]["context"], 32768)                      # as it would load
        self.assertFalse(rows["small-1b"]["loaded"])

    def test_nothing_at_all_when_bionic_is_not_installed(self):
        self.use(Fake(installed=False))
        self.assertEqual(B.models(max_age=0), [])
        self.assertEqual(B.ensure(), "")
        self.assertFalse(B.status()["installed"])


class TestWhatItHolds(BionicTest):
    def test_what_is_in_memory_and_how_much_it_costs(self):
        self.use(Fake(up=True))
        held = B.loaded(max_age=0)
        self.assertEqual([r["model"] for r in held], ["qwen3.8-27b-mlx"])
        self.assertEqual(held[0]["bytes"], 16_081_498_475)
        self.assertTrue(B.is_loaded("qwen3.8-27b-mlx"))
        self.assertFalse(B.is_loaded("small-1b"))

    def test_unloading_asks_bionic_and_forgets_what_it_knew(self):
        f = self.use(Fake(up=True))
        B.loaded(max_age=0)
        import subprocess
        said = {}
        def run(argv, **kw):
            said["argv"] = argv
            class R: returncode = 0; stdout = ""; stderr = ""
            return R()
        saved = subprocess.run
        subprocess.run = run
        self.addCleanup(setattr, subprocess, "run", saved)
        ok, why = B.unload("qwen3.8-27b-mlx")
        self.assertTrue(ok, why)
        self.assertEqual(said["argv"][1:], ["unload", "qwen3.8-27b-mlx"])
        self.assertEqual(B._PS["at"], 0.0)          # asked again next time


class TestLettingItGo(BionicTest):
    """Memory given back when nothing on this Mac has used a model for a while."""
    def use_with(self, **over):
        f = self.use(Fake(up=True))
        row = dict(PS[0], **over)
        saved = B._lms
        B._lms = lambda args, timeout=25: [row] if args == ["ps"] else saved(args, timeout)
        return f

    def test_a_model_nobody_has_used_can_go(self):
        self.use_with(lastUsedTime=(time.time() - 3600) * 1000)
        self.assertEqual([m["model"] for m in B.idle_models(20)], ["qwen3.8-27b-mlx"])
        self.assertEqual(B.idle_models(90), [])            # not idle for that long yet
        self.assertEqual(B.idle_models(0), [])             # 0 keeps it loaded

    def test_one_that_is_answering_right_now_is_left_alone(self):
        self.use_with(lastUsedTime=(time.time() - 3600) * 1000, status="generating")
        self.assertEqual(B.idle_models(20), [])

    def test_bionics_own_use_counts_not_just_orbits(self):
        # used a minute ago from Bionic itself: Orbit does not pull it out from under you
        self.use_with(lastUsedTime=(time.time() - 60) * 1000)
        self.assertEqual(B.idle_models(20), [])


class TestSwitchingTheServerOn(BionicTest):
    def test_a_server_that_is_off_is_started_once(self):
        f = self.use(Fake(up=False))
        import subprocess
        saved = subprocess.run
        subprocess.run = f.start
        self.addCleanup(setattr, subprocess, "run", saved)
        self.assertEqual(B.ensure(), "http://127.0.0.1:1234/v1")
        self.assertEqual(f.starts, 1)
        self.assertEqual(B.ensure(), "http://127.0.0.1:1234/v1")
        self.assertEqual(f.starts, 1)                      # already on: left alone

    def test_the_port_it_reports_is_the_one_used(self):
        self.use(Fake(up=True, port=4321))
        self.assertEqual(B.ensure(), "http://127.0.0.1:4321/v1")


class TestInThePicker(BionicTest):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-bionic-")
        os.makedirs(os.path.join(self.tmp, "config"))

    def test_models_appear_without_anyone_fetching_a_list(self):
        self.use(Fake(up=True))
        cat = P.catalogue(self.tmp, None, {})
        mine = [m for m in cat if m["provider"] == "bionic"]
        self.assertEqual([m["id"] for m in mine],
                         ["bionic:qwen3.8-27b-mlx", "bionic:small-1b"])
        self.assertTrue(all(m["ready"] for m in mine))     # no key to be missing

    def test_it_resolves_to_bionics_own_endpoint_not_the_local_server(self):
        self.use(Fake(up=True, port=4321))
        spec = P.resolve(self.tmp, "bionic:small-1b", None, {})
        self.assertEqual(spec["provider_cfg"]["base_url"], "http://127.0.0.1:4321/v1")
        self.assertEqual(spec["provider_cfg"]["kind"], "openai")

    def test_the_harness_offers_them_through_the_gateway_with_no_key(self):
        self.use(Fake(up=True))
        mine = [m for m in H.catalogue(self.tmp, {}, None) if m["model"].startswith("bionic/")]
        # a model never trained to call tools says so: it cannot drive the harness
        self.assertEqual([m["label"] for m in mine],
                         ["Qwen3.8 27B · Bionic", "Small 1B · no tool use · Bionic"])
        self.assertTrue(all(m["ready"] and m["format"] == "chat" for m in mine))
        pc = H.resolve(self.tmp, "harness:bionic/small-1b", {}, None)["provider_cfg"]
        self.assertTrue(pc["keyless"])
        self.assertFalse(pc["local"])                      # not MTPLX's endpoint
        self.assertEqual(pc["base"], "http://127.0.0.1:1234/v1")

    def test_no_bionic_no_provider(self):
        self.use(Fake(installed=False))
        self.assertEqual([m for m in P.catalogue(self.tmp, None, {}) if m["provider"] == "bionic"], [])
        self.assertEqual([m for m in H.catalogue(self.tmp, {}, None, include_unready=True)
                          if m["model"].startswith("bionic/")], [])


if __name__ == "__main__":
    unittest.main()
