"""Test offline: client Coinbase finto, nessuna chiave, nessuna rete, nessun workflow.
Esegui:  python -m unittest -v test_offline_stub
"""
import os, sys, types, json, tempfile, unittest
from datetime import datetime, timezone, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_TMP = tempfile.mkdtemp()
os.chdir(_TMP)   # nessun config.json / csv reali

# --- moduli esterni finti (nessuna dipendenza e nessuna rete) ---
class FakeClient:
    def __init__(self, *a, **k):
        self.orders_created, self.open_orders, self.summary = [], [], None
    def get_transaction_summary(self):
        if isinstance(self.summary, Exception): raise self.summary
        return self.summary
    def list_orders(self, **k):
        if isinstance(self.open_orders, Exception): raise self.open_orders
        return {"orders": self.open_orders}
    def create_order(self, **k):
        self.orders_created.append(k); return {"success": True}

cb = types.ModuleType("coinbase"); cbr = types.ModuleType("coinbase.rest")
cbr.RESTClient = FakeClient; cb.rest = cbr
sys.modules.update({"coinbase": cb, "coinbase.rest": cbr})
sys.modules.setdefault("joblib", types.ModuleType("joblib"))
g = types.ModuleType("google"); g.genai = types.ModuleType("google.genai")
sys.modules.update({"google": g, "google.genai": g.genai})

def _no_network(*a, **k): raise RuntimeError("rete bloccata nei test")
import requests
requests.get = _no_network; requests.post = _no_network

import bot_coinbase_github as bot
import ai_auditor as aud


_ORIG = {n: getattr(bot, n) for n in ("piazza_nuova_griglia", "cancella_ordini_pair", "controlla_saldi_globali",
         "recupera_ordini_pair", "ottieni_dati_mercato_avanzati")}

def reset(price_dec=None):
    for n, f in _ORIG.items(): setattr(bot, n, f)
    bot._FEE_CACHE = None; bot._PREC_CACHE.clear()
    bot._PREC_CACHE["ADA-EUR"] = 4          # quote_increment 0.0001
    if price_dec: bot._PREC_CACHE.update(price_dec)
    bot.client = FakeClient()
    bot.client.summary = {"fee_tier": {"maker_fee_rate": "0.0025", "taker_fee_rate": "0.005"}}
    bot.cancella_ordini_pair = lambda *a, **k: None
    bot.invia_telegram = lambda *a, **k: None
    bot.registra_su_diario_di_bordo = lambda *a, **k: None
    bot.resetta_sell_action_in_config = lambda *a, **k: None
    bot.MODELLO_ML = None
    bot.CONFIG_ASSETS.clear()
    bot.CONFIG_ASSETS["ADA-EUR"] = dict(grid_dist=0.03, grid_dist_sell=0.02, emoji="x", min_order_eur=5.0,
        decimals=1, target_weight_pct=20.0, buy_conviction=1.0, sell_action="tranche",
        is_active=True, exit_strategy="none")
    open("storico_portafoglio_giornaliero.csv", "w").close()

def balances(eur_tot=400.0, eur_disp=400.0, crypto=0.0, sym="ADA"):
    bot.controlla_saldi_globali = lambda: (eur_tot, eur_disp, {sym: crypto}, {sym: crypto})

def storico(giorni, cash, tot=1000.0):
    with open("storico_portafoglio_giornaliero.csv", "w") as f:
        f.write("Data,Valore_Totale_EUR,Saldo_EUR\n")
        for i in range(giorni): f.write(f"2026-11-{i+1:02d},{tot},{cash}\n")

def sides(side): return [o for o in bot.client.orders_created if o["side"] == side]
def px(o): return float(o["order_configuration"]["limit_limit_gtc"]["limit_price"])
def qty(o): return float(o["order_configuration"]["limit_limit_gtc"]["base_size"])
def grid(price=1.0, ema50=1.0, **kw):
    kw.setdefault("valore_totale_portafoglio", 1000.0)
    return bot.piazza_nuova_griglia("ADA-EUR", price, ema50=ema50, atr=0.01, **kw)
def order(side, price, hours):
    t = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    return {"side": side, "created_time": t, "order_configuration": {"limit_limit_gtc": {"limit_price": str(price)}}}


class TestFee(unittest.TestCase):
    def setUp(self): reset()
    def test_fee_dict_fraction(self):
        self.assertEqual(bot.ottieni_fee_coinbase(), (0.0025, 0.005))
    def test_fee_percent_normalised(self):
        bot._FEE_CACHE = None
        bot.client.summary = {"fee_tier": {"maker_fee_rate": "0.4", "taker_fee_rate": "0.6"}}
        m, t = bot.ottieni_fee_coinbase(); self.assertAlmostEqual(m, 0.004); self.assertAlmostEqual(t, 0.006)
    def test_fee_object_attrs(self):
        bot._FEE_CACHE = None
        ft = types.SimpleNamespace(maker_fee_rate="0.0015", taker_fee_rate="0.0025")
        bot.client.summary = types.SimpleNamespace(fee_tier=ft)
        self.assertEqual(bot.ottieni_fee_coinbase(), (0.0015, 0.0025))
    def test_fee_fallback_on_error(self):
        bot._FEE_CACHE = None; bot.client.summary = RuntimeError("api down")
        self.assertEqual(bot.ottieni_fee_coinbase(), (bot.FEE_MAKER_DEFAULT, bot.FEE_TAKER_DEFAULT))
    def test_fee_fallback_on_missing_fields(self):
        bot._FEE_CACHE = None; bot.client.summary = {"fee_tier": {}}
        self.assertEqual(bot.ottieni_fee_coinbase(), (0.0025, 0.005))
    def test_fee_cached_once(self):
        bot.ottieni_fee_coinbase(); bot.client.summary = RuntimeError("x")
        self.assertEqual(bot.ottieni_fee_coinbase(), (0.0025, 0.005))

class TestDistanze(unittest.TestCase):
    def setUp(self): reset()
    def test_limits_default_tier(self):
        mb, xb, ms, xs = bot.limiti_distanze()
        self.assertAlmostEqual(mb, 0.005); self.assertAlmostEqual(xb, 0.02)
        self.assertAlmostEqual(ms, 0.018); self.assertAlmostEqual(xs, 0.05)
    def test_limits_low_fee_tier(self):
        bot._FEE_CACHE = (0.0005, 0.001)
        mb, xb, ms, xs = bot.limiti_distanze()
        self.assertAlmostEqual(mb, 0.001); self.assertAlmostEqual(ms, 0.003)
    def test_limits_high_fee_tier_floor_rises(self):
        bot._FEE_CACHE = (0.006, 0.012)
        mb, xb, ms, xs = bot.limiti_distanze()
        self.assertAlmostEqual(mb, 0.012); self.assertAlmostEqual(ms, 0.036); self.assertGreaterEqual(xb, mb)
    def test_buy_capped_2pct_in_config_3pct(self):
        balances(); grid(price=1.0, ema50=1.0)
        self.assertAlmostEqual(px(sides("BUY")[0]), 0.98, places=4)
    def test_buy_capped_2pct_in_downtrend_and_high_vol(self):
        balances(); bot.MODELLO_ML = mock.Mock(); bot.MODELLO_ML.predict.return_value = [1]
        grid(price=0.95, ema50=1.0)   # sotto EMA50: il vecchio codice allargava fino a 4,5%+
        self.assertAlmostEqual(px(sides("BUY")[0]), 0.95 * 0.98, places=4)
    def test_buy_never_below_round_trip_fee(self):
        balances(); bot.CONFIG_ASSETS["ADA-EUR"]["grid_dist"] = 0.001; grid()
        self.assertAlmostEqual(px(sides("BUY")[0]), 0.995, places=4)
    def test_sell_floor_and_cap(self):
        balances(crypto=100.0); bot.CONFIG_ASSETS["ADA-EUR"]["grid_dist_sell"] = 0.001; grid()
        self.assertAlmostEqual(px(sides("SELL")[0]), 1.018, places=4)
        reset(); balances(crypto=100.0); bot.CONFIG_ASSETS["ADA-EUR"]["grid_dist_sell"] = 0.20; grid()
        self.assertAlmostEqual(px(sides("SELL")[0]), 1.05, places=4)

class TestPrecisione(unittest.TestCase):
    def setUp(self): reset()
    def _resp(self, qi):
        r = mock.Mock(status_code=200); r.json.return_value = {"quote_increment": qi}; return r
    def test_ada_four_decimals(self):
        with mock.patch.object(bot.requests, "get", return_value=self._resp("0.0001")):
            self.assertEqual(bot.formatta_prezzo("ADA-EUR", 0.38274), "0.3827")
    def test_doge_five_decimals(self):
        with mock.patch.object(bot.requests, "get", return_value=self._resp("0.00001")):
            self.assertEqual(bot.formatta_prezzo("DOGE-EUR", 0.123456), "0.12346")
    def test_btc_two_decimals_and_integer_increment(self):
        with mock.patch.object(bot.requests, "get", return_value=self._resp("0.01")):
            self.assertEqual(bot.formatta_prezzo("BTC-EUR", 81234.5678), "81234.57")
        with mock.patch.object(bot.requests, "get", return_value=self._resp("1")):
            self.assertEqual(bot.formatta_prezzo("X-EUR", 12.7), "13")
    def test_fallback_when_api_fails(self):
        bot._PREC_CACHE.clear()
        self.assertEqual(bot.ottieni_decimali_prezzo("ZZZ-EUR"), 2)
    def test_order_price_uses_increment(self):
        reset({"ADA-EUR": 4}); balances(); grid(price=0.38274)
        self.assertEqual(sides("BUY")[0]["order_configuration"]["limit_limit_gtc"]["limit_price"], "0.3751")

class TestAntiCash(unittest.TestCase):
    def setUp(self): reset(); bot.CONFIG_ASSETS["ADA-EUR"]["target_weight_pct"] = 25.0
    def test_cash_history(self):
        storico(3, 990); self.assertTrue(bot.cash_alto_da_giorni())
        storico(2, 990); self.assertFalse(bot.cash_alto_da_giorni())       # meno di 3 giorni
        storico(3, 600); self.assertFalse(bot.cash_alto_da_giorni())       # cash 60%
    def test_tranche_active(self):
        storico(3, 990); balances(eur_tot=990, eur_disp=990); grid(price=1.0, ema50=1.0, valore_totale_portafoglio=1000.0)
        b = sides("BUY")[0]
        self.assertAlmostEqual(px(b), 0.995, places=3)                       # 0,5% sotto spot
        self.assertLessEqual(qty(b) * px(b), 99.0 + 0.5)                     # <= 10% cash libero
    def test_tranche_off_without_history(self):
        storico(1, 990); balances(eur_tot=990, eur_disp=990); grid(valore_totale_portafoglio=1000.0)
        self.assertAlmostEqual(px(sides("BUY")[0]), 0.98, places=3)
    def test_tranche_off_when_live_cash_low(self):
        storico(3, 990); balances(eur_tot=500, eur_disp=500); grid(valore_totale_portafoglio=1000.0)
        self.assertAlmostEqual(px(sides("BUY")[0]), 0.98, places=3)
    def test_tranche_off_in_downtrend(self):
        storico(3, 990); balances(eur_tot=990, eur_disp=990); grid(price=0.90, ema50=1.0, valore_totale_portafoglio=1000.0)
        self.assertAlmostEqual(px(sides("BUY")[0]), 0.90 * 0.98, places=3)
    def test_tranche_off_when_buy_not_allowed(self):
        storico(3, 990); balances(eur_tot=990, eur_disp=990); grid(autorizza_buy=False, valore_totale_portafoglio=1000.0)
        self.assertEqual(sides("BUY"), [])

class TestOverweight(unittest.TestCase):
    def setUp(self): reset()
    def test_function(self):
        self.assertTrue(bot.e_sovrappesato(250, 1000, 20))     # budget 200, 125% = 250
        self.assertFalse(bot.e_sovrappesato(249, 1000, 20))
        self.assertFalse(bot.e_sovrappesato(900, 1000, 0))     # target 0: niente cap
    def test_no_buy_but_sell_kept_at_normal_tranche(self):
        balances(eur_tot=300, eur_disp=300, crypto=300.0)     # 300 ADA a 1 EUR = 300 > 250
        grid(price=1.0, valore_totale_portafoglio=1000.0)
        self.assertEqual(sides("BUY"), [])
        s = sides("SELL"); self.assertEqual(len(s), 1)
        self.assertGreater(qty(s[0]), 0)
    def test_buy_allowed_below_cap(self):
        balances(eur_tot=700, eur_disp=700, crypto=100.0); grid(valore_totale_portafoglio=1000.0)
        self.assertEqual(len(sides("BUY")), 1)

class TestStaleRealign(unittest.TestCase):
    def setUp(self): reset()
    def test_no_buy_means_stale_unless_required_existing(self):
        bot.client.open_orders = []
        self.assertTrue(bot.ordine_buy_obsoleto("ADA-EUR", 1.0))
        self.assertFalse(bot.ordine_buy_obsoleto("ADA-EUR", 1.0, richiedi_esistente=True))
    def test_fresh_close_buy_is_valid(self):
        bot.client.open_orders = [order("BUY", 0.98, 2)]
        self.assertFalse(bot.ordine_buy_obsoleto("ADA-EUR", 1.0))
    def test_old_buy_36h(self):
        bot.client.open_orders = [order("BUY", 0.98, 37)]
        self.assertTrue(bot.ordine_buy_obsoleto("ADA-EUR", 1.0))
        bot.client.open_orders = [order("BUY", 0.98, 35)]
        self.assertFalse(bot.ordine_buy_obsoleto("ADA-EUR", 1.0))
    def test_drift_over_4pct(self):
        bot.client.open_orders = [order("BUY", 0.95, 2)]
        self.assertTrue(bot.ordine_buy_obsoleto("ADA-EUR", 1.0))         # 5% sotto
        bot.client.open_orders = [order("BUY", 0.97, 2)]
        self.assertFalse(bot.ordine_buy_obsoleto("ADA-EUR", 1.0))        # 3% sotto
    def test_api_error_does_nothing(self):
        bot.client.open_orders = RuntimeError("boom")
        self.assertFalse(bot.ordine_buy_obsoleto("ADA-EUR", 1.0))
    def test_sell_orders_ignored(self):
        bot.client.open_orders = [order("SELL", 1.02, 100)]
        self.assertTrue(bot.ordine_buy_obsoleto("ADA-EUR", 1.0))         # nessun BUY

class TestGestioneAsset(unittest.TestCase):
    """esegui_gestione_asset con mercato e ordini finti."""
    def setUp(self):
        reset(); self.calls = []
        bot.piazza_nuova_griglia = lambda **k: self.calls.append(k)
        bot.cancella_ordini_pair = lambda *a, **k: self.calls.append(("cancel", a, k))
    def run_asset(self, price=1.0, ema50=1.0, atr=0.01, ids=("b", "s"), crypto=0.0, eur=400.0, force=False, tot=1000.0):
        bot.ottieni_dati_mercato_avanzati = lambda p: (price, ema50, atr, 0.0, 0.01, 50.0, 1.0)
        balances(eur_tot=eur, eur_disp=eur, crypto=crypto)
        bot.recupera_ordini_pair = lambda p: ids
        return bot.esegui_gestione_asset("ADA-EUR", tot, forza_realign=force)
    def test_force_flag_with_fresh_buy_does_not_reset_pivot(self):
        bot.client.open_orders = [order("BUY", 0.98, 3)]
        self.run_asset(force=True)
        self.assertEqual([c for c in self.calls if isinstance(c, dict)], [])
    def test_force_flag_with_old_buy_realigns(self):
        bot.client.open_orders = [order("BUY", 0.98, 40)]
        self.run_asset(force=True)
        self.assertEqual(len(self.calls), 1)
    def test_force_flag_missing_sell_with_crypto_realigns(self):
        bot.client.open_orders = [order("BUY", 0.98, 3)]
        self.run_asset(force=True, ids=("b", None), crypto=100.0)
        self.assertEqual(len(self.calls), 1)
    def test_force_flag_missing_sell_without_crypto_no_realign(self):
        bot.client.open_orders = [order("BUY", 0.98, 3)]
        self.run_asset(force=True, ids=("b", None), crypto=0.0)
        self.assertEqual(self.calls, [])
    def test_stale_buy_realigns_without_flag(self):
        bot.client.open_orders = [order("BUY", 0.90, 3)]    # 10% sotto spot
        self.run_asset(); self.assertEqual(len(self.calls), 1)
    def test_valid_buy_untouched(self):
        bot.client.open_orders = [order("BUY", 0.985, 3)]
        self.run_asset(); self.assertEqual(self.calls, [])
    def test_missing_buy_restored(self):
        self.run_asset(ids=(None, "s")); self.assertEqual(len(self.calls), 1)
    def test_init_grid_when_empty(self):
        self.run_asset(ids=(None, None)); self.assertEqual(len(self.calls), 1)

class TestDrop(unittest.TestCase):
    """Scenario di calo: prezzo sotto EMA50 - 2 ATR."""
    def setUp(self):
        reset(); self.calls = []
        bot.piazza_nuova_griglia = lambda **k: self.calls.append(k)
        bot.cancella_ordini_pair = lambda *a, **k: None
        bot.ottieni_dati_mercato_avanzati = lambda p: (0.90, 1.0, 0.02, -0.1, 0.05, 30.0, 1.0)  # floor 0.96
        balances(crypto=100.0)
    def test_circuit_breaker_blocks_buy_once(self):
        bot.recupera_ordini_pair = lambda p: ("b", "s")
        bot.client.open_orders = [order("BUY", 0.98, 3)]
        bot.esegui_gestione_asset("ADA-EUR", 1000.0)
        self.assertEqual(len(self.calls), 1); self.assertFalse(self.calls[0]["autorizza_buy"])
    def test_no_repeated_sell_replacement_while_blocked(self):
        bot.recupera_ordini_pair = lambda p: (None, "s")     # BUY gia' cancellato dal breaker
        bot.esegui_gestione_asset("ADA-EUR", 1000.0)
        self.assertEqual(self.calls, [])                      # niente piu' re-place a ogni run
    def test_real_grid_in_drop_places_no_buy_and_sell_ok(self):
        reset(); bot.cancella_ordini_pair = lambda *a, **k: None
        balances(crypto=200.0)
        grid(price=0.90, ema50=1.0, autorizza_buy=False)
        self.assertEqual(sides("BUY"), []); self.assertEqual(len(sides("SELL")), 1)
        self.assertGreaterEqual(px(sides("SELL")[0]), 0.90 * 1.018 - 1e-9)
    def test_drop_buy_stays_within_2pct_when_allowed(self):
        reset(); bot.cancella_ordini_pair = lambda *a, **k: None; balances()
        grid(price=0.90, ema50=1.0, autorizza_buy=True)
        self.assertGreaterEqual(px(sides("BUY")[0]), 0.90 * 0.98 - 1e-4)
    def test_progressive_drop_never_exceeds_overweight(self):
        """Se il bot continua a comprare in calo, l'esposizione si ferma al 125% del target."""
        reset(); bot.cancella_ordini_pair = lambda *a, **k: None
        crypto, eur, tot_buys = 0.0, 400.0, 0
        for price in [1.0, 0.97, 0.94, 0.91, 0.88, 0.85, 0.82, 0.79]:
            bot.client.orders_created.clear(); balances(eur_tot=eur, eur_disp=eur, crypto=crypto)
            valore = eur + crypto * price
            grid(price=price, ema50=price * 1.01, valore_totale_portafoglio=valore)
            for b in sides("BUY"):            # ipotesi peggiore: ogni BUY si riempie
                cost = qty(b) * px(b); crypto += qty(b); eur -= cost; tot_buys += 1
        valore = eur + crypto * price
        self.assertLessEqual(crypto * price, valore * 0.20 * 1.25 + 25.0)   # tetto + una tranche
        self.assertGreater(tot_buys, 0)

class TestValidator(unittest.TestCase):
    ATT = {"assets": {"BTC-EUR": {"grid_dist_buy": 0.015, "grid_dist_sell": 0.02, "target_weight_pct": 40.0,
                                  "buy_conviction": 1.0, "sell_action": "tranche", "exit_strategy": "none", "is_active": True},
                       "ADA-EUR": {"grid_dist_buy": 0.015, "grid_dist_sell": 0.02, "target_weight_pct": 30.0,
                                   "buy_conviction": 1.0, "sell_action": "tranche", "exit_strategy": "none", "is_active": True}}}
    def prop(self, **chg):
        import copy; n = copy.deepcopy(self.ATT); n["assets"]["BTC-EUR"].update(chg); return n
    def test_ranges_clamped(self):
        out, note = aud.valida_config(self.prop(grid_dist_buy=0.10, grid_dist_sell=0.001, buy_conviction=9, target_weight_pct=-5), self.ATT)
        a = out["assets"]["BTC-EUR"]
        self.assertEqual(a["grid_dist_buy"], 0.02); self.assertEqual(a["grid_dist_sell"], 0.018)
        self.assertEqual(a["buy_conviction"], 2.0); self.assertEqual(a["target_weight_pct"], 0.0)
        self.assertGreaterEqual(len(note), 4)
    def test_valid_values_untouched(self):
        out, note = aud.valida_config(self.prop(grid_dist_buy=0.01), self.ATT)
        self.assertEqual(out["assets"]["BTC-EUR"]["grid_dist_buy"], 0.01); self.assertEqual(note, [])
    def test_liquidate_all_and_market_sell_allowed(self):
        out, _ = aud.valida_config(self.prop(sell_action="liquidate_all", exit_strategy="market_sell"), self.ATT)
        self.assertEqual(out["assets"]["BTC-EUR"]["sell_action"], "liquidate_all")
        self.assertEqual(out["assets"]["BTC-EUR"]["exit_strategy"], "market_sell")
    def test_scale_out_and_soft_exit_allowed(self):
        out, _ = aud.valida_config(self.prop(sell_action="scale_out", exit_strategy="soft_exit"), self.ATT)
        self.assertEqual(out["assets"]["BTC-EUR"]["sell_action"], "scale_out")
    def test_unknown_values_reverted(self):
        out, note = aud.valida_config(self.prop(sell_action="yolo", exit_strategy="nuke"), self.ATT)
        self.assertEqual(out["assets"]["BTC-EUR"]["sell_action"], "tranche")
        self.assertEqual(out["assets"]["BTC-EUR"]["exit_strategy"], "none"); self.assertTrue(note)
    def test_new_asset_ignored(self):
        n = self.prop(); n["assets"]["PEPE-EUR"] = {"target_weight_pct": 10}
        out, note = aud.valida_config(n, self.ATT)
        self.assertNotIn("PEPE-EUR", out["assets"]); self.assertTrue(any("PEPE" in x for x in note))
    def test_weights_over_100_discarded(self):
        import copy
        att = copy.deepcopy(self.ATT); att["assets"]["SOL-EUR"] = dict(att["assets"]["ADA-EUR"], target_weight_pct=20.0)
        n = copy.deepcopy(att)
        for v in n["assets"].values(): v["target_weight_pct"] = 40.0              # 3 x 40 = 120%
        out, note = aud.valida_config(n, att)
        self.assertIsNone(out); self.assertTrue(any("100" in x for x in note))
    def test_non_numeric_does_not_crash(self):
        out, note = aud.valida_config(self.prop(grid_dist_buy="abc"), self.ATT)
        self.assertIsNotNone(out); self.assertTrue(note)
    def test_garbage_config_rejected(self):
        self.assertIsNone(aud.valida_config({"foo": 1}, self.ATT)[0])
        self.assertIsNone(aud.valida_config(None, self.ATT)[0])
    def test_removed_asset_kept_from_current(self):
        n = {"assets": {"BTC-EUR": self.ATT["assets"]["BTC-EUR"]}}
        out, _ = aud.valida_config(n, self.ATT); self.assertIn("ADA-EUR", out["assets"])

class TestNotificheTelegram(unittest.TestCase):
    def setUp(self): reset()
    def test_ordine_limite_piazzato_non_notifica_ma_ordina_e_logga(self):
        msgs, diario = [], []
        bot.invia_telegram = lambda m, *a, **k: msgs.append(m)
        bot.registra_su_diario_di_bordo = lambda *a, **k: diario.append(1)
        balances(); grid(price=1.0, ema50=1.0)
        self.assertEqual(len(sides("BUY")), 1)      # l'ordine viene piazzato come prima
        self.assertEqual(msgs, [])                  # nessun Telegram per ordini non eseguiti
        self.assertEqual(len(diario), 1)            # il diario resta aggiornato

if __name__ == "__main__":
    unittest.main(verbosity=2)
