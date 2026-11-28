"""Test offline per KPI esecuzione e allarme anti-cassa (idea 3: solo report, nessun trading).
Nessuna rete, nessuna chiave, nessun workflow. Esegui:  python -m unittest -v test_kpi_report
"""
import os, sys, types, tempfile, unittest
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_TMP = tempfile.mkdtemp()
os.chdir(_TMP)

class FakeClient:
    def __init__(self, *a, **k):
        self.fills_response = {"fills": [], "cursor": None}
        self.calls = []
    def get_fills(self, **k):
        self.calls.append(k)
        if isinstance(self.fills_response, Exception):
            raise self.fills_response
        return self.fills_response

cb = types.ModuleType("coinbase"); cbr = types.ModuleType("coinbase.rest")
cbr.RESTClient = FakeClient; cb.rest = cbr
sys.modules.update({"coinbase": cb, "coinbase.rest": cbr})
sys.modules.setdefault("joblib", types.ModuleType("joblib"))

def _no_network(*a, **k): raise RuntimeError("rete bloccata nei test")
import requests
requests.get = _no_network; requests.post = _no_network

import bot_coinbase_github as bot


def fill(time, product="ADA-EUR", side="BUY", size=1.0, price=1.0, fee=0.0, liq="MAKER"):
    return {"time": time, "product": product, "side": side, "size": size,
            "price": price, "commission": fee, "liquidity": liq}

def iso(giorni_fa):
    return (datetime.now(timezone.utc) - timedelta(days=giorni_fa)).isoformat()

def scrivi_storico(righe):
    """righe: lista di (data, saldo_eur, valore_totale)."""
    with open(bot.FILE_PORTAFOGLIO_GIORNALIERO, "w", encoding="utf-8") as f:
        f.write("Data,Saldo_EUR,Valore_Crypto_EUR,Valore_Totale_EUR\n")
        for d, cash, tot in righe:
            f.write(f"{d},{cash:.2f},{tot-cash:.2f},{tot:.2f}\n")

def reset():
    bot.client = FakeClient()
    bot.invia_telegram = lambda *a, **k: None
    for p in (bot.FILE_PORTAFOGLIO_GIORNALIERO, bot.FILE_FLAG_ALERT_CASSA, bot.FILE_FLAG_AVVISO_SC, "report_domenica_inviato.txt"):
        if os.path.exists(p):
            os.remove(p)


class TestNormalizzaFill(unittest.TestCase):
    def test_da_dict(self):
        nf = bot._normalizza_fill({"trade_time": "2026-11-28T10:00:00Z", "product_id": "SOL-EUR",
                                   "side": "buy", "size": "0.5", "price": "65.0",
                                   "commission": "0.02", "liquidity_indicator": "maker"})
        self.assertEqual(nf["side"], "BUY")
        self.assertEqual(nf["liquidity"], "MAKER")
        self.assertAlmostEqual(nf["size"], 0.5)
        self.assertAlmostEqual(nf["commission"], 0.02)
    def test_da_oggetto_sdk(self):
        class O: pass
        o = O(); o.trade_time = "t"; o.product_id = "P"; o.side = "SELL"
        o.size = 1; o.price = 2; o.commission = 0.1; o.liquidity_indicator = "TAKER"
        self.assertEqual(bot._normalizza_fill(o)["product"], "P")
    def test_spazzatura_non_esplode(self):
        self.assertIsNone(bot._normalizza_fill({"size": "abc"}))


class TestKpiFills(unittest.TestCase):
    def setUp(self): reset()

    def test_vuoto(self):
        k = bot.calcola_kpi_fills([], giorni=7)
        self.assertEqual(k["n_fill"], 0)
        self.assertEqual(k["pnl_tot"], 0.0)

    def test_round_trip_fifo_con_fee(self):
        fills = [
            fill(iso(2), side="BUY", size=10.0, price=1.00, fee=0.03),   # costo 10.03 -> 1.003/u
            fill(iso(1), side="SELL", size=10.0, price=1.02, fee=0.03),  # ricavo 10.20-0.03
        ]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertEqual(k["n_fill"], 2)
        self.assertEqual(k["n_buy"], 1)
        self.assertEqual(k["n_sell"], 1)
        self.assertAlmostEqual(k["fee"], 0.06, places=6)
        # pnl = 10*(1.02-1.003) - 0.03 = 0.17 - 0.03 = 0.14
        self.assertAlmostEqual(k["pnl_tot"], 0.14, places=6)
        self.assertAlmostEqual(k["pnl_7d"], 0.14, places=6)

    def test_fifo_piu_lotti(self):
        fills = [
            fill(iso(4), side="BUY", size=10.0, price=1.00, fee=0.0),
            fill(iso(3), side="BUY", size=10.0, price=1.10, fee=0.0),
            fill(iso(2), side="SELL", size=10.0, price=1.20, fee=0.0),   # chiude lotto a 1.00: +2.0
        ]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertAlmostEqual(k["pnl_tot"], 2.0, places=6)

    def test_finestra_7_giorni_esclude_vecchi(self):
        fills = [
            fill(iso(30), side="BUY", size=10.0, price=1.0, fee=0.10),
            fill(iso(29), side="SELL", size=10.0, price=1.1, fee=0.10),  # +0.8 ma fuori finestra
            fill(iso(1), side="BUY", size=1.0, price=1.0, fee=0.01),
        ]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertEqual(k["n_fill"], 1)                 # solo il fill recente
        self.assertAlmostEqual(k["pnl_7d"], 0.0, places=6)
        self.assertAlmostEqual(k["pnl_tot"], 0.80, places=6)
        self.assertAlmostEqual(k["fee_tot"], 0.21, places=6)
        self.assertAlmostEqual(k["fee"], 0.01, places=6)

    def test_quota_taker(self):
        fills = [
            fill(iso(1), side="BUY", size=1.0, price=100.0, liq="MAKER"),
            fill(iso(1), side="SELL", size=1.0, price=100.0, liq="TAKER"),
        ]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertAlmostEqual(k["taker_pct"], 50.0, places=3)

    def test_vendita_senza_lotto_non_esplode(self):
        fills = [fill(iso(1), side="SELL", size=5.0, price=1.0, fee=0.01)]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        # costo sconosciuto: niente P/L, nemmeno la fee come perdita
        self.assertAlmostEqual(k["pnl_tot"], 0.0, places=6)
        self.assertEqual(k["vendite_senza_costo_7d"], 1)
        self.assertAlmostEqual(k["valore_senza_costo_7d"], 5.0, places=6)

    def test_vendita_parzialmente_abbinata(self):
        # esempio di Marco: vendita 2 unità a 10€, un solo lotto noto a 9€, fee totale 1,50€
        # -> P/L confermato solo sull'unità nota: 1*(10-9) - 0,75 (quota fee) = +0,25; l'altra unità sconosciuta
        fills = [
            fill(iso(2), side="BUY", size=1.0, price=9.0, fee=0.0),
            fill(iso(1), side="SELL", size=2.0, price=10.0, fee=1.50),
        ]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertAlmostEqual(k["pnl_tot"], 0.25, places=6)
        self.assertAlmostEqual(k["pnl_7d"], 0.25, places=6)
        self.assertEqual(k["vendite_parziali_7d"], 1)
        self.assertEqual(k["vendite_senza_costo_7d"], 0)   # parziale non è "senza costo"
        self.assertEqual(k["vendite_sotto_costo_7d"], 0)   # +0,25 non è una perdita

    def test_input_ordinato_da_solo(self):
        fills = [
            fill(iso(1), side="SELL", size=10.0, price=1.2, fee=0.0),
            fill(iso(2), side="BUY", size=10.0, price=1.0, fee=0.0),
        ]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertAlmostEqual(k["pnl_tot"], 2.0, places=6)     # buy prima del sell dopo il sort


class TestRecuperaFills(unittest.TestCase):
    def setUp(self): reset()

    def test_paginazione(self):
        pagine = [
            {"fills": [{"trade_time": "t1", "product_id": "P", "side": "BUY", "size": 1,
                        "price": 1, "commission": 0, "liquidity_indicator": "MAKER"}], "cursor": "c2"},
            {"fills": [{"trade_time": "t2", "product_id": "P", "side": "SELL", "size": 1,
                        "price": 1, "commission": 0, "liquidity_indicator": "TAKER"}], "cursor": None},
        ]
        chiamate = {"n": 0}
        def fake_get(**k):
            r = pagine[chiamate["n"]]; chiamate["n"] += 1; return r
        bot.client.get_fills = fake_get
        fills = bot.recupera_fills("2026-11-01")
        self.assertEqual(chiamate["n"], 2)          # si ferma quando il cursor finisce
        self.assertEqual(len(fills), 2)
        self.assertEqual(fills[1]["liquidity"], "TAKER")

    def test_errore_api_ritorna_vuoto(self):
        bot.client.fills_response = RuntimeError("api giu")
        self.assertEqual(bot.recupera_fills("2026-11-01"), [])


class TestStatisticheCassa(unittest.TestCase):
    def setUp(self): reset()

    def test_media_e_consecutivi(self):
        scrivi_storico([("2026-11-20", 900, 1000), ("2026-11-21", 850, 1000),
                        ("2026-11-22", 500, 1000), ("2026-11-23", 900, 1000), ("2026-11-24", 950, 1000)])
        s = bot.statistiche_cassa(giorni=7)
        self.assertEqual(s["n_giorni"], 5)
        self.assertAlmostEqual(s["media_pct"], 82.0, places=3)
        self.assertEqual(s["giorni_sopra_soglia"], 4)
        self.assertEqual(s["consecutivi_sopra_soglia"], 2)   # 23 e 24; il 22 spezza

    def test_file_mancante(self):
        s = bot.statistiche_cassa(giorni=7)
        self.assertEqual(s["n_giorni"], 0)

    def test_righe_malformate_saltate(self):
        with open(bot.FILE_PORTAFOGLIO_GIORNALIERO, "w") as f:
            f.write("Data,Saldo_EUR,Valore_Crypto_EUR,Valore_Totale_EUR\n")
            f.write("2026-11-20,abc,,0\n")
            f.write("2026-11-21,900,100,1000\n")
        s = bot.statistiche_cassa(giorni=7)
        self.assertEqual(s["n_giorni"], 1)
        self.assertAlmostEqual(s["media_pct"], 90.0, places=3)


class TestAllarmeCassa(unittest.TestCase):
    def setUp(self): reset()

    def test_scatta_dopo_3_giorni(self):
        msgs = []
        bot.invia_telegram = lambda m, *a, **k: msgs.append(m)
        scrivi_storico([(f"2026-11-{d:02d}", 900, 1000) for d in (20, 21, 22)])
        self.assertTrue(bot.controlla_allarme_cassa())
        self.assertEqual(len(msgs), 1)
        self.assertIn("ALLARME CASSA", msgs[0])

    def test_non_scatta_sotto_3_giorni(self):
        msgs = []
        bot.invia_telegram = lambda m, *a, **k: msgs.append(m)
        scrivi_storico([(f"2026-11-{d:02d}", 900, 1000) for d in (21, 22)])
        self.assertFalse(bot.controlla_allarme_cassa())
        self.assertEqual(msgs, [])

    def test_non_scatta_se_interrotto(self):
        msgs = []
        bot.invia_telegram = lambda m, *a, **k: msgs.append(m)
        scrivi_storico([("2026-11-20", 900, 1000), ("2026-11-21", 900, 1000),
                        ("2026-11-22", 500, 1000), ("2026-11-23", 900, 1000), ("2026-11-24", 900, 1000)])
        self.assertFalse(bot.controlla_allarme_cassa())
        self.assertEqual(msgs, [])

    def test_una_volta_al_giorno(self):
        msgs = []
        bot.invia_telegram = lambda m, *a, **k: msgs.append(m)
        scrivi_storico([(f"2026-11-{d:02d}", 900, 1000) for d in (20, 21, 22)])
        bot.controlla_allarme_cassa()
        bot.controlla_allarme_cassa()
        self.assertEqual(len(msgs), 1)

    def test_senza_storico_non_scatta(self):
        self.assertFalse(bot.controlla_allarme_cassa())


class TestReportDomenicaleKpi(unittest.TestCase):
    def setUp(self): reset()

    def _setup_report(self, msgs):
        bot.invia_telegram = lambda m, *a, **k: msgs.append(m)
        bot.CONFIG_ASSETS.clear()
        bot.CONFIG_ASSETS["ADA-EUR"] = dict(grid_dist=0.03, grid_dist_sell=0.02, emoji="x",
            min_order_eur=5.0, decimals=1, target_weight_pct=20.0, buy_conviction=1.0,
            sell_action="tranche", is_active=True, exit_strategy="none")
        scrivi_storico([(f"2026-11-{d:02d}", 700, 1000) for d in range(10, 23)])  # cassa 70%: niente allarme
        bot.client.fills_response = {"fills": [
            {"trade_time": iso(1), "product_id": "ADA-EUR", "side": "BUY", "size": 10,
             "price": 1.0, "commission": 0.03, "liquidity_indicator": "MAKER"},
            {"trade_time": iso(1), "product_id": "ADA-EUR", "side": "SELL", "size": 10,
             "price": 1.02, "commission": 0.03, "liquidity_indicator": "MAKER"},
        ], "cursor": None}

    def test_report_include_kpi(self):
        from unittest import mock
        msgs = []
        self._setup_report(msgs)
        class FakeDt(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 11, 22, 21, 0)   # domenica sera
        with mock.patch.object(bot, "datetime", FakeDt):
            bot.traccia_portafoglio_giornaliero({"ADA-EUR": 1.0}, 700.0, {"ADA": 0.0}, {})
        self.assertEqual(len(msgs), 1)
        self.assertIn("KPI settimana", msgs[0])
        self.assertIn("Fill: 2", msgs[0])
        self.assertIn("Fee pagate: 0.06 EUR", msgs[0])
        self.assertIn("+0.14 EUR", msgs[0])           # round trip 1.00->1.02 con 0.06 di fee
        self.assertIn("Cassa media: 70%", msgs[0])

    def test_report_funziona_anche_se_api_fills_giu(self):
        from unittest import mock
        msgs = []
        self._setup_report(msgs)
        bot.client.fills_response = RuntimeError("api giu")
        class FakeDt(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 11, 22, 21, 0)
        with mock.patch.object(bot, "datetime", FakeDt):
            bot.traccia_portafoglio_giornaliero({"ADA-EUR": 1.0}, 700.0, {"ADA": 0.0}, {})
        self.assertEqual(len(msgs), 1)
        self.assertIn("REPORT SETTIMANALE", msgs[0])
        self.assertIn("Fill: 0", msgs[0])             # KPI a zero ma report inviato

    def test_report_dichiara_vendite_senza_costo(self):
        from unittest import mock
        msgs = []
        self._setup_report(msgs)
        # aggiungo una vendita senza lotto noto (es. crypto gia presente prima dello storico fill)
        bot.client.fills_response["fills"].append(
            {"trade_time": iso(0), "product_id": "SOL-EUR", "side": "SELL", "size": 0.5,
             "price": 60.0, "commission": 0.10, "liquidity_indicator": "MAKER"})
        class FakeDt(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 11, 22, 21, 0)
        with mock.patch.object(bot, "datetime", FakeDt):
            bot.traccia_portafoglio_giornaliero({"ADA-EUR": 1.0}, 700.0, {"ADA": 0.0}, {})
        self.assertEqual(len(msgs), 1)
        self.assertIn("Vendite senza costo noto: 1", msgs[0])
        self.assertIn("+0.14 EUR", msgs[0])           # P/L invariato: la vendita ignota non lo tocca


class TestVenditeSottoCosto(unittest.TestCase):
    def setUp(self): reset()

    def test_vendita_sotto_costo_rilevata(self):
        fills = [
            fill(iso(1), side="BUY", size=10.0, price=1.00, fee=0.03),  # costo 1.003/u
            fill(iso(0), side="SELL", size=10.0, price=0.90, fee=0.03), # sotto costo
        ]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertEqual(k["vendite_sotto_costo_7d"], 1)
        # pnl = 10*(0.90-1.003) - 0.03 = -1.06
        self.assertAlmostEqual(k["perdita_sotto_costo_7d"], -1.06, places=6)
        self.assertEqual(len(k["vendite_sotto_costo_recenti"]), 1)
        v = k["vendite_sotto_costo_recenti"][0]
        self.assertEqual(v["product"], "ADA-EUR")
        self.assertAlmostEqual(v["costo_medio"], 1.003, places=6)
        self.assertAlmostEqual(v["pnl"], -1.06, places=6)

    def test_vendita_sopra_costo_non_segnalata(self):
        fills = [
            fill(iso(1), side="BUY", size=10.0, price=1.00, fee=0.0),
            fill(iso(0), side="SELL", size=10.0, price=1.10, fee=0.0),
        ]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertEqual(k["vendite_sotto_costo_7d"], 0)
        self.assertEqual(k["vendite_sotto_costo_recenti"], [])

    def test_vendita_senza_lotti_noti_non_segnalata(self):
        fills = [fill(iso(0), side="SELL", size=5.0, price=0.5, fee=0.01)]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertEqual(k["vendite_sotto_costo_7d"], 0)   # costo ignoto: niente avviso
        self.assertEqual(k["vendite_sotto_costo_recenti"], [])

    def test_finestra_48h_esclude_vecchie(self):
        fills = [
            fill(iso(4), side="BUY", size=10.0, price=1.00, fee=0.0),
            fill(iso(3), side="SELL", size=10.0, price=0.90, fee=0.0),  # 72h fa: nel 7d ma non nei "recenti"
        ]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertEqual(k["vendite_sotto_costo_7d"], 1)
        self.assertEqual(k["vendite_sotto_costo_recenti"], [])

    def test_vendita_senza_lotti_conta_sconosciuta(self):
        fills = [fill(iso(0), side="SELL", size=5.0, price=0.5, fee=0.01)]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertEqual(k["vendite_senza_costo_7d"], 1)
        self.assertAlmostEqual(k["valore_senza_costo_7d"], 2.5, places=6)
        self.assertAlmostEqual(k["pnl_tot"], 0.0, places=6)   # fee non contata come perdita

    def test_parziale_in_perdita_segnalata_solo_sulla_parte_nota(self):
        # vendita 2 a 10€, lotto noto 1 a 11€, fee 1,50€ -> P/L confermato: -1 - 0,75 = -1,75
        fills = [
            fill(iso(2), side="BUY", size=1.0, price=11.0, fee=0.0),
            fill(iso(1), side="SELL", size=2.0, price=10.0, fee=1.50),
        ]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertEqual(k["vendite_sotto_costo_7d"], 1)
        self.assertAlmostEqual(k["perdita_sotto_costo_7d"], -1.75, places=6)
        self.assertEqual(k["vendite_parziali_7d"], 1)
        self.assertEqual(len(k["vendite_sotto_costo_recenti"]), 1)
        v = k["vendite_sotto_costo_recenti"][0]
        self.assertAlmostEqual(v["qta_abbinata"], 1.0, places=6)
        self.assertAlmostEqual(v["size"], 2.0, places=6)
        self.assertAlmostEqual(v["pnl"], -1.75, places=6)

    def test_carico_medio_lotti_aperti(self):
        fills = [
            fill(iso(3), side="BUY", size=10.0, price=1.00, fee=0.0),
            fill(iso(2), side="BUY", size=10.0, price=1.20, fee=0.0),
            fill(iso(1), side="SELL", size=10.0, price=1.50, fee=0.0),  # chiude il lotto a 1.00
        ]
        k = bot.calcola_kpi_fills(fills, giorni=7)
        self.assertIn("ADA-EUR", k["carico"])
        qta, costo = k["carico"]["ADA-EUR"]
        self.assertAlmostEqual(qta, 10.0, places=6)
        self.assertAlmostEqual(costo, 1.20, places=6)


class TestAvvisoSottoCosto(unittest.TestCase):
    def setUp(self): reset()

    def _fills_sotto_costo(self):
        return {"fills": [
            {"trade_time": iso(1), "product_id": "ADA-EUR", "side": "BUY", "size": 10,
             "price": 1.0, "commission": 0.0, "liquidity_indicator": "MAKER"},
            {"trade_time": iso(0), "product_id": "ADA-EUR", "side": "SELL", "size": 10,
             "price": 0.9, "commission": 0.0, "liquidity_indicator": "MAKER"},
        ], "cursor": None}

    def test_invia_avviso_e_scrive_flag(self):
        msgs = []
        bot.invia_telegram = lambda m, *a, **k: msgs.append(m)
        bot.client.fills_response = self._fills_sotto_costo()
        bot.controlla_avviso_sotto_costo()
        self.assertEqual(len(msgs), 1)
        self.assertIn("sotto costo", msgs[0])
        self.assertIn("NON blocca", msgs[0])
        self.assertTrue(os.path.exists(bot.FILE_FLAG_AVVISO_SC))

    def test_avviso_parziale_lo_dichiara(self):
        msgs = []
        bot.invia_telegram = lambda m, *a, **k: msgs.append(m)
        bot.client.fills_response = {"fills": [
            {"trade_time": iso(1), "product_id": "ADA-EUR", "side": "BUY", "size": 1,
             "price": 11.0, "commission": 0.0, "liquidity_indicator": "MAKER"},
            {"trade_time": iso(0), "product_id": "ADA-EUR", "side": "SELL", "size": 2,
             "price": 10.0, "commission": 1.5, "liquidity_indicator": "MAKER"},
        ], "cursor": None}
        bot.controlla_avviso_sotto_costo()
        self.assertEqual(len(msgs), 1)
        self.assertIn("-1.75 EUR", msgs[0])            # P/L solo sulla parte abbinata
        self.assertIn("senza costo noto", msgs[0])     # parte non abbinata dichiarata

    def test_non_ripete_la_stessa_vendita(self):
        msgs = []
        bot.invia_telegram = lambda m, *a, **k: msgs.append(m)
        bot.client.fills_response = self._fills_sotto_costo()
        bot.controlla_avviso_sotto_costo()
        bot.controlla_avviso_sotto_costo()
        self.assertEqual(len(msgs), 1)

    def test_nessun_avviso_se_sopra_costo(self):
        msgs = []
        bot.invia_telegram = lambda m, *a, **k: msgs.append(m)
        bot.client.fills_response = {"fills": [
            {"trade_time": iso(1), "product_id": "ADA-EUR", "side": "BUY", "size": 10,
             "price": 1.0, "commission": 0.0, "liquidity_indicator": "MAKER"},
            {"trade_time": iso(0), "product_id": "ADA-EUR", "side": "SELL", "size": 10,
             "price": 1.2, "commission": 0.0, "liquidity_indicator": "MAKER"},
        ], "cursor": None}
        bot.controlla_avviso_sotto_costo()
        self.assertEqual(msgs, [])

    def test_scaduto_dopo_data_fine(self):
        from unittest import mock
        msgs = []
        bot.invia_telegram = lambda m, *a, **k: msgs.append(m)
        bot.client.fills_response = self._fills_sotto_costo()
        class FakeDt(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 12, 29, 10, 0)   # oltre la fine della fase di osservazione
        with mock.patch.object(bot, "datetime", FakeDt):
            bot.controlla_avviso_sotto_costo()
        self.assertEqual(msgs, [])

    def test_api_giu_non_esplode(self):
        msgs = []
        bot.invia_telegram = lambda m, *a, **k: msgs.append(m)
        bot.client.fills_response = RuntimeError("api giu")
        bot.controlla_avviso_sotto_costo()   # non deve sollevare
        self.assertEqual(msgs, [])


if __name__ == "__main__":
    unittest.main()
