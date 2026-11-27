"""Test offline del radar dell'auditor: nessuna chiave, nessuna rete, nessun git, nessun workflow.
Esegui:  python -m unittest -v test_radar_offline
"""
import os, sys, types, json, csv, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_TMP = tempfile.mkdtemp()
os.chdir(_TMP)

g = types.ModuleType("google"); g.genai = types.ModuleType("google.genai")
sys.modules.update({"google": g, "google.genai": g.genai})
import requests
def _no_network(*a, **k): raise RuntimeError("rete bloccata nei test")
requests.get = _no_network; requests.post = _no_network
import ai_auditor as aud
aud.time.sleep = lambda *_: None


def candles(n=300, start=100.0, step=0.0, vol=1000.0, last_vol=None):
    """Formato Coinbase: [time, low, high, open, close, volume], dal piu' recente al piu' vecchio."""
    rows = []
    for i in range(n):                       # i = 0 e' la candela piu' vecchia
        c = start + step * i
        v = last_vol if (last_vol is not None and i >= n - 24) else vol
        rows.append([1_700_000_000 + i * 3600, c * 0.995, c * 1.005, c, c, v])
    return list(reversed(rows))

class Resp:
    def __init__(self, data, code=200): self.data, self.status_code = data, code
    def json(self): return self.data

def fake_get(table):
    def _get(url, **k):
        pair = url.split("/products/")[1].split("/")[0]
        v = table[pair]
        if isinstance(v, Exception): raise v
        return v
    return _get


class TestScore(unittest.TestCase):
    base = dict(ret_7d_pct=0.0, dist_ema50_pct=0.0, dist_ema200_pct=0.0, rsi_1h=50.0, pressione_rilevata="NORMALE",
                volume_anomaly_vai=1.0, var_24h_pct=0.0, volume_eur_24h=5_000_000, atr_pct=1.0)
    def sc(self, **k): return aud.calcola_score_radar({**self.base, **k})
    def test_neutral_base(self): self.assertEqual(self.sc(), 50 + 8 + 4 + 6)
    def test_bounds(self):
        self.assertLessEqual(self.sc(ret_7d_pct=500, rsi_1h=50, volume_anomaly_vai=2, var_24h_pct=1), 100)
        self.assertGreaterEqual(self.sc(ret_7d_pct=-500, dist_ema50_pct=-9, dist_ema200_pct=-9, rsi_1h=80,
                                        pressione_rilevata="DISTRIBUZIONE", volume_eur_24h=10, atr_pct=9), 0)
    def test_momentum_monotonic(self): self.assertGreater(self.sc(ret_7d_pct=8), self.sc(ret_7d_pct=-8))
    def test_downtrend_penalised(self): self.assertGreater(self.sc(), self.sc(dist_ema50_pct=-3, dist_ema200_pct=-3))
    def test_overbought_penalised(self): self.assertLess(self.sc(rsi_1h=80), self.sc(rsi_1h=50))
    def test_distribution_penalised(self): self.assertLess(self.sc(pressione_rilevata="DISTRIBUZIONE"), self.sc())
    def test_illiquid_penalised(self):
        self.assertLess(self.sc(volume_eur_24h=100_000), self.sc(volume_eur_24h=500_000))
        self.assertLess(self.sc(volume_eur_24h=500_000), self.sc())
    def test_no_7d_or_200_ok(self): self.assertIsInstance(self.sc(ret_7d_pct=None, dist_ema200_pct=None), float)
    def test_deterministic(self): self.assertEqual(self.sc(ret_7d_pct=3.3), self.sc(ret_7d_pct=3.3))


class TestScan(unittest.TestCase):
    def test_metrics_and_ranking(self):
        table = {"UP-EUR": Resp(candles(step=0.2)), "DOWN-EUR": Resp(candles(start=160, step=-0.2)),
                 "FLAT-EUR": Resp(candles(step=0.0))}
        with mock.patch.object(aud.requests, "get", fake_get(table)):
            r = aud.scansiona_radar_altcoin_con_volumi(list(table))
        self.assertEqual(set(r), set(table)); self.assertEqual(aud.RADAR_ERRORI, [])
        for v in r.values():
            for k in ("prezzo", "var_24h_pct", "ret_7d_pct", "rsi_1h", "volume_anomaly_vai", "volume_eur_24h",
                      "atr_pct", "dist_ema50_pct", "dist_ema200_pct", "pressione_rilevata", "score", "rank"):
                self.assertIn(k, v)
        self.assertGreater(r["UP-EUR"]["ret_7d_pct"], 0); self.assertLess(r["DOWN-EUR"]["ret_7d_pct"], 0)
        self.assertEqual(r["DOWN-EUR"]["rank"], 3); self.assertEqual(sorted(v["rank"] for v in r.values()), [1, 2, 3])
        self.assertGreater(r["UP-EUR"]["score"], r["DOWN-EUR"]["score"])
        self.assertGreater(r["UP-EUR"]["dist_ema50_pct"], 0); self.assertLess(r["DOWN-EUR"]["dist_ema50_pct"], 0)
        self.assertGreater(r["FLAT-EUR"]["volume_eur_24h"], 0)
    def test_vai_accumulo_label(self):
        table = {"A-EUR": Resp(candles(vol=100, last_vol=400))}
        with mock.patch.object(aud.requests, "get", fake_get(table)):
            r = aud.scansiona_radar_altcoin_con_volumi(["A-EUR"])
        self.assertGreaterEqual(r["A-EUR"]["volume_anomaly_vai"], 1.8)
        self.assertEqual(r["A-EUR"]["pressione_rilevata"], "ACCUMULO")
    def test_errors_logged_per_pair(self):
        table = {"OK-EUR": Resp(candles()), "NF-EUR": Resp({"message": "NotFound"}, 404),
                 "SHORT-EUR": Resp(candles(n=10)), "BOOM-EUR": RuntimeError("timeout"), "BAD-EUR": Resp({"x": 1})}
        with mock.patch.object(aud.requests, "get", fake_get(table)):
            r = aud.scansiona_radar_altcoin_con_volumi(list(table))
        self.assertEqual(list(r), ["OK-EUR"])
        errs = dict(aud.RADAR_ERRORI)
        self.assertEqual(set(errs), {"NF-EUR", "SHORT-EUR", "BOOM-EUR", "BAD-EUR"})
        self.assertIn("404", errs["NF-EUR"]); self.assertIn("timeout", errs["BOOM-EUR"])
    def test_short_history_has_no_7d_or_200(self):
        table = {"S-EUR": Resp(candles(n=100))}
        with mock.patch.object(aud.requests, "get", fake_get(table)):
            r = aud.scansiona_radar_altcoin_con_volumi(["S-EUR"])
        self.assertIsNone(r["S-EUR"]["ret_7d_pct"]); self.assertIsNone(r["S-EUR"]["dist_ema200_pct"])
        self.assertIsInstance(r["S-EUR"]["score"], float)
    def test_errors_reset_each_scan(self):
        with mock.patch.object(aud.requests, "get", fake_get({"X-EUR": RuntimeError("e")})):
            aud.scansiona_radar_altcoin_con_volumi(["X-EUR"])
        with mock.patch.object(aud.requests, "get", fake_get({"Y-EUR": Resp(candles())})):
            aud.scansiona_radar_altcoin_con_volumi(["Y-EUR"])
        self.assertEqual(aud.RADAR_ERRORI, [])
    def test_flat_price_rsi_not_crash(self):
        with mock.patch.object(aud.requests, "get", fake_get({"F-EUR": Resp(candles(step=0))})):
            r = aud.scansiona_radar_altcoin_con_volumi(["F-EUR"])
        self.assertEqual(r["F-EUR"]["rsi_1h"], 50.0)


class TestInConfigAndCsv(unittest.TestCase):
    def setUp(self):
        if os.path.exists(aud.FILE_RADAR_CSV): os.remove(aud.FILE_RADAR_CSV)
        table = {"BTC-EUR": Resp(candles(step=0.1)), "NEAR-EUR": Resp(candles(step=0.3))}
        with mock.patch.object(aud.requests, "get", fake_get(table)):
            self.radar = aud.scansiona_radar_altcoin_con_volumi(list(table))
    def test_in_config_flag(self):
        aud.segna_asset_in_config(self.radar, {"assets": {"BTC-EUR": {}}})
        self.assertTrue(self.radar["BTC-EUR"]["in_config"]); self.assertFalse(self.radar["NEAR-EUR"]["in_config"])
        aud.segna_asset_in_config(self.radar, None)
        self.assertFalse(self.radar["BTC-EUR"]["in_config"])
    def test_csv_header_and_append(self):
        aud.segna_asset_in_config(self.radar, {"assets": {"BTC-EUR": {}}})
        self.assertTrue(aud.salva_radar_csv(self.radar)); self.assertTrue(aud.salva_radar_csv(self.radar))
        rows = list(csv.reader(open(aud.FILE_RADAR_CSV, encoding="utf-8")))
        self.assertEqual(rows[0], aud.RADAR_CSV_COLONNE); self.assertEqual(len(rows), 1 + 2 * 2)
        self.assertTrue(all(len(r) == len(aud.RADAR_CSV_COLONNE) for r in rows))
        d = dict(zip(rows[0], rows[1])); self.assertIn(d["Pair"], ("BTC-EUR", "NEAR-EUR")); self.assertTrue(d["Score"])
    def test_csv_empty_radar_writes_nothing(self):
        self.assertFalse(aud.salva_radar_csv({})); self.assertFalse(os.path.exists(aud.FILE_RADAR_CSV))
    def test_csv_write_error_is_not_fatal(self):
        with mock.patch("builtins.open", side_effect=OSError("disco pieno")):
            self.assertFalse(aud.salva_radar_csv(self.radar))
    def test_commit_csv_only_touches_csv_and_survives_git_errors(self):
        aud.salva_radar_csv(self.radar); calls = []
        def run(cmd, **k):
            calls.append(cmd); r = types.SimpleNamespace(stdout=" M radar_scansioni.csv\n", returncode=0); return r
        with mock.patch.object(aud.subprocess, "run", run):
            self.assertTrue(aud.commit_radar_csv())
        added = [c for c in calls if c[:2] == ["git", "add"]]
        self.assertEqual(added, [["git", "add", aud.FILE_RADAR_CSV]])
        self.assertFalse(any("config.json" in " ".join(c) for c in calls))
        with mock.patch.object(aud.subprocess, "run", side_effect=RuntimeError("push rifiutato")):
            self.assertFalse(aud.commit_radar_csv())          # nessuna eccezione


class FakeModels:
    def __init__(self, text, sink): self.text, self.sink = text, sink
    def generate_content(self, model, contents):
        self.sink.append(contents); return types.SimpleNamespace(text=self.text)

class TestAuditEndToEnd(unittest.TestCase):
    """esegui_audit con Gemini finto: il prompt e' corretto e nulla tocca config/ordini oltre al perimetro."""
    def setUp(self):
        for f in (aud.FILE_RADAR_CSV, aud.FILE_CONFIG, aud.FILE_PORTAFOGLIO, aud.FILE_DIARIO):
            if os.path.exists(f): os.remove(f)
        self.cfg = {"assets": {"BTC-EUR": {"grid_dist_buy": 0.015, "grid_dist_sell": 0.02, "target_weight_pct": 40.0,
                    "buy_conviction": 1.0, "sell_action": "tranche", "exit_strategy": "none", "is_active": True}},
                    "force_grid_realign": False}
        json.dump(self.cfg, open(aud.FILE_CONFIG, "w"))
        with open(aud.FILE_PORTAFOGLIO, "w") as f:
            f.write("Data,Saldo_EUR,Valore_Crypto_EUR,Valore_Totale_EUR\n2026-11-27,370,3,373\n")
        self.table = {p: Resp(candles(step=0.1)) for p in aud.ALTCOIN_CANDIDATE_RADAR}
        self.table["NEAR-EUR"] = Resp({"message": "x"}, 404); self.table["DOT-EUR"] = Resp({"message": "x"}, 404)
        self.table["SUI-EUR"] = RuntimeError("t")
        self.prompts, self.tg, self.git = [], [], []
        aud.GEMINI_API_KEY = "finta"
        aud.invia_telegram = lambda m: self.tg.append(m)
        aud.subprocess.run = lambda cmd, **k: (self.git.append(cmd), types.SimpleNamespace(stdout=" M x\n", returncode=0))[1]
    def run_audit(self, text):
        g.genai.Client = lambda api_key: types.SimpleNamespace(models=FakeModels(text, self.prompts))
        with mock.patch.object(aud.requests, "get", fake_get(self.table)):
            aud.esegui_audit()
    def test_prompt_content_and_no_config_change(self):
        self.run_audit("Report\n---JSON_CONFIG---\nNO_CHANGE\n---JSON_MEMORIA---\nNO_CHANGE")
        p = self.prompts[0]
        self.assertNotIn("0.025 - 0.035", p); self.assertNotIn("CARICO MEDIO", p)
        self.assertIn("0.005 e 0.02", p); self.assertIn("non proporli", p); self.assertIn('"score"', p)
        self.assertIn('"rank"', p); self.assertIn('"in_config": true', p); self.assertIn("NON è tracciato", p)
        self.assertEqual(json.load(open(aud.FILE_CONFIG)), self.cfg)                  # config.json invariato
        self.assertTrue(os.path.exists(aud.FILE_RADAR_CSV))                           # CSV scritto
        added = [c for c in self.git if c[:2] == ["git", "add"]]
        self.assertEqual(added, [["git", "add", aud.FILE_RADAR_CSV]])                 # solo il CSV
        self.assertIn("Coppie non lette", self.tg[0]); self.assertIn("NEAR-EUR (HTTP 404)", self.tg[0])
        self.assertNotIn("conferm", self.tg[0].lower())                               # nessuna approvazione richiesta
    def test_config_change_still_autonomous_and_validated(self):
        new = json.loads(json.dumps(self.cfg))
        new["assets"]["BTC-EUR"].update(grid_dist_buy=0.035, sell_action="liquidate_all", exit_strategy="market_sell")
        new["assets"]["PEPE-EUR"] = {"target_weight_pct": 10}
        self.run_audit("Report\n---JSON_CONFIG---\n" + json.dumps(new) + "\n---JSON_MEMORIA---\nNO_CHANGE")
        out = json.load(open(aud.FILE_CONFIG))
        a = out["assets"]["BTC-EUR"]
        self.assertEqual(a["grid_dist_buy"], 0.02)                                    # range
        self.assertEqual(a["sell_action"], "liquidate_all"); self.assertEqual(a["exit_strategy"], "market_sell")
        self.assertNotIn("PEPE-EUR", out["assets"])                                   # validatore invariato
        self.assertTrue(out["force_grid_realign"])
        self.assertTrue(any("riposiziona" in m for m in self.tg))
        self.assertTrue(any(c[:2] == ["git", "push"] for c in self.git))              # push autonomo, nessuna conferma
    def test_audit_survives_all_radar_errors(self):
        for p in list(self.table): self.table[p] = RuntimeError("down")
        self.run_audit("Report\n---JSON_CONFIG---\nNO_CHANGE\n---JSON_MEMORIA---\nNO_CHANGE")
        self.assertEqual(len(self.tg), 1); self.assertFalse(os.path.exists(aud.FILE_RADAR_CSV))


if __name__ == "__main__":
    unittest.main(verbosity=2)
