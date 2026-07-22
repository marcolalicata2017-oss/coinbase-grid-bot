import os
import time
import requests
import pandas as pd
from datetime import datetime
from coinbase.rest import RESTClient

# ==========================================
# CONFIGURAZIONE GENERALE & MULTI-ASSET
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINBASE_KEY_NAME = os.getenv("COINBASE_KEY_NAME")
COINBASE_KEY_SECRET = os.getenv("COINBASE_KEY_SECRET")

# Configurazione del Pool Fluido per ciascun Asset
CONFIG_ASSETS = {
    "ETH-EUR": {
        "grid_dist": 0.012,     # 1.2%
        "emoji": "🔷",
        "min_order_eur": 5.0,
        "decimals": 4
    },
    "BTC-EUR": {
        "grid_dist": 0.010,     # 1.0%
        "emoji": "🪙",
        "min_order_eur": 5.0,
        "decimals": 5
    },
    "SOL-EUR": {
        "grid_dist": 0.018,     # 1.8%
        "emoji": "🟣",
        "min_order_eur": 5.0,
        "decimals": 2
    }
}

PERCENTUALE_BUDGET_BUY = 0.10  # 10% del Pool EUR disponibile ad ogni riacquisto
SOGLIA_EMA_TOLLERANZA = 0.95    # Soglia di protezione cash impostata al 95% della EMA50 (-5%)
FILE_DIARIO = "diario_di_bordo.csv"
FILE_PORTAFOGLIO_GIORNALIERO = "storico_portafoglio_giornaliero.csv"

client = RESTClient(api_key=COINBASE_KEY_NAME, api_secret=COINBASE_KEY_SECRET, timeout=10)

ULTIMO_STATO_CB = {}

# ==========================================
# UTILITIES TELEGRAM & DIARIO
# ==========================================
def invia_telegram(messaggio):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": messaggio, "parse_mode": "Markdown"}
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print(f"⚠️ [DEBUG] Errore invio Telegram: {e}", flush=True)

def registra_su_diario_di_bordo(pair, prezzo_pivot, ema50, saldo_eur, crypto_posseduta, motivo, trend_ok):
    ora_corrente = time.strftime("%Y-%m-%d %H:%M:%S")
    file_esistente = os.path.exists(FILE_DIARIO)
    try:
        with open(FILE_DIARIO, "a", encoding="utf-8") as f:
            if not file_esistente:
                f.write("Data_Ora,Pair,Prezzo_Pivot,EMA50,Saldo_EUR_Pool,Crypto_Posseduta,Trend_OK,Motivo\n")
            f.write(f"{ora_corrente},{pair},{prezzo_pivot:.2f},{ema50:.2f},{saldo_eur:.2f},{crypto_posseduta:.5f},{trend_ok},{motivo}\n")
    except Exception as e:
        print(f"⚠️ Errore scrittura diario di bordo ({pair}): {e}", flush=True)

# ==========================================
# TRACCIAMENTO ED ELABORAZIONE REPORT SETTIMANALE VISIVO
# ==========================================
def genera_barra_progresso(percentuale, lung=10):
    p = max(0.0, min(1.0, percentuale))
    pieni = int(round(p * lung))
    vuoti = lung - pieni
    return "█" * pieni + "░" * vuoti

def traccia_portafoglio_giornaliero(prezzi_attuali, saldo_eur, dict_cripto, stati_cb):
    """Traccia il valore giornaliero su CSV e invia il report visivo SOLO la Domenica sera."""
    ora_dt = datetime.now()
    oggi = ora_dt.strftime("%Y-%m-%d")

    valore_cripto_totale = 0.0
    dettagli_cripto_val = {}
    
    for pair, prezzo in prezzi_attuali.items():
        sym = pair.split("-")[0]
        qta = dict_cripto.get(sym, 0.0)
        val = qta * (prezzo if prezzo else 0.0)
        dettagli_cripto_val[sym] = (val, qta)
        valore_cripto_totale += val

    valore_totale = saldo_eur + valore_cripto_totale

    file_esiste = os.path.exists(FILE_PORTAFOGLIO_GIORNALIERO)
    gia_registrato_oggi = False

    if file_esiste:
        try:
            with open(FILE_PORTAFOGLIO_GIORNALIERO, "r", encoding="utf-8") as f:
                righe = f.readlines()
                if any(riga.startswith(oggi) for riga in righe):
                    gia_registrato_oggi = True
        except: pass

    # 1. Registrazione Silenziosa sul CSV (1 riga al giorno)
    if not gia_registrato_oggi:
        print(f"📊 [CSV] Registrazione valore portafoglio per il giorno {oggi}...", flush=True)
        intestazione = "Data,Saldo_EUR,Valore_Crypto_EUR,Valore_Totale_EUR\n"
        riga = f"{oggi},{saldo_eur:.2f},{valore_cripto_totale:.2f},{valore_totale:.2f}\n"
        
        try:
            with open(FILE_PORTAFOGLIO_GIORNALIERO, "a", encoding="utf-8") as f:
                if not file_esiste:
                    f.write(intestazione)
                f.write(riga)
        except Exception as e:
            print(f"Errore registrazione CSV portafoglio: {e}", flush=True)

    # 2. Controllo Invio Report Visivo: Solo DOMENICA (weekday == 6) dalle ore 20:00 in poi
    is_domenica = (ora_dt.weekday() == 6)
    is_sera = (ora_dt.hour >= 20)
    
    file_flag_domenica = "report_domenica_inviato.txt"
    gia_inviato_domenica = False
    if os.path.exists(file_flag_domenica):
        try:
            with open(file_flag_domenica, "r", encoding="utf-8") as f:
                if f.read().strip() == oggi:
                    gia_inviato_domenica = True
        except: pass

    if is_domenica and is_sera and not gia_inviato_domenica:
        print("📊 [TELEGRAM] Generazione Report Visivo Settimanale della Domenica...", flush=True)
        
        valore_7_gg_fa = valore_totale
        try:
            df = pd.read_csv(FILE_PORTAFOGLIO_GIORNALIERO)
            if len(df) >= 7:
                valore_7_gg_fa = float(df.iloc[-7]["Valore_Totale_EUR"])
            elif len(df) > 1:
                valore_7_gg_fa = float(df.iloc[0]["Valore_Totale_EUR"])
        except Exception as e:
            print(f"Avviso lettura storico per delta: {e}", flush=True)

        diff_eur = valore_totale - valore_7_gg_fa
        pct_diff = ((valore_totale - valore_7_gg_fa) / valore_7_gg_fa * 100) if valore_7_gg_fa > 0 else 0.0
        
        emoji_trend = "🟢" if diff_eur >= 0 else "🔴"
        segno = "+" if diff_eur >= 0 else ""

        pct_eur = (saldo_eur / valore_totale) if valore_totale > 0 else 1.0
        barra_eur = genera_barra_progresso(pct_eur)

        msg_report = f"📊 *REPORT SETTIMANALE PORTAFOGLIO*\n" \
                     f"📅 Domenica {ora_dt.strftime('%d/%m/%Y')}\n\n" \
                     f"💰 Valore Totale: *{valore_totale:.2f} EUR*\n" \
                     f"📈 Variazione Settimana: *{segno}{pct_diff:.2f}%* ({emoji_trend} {segno}{diff_eur:.2f} EUR)\n\n" \
                     f"📊 *Composizione Portafoglio:*\n" \
                     f"`[{barra_eur}]` {pct_eur*100:.0f}% Saldo EUR ({saldo_eur:.2f} EUR)\n"

        for pair, cfg in CONFIG_ASSETS.items():
            sym = pair.split("-")[0]
            val, qta = dettagli_cripto_val.get(sym, (0.0, 0.0))
            pct_asset = (val / valore_totale) if valore_totale > 0 else 0.0
            barra_asset = genera_barra_progresso(pct_asset)
            msg_report += f"`[{barra_asset}]` {pct_asset*100:.0f}% {cfg['emoji']} {sym} ({val:.2f} EUR | {qta:.{cfg['decimals']}f} {sym})\n"

        msg_report += "\n🛡️ *Stato Circuit Breaker (Soglia 95% EMA50):*\n"
        for pair, cb_attivo in stati_cb.items():
            emoji_asset = CONFIG_ASSETS[pair]["emoji"]
            stato_txt = "ATTIVO 🔴" if cb_attivo else "DISATTIVATO 🟢"
            msg_report += f"{emoji_asset} {pair}: *{stato_txt}*\n"

        invia_telegram(msg_report)

        try:
            with open(file_flag_domenica, "w", encoding="utf-8") as f:
                f.write(oggi)
        except: pass

# ==========================================
# CHIAMATE API COINBASE
# ==========================================
def ottieni_prezzo_e_ema50(product_id):
    url = f"https://api.exchange.coinbase.com/products/{product_id}/candles?granularity=3600"
    headers = {"User-Agent": "Python-Bot"}
    for tentativo in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if len(data) >= 50:
                    prezzi_chiusura = [float(candela[4]) for candela in reversed(data)]
                    s_prezzi = pd.Series(prezzi_chiusura)
                    ema50 = s_prezzi.ewm(span=50, adjust=False).mean().iloc[-1]
                    prezzo_attuale = prezzi_chiusura[-1]
                    return prezzo_attuale, ema50
        except Exception as e:
            print(f"⚠️ Errore API candele ({product_id}): {e}", flush=True)
        time.sleep(1)
    return None, None

def controlla_saldi_globali():
    saldo_eur = 0.0
    cripto_dict = {"ETH": 0.0, "BTC": 0.0, "SOL": 0.0}
    for tentativo in range(3):
        try:
            conti = client.get_accounts()
            lista_conti = conti.get('accounts', []) if isinstance(conti, dict) else getattr(conti, 'accounts', [])
            for conto in lista_conti:
                valuta = conto.get('currency') if isinstance(conto, dict) else getattr(conto, 'currency', None)
                disponibile_data = conto.get('available_balance', {}) if isinstance(conto, dict) else getattr(conto, 'available_balance', None)
                valore = float(disponibile_data.get('value', 0.0)) if isinstance(disponibile_data, dict) else float(getattr(disponibile_data, 'value', 0.0))
                
                if valuta == "EUR":
                    saldo_eur = valore
                elif valuta in cripto_dict:
                    cripto_dict[valuta] = valore
            return saldo_eur, cripto_dict
        except Exception as e:
            print(f"⚠️ Errore lettura saldi (tentativo {tentativo+1}): {e}", flush=True)
            time.sleep(2)
    return 0.0, cripto_dict

def recupera_ordini_pair(product_id):
    id_buy, id_sell = None, None
    for tentativo in range(3):
        try:
            res = client.list_orders(order_status=["OPEN"])
            ordini = res.get('orders', []) if isinstance(res, dict) else getattr(res, 'orders', [])
            if ordini:
                for o in ordini:
                    p_id = o.get('product_id') if isinstance(o, dict) else getattr(o, 'product_id', None)
                    if p_id == product_id:
                        c_id = str(o.get('client_order_id', '') if isinstance(o, dict) else getattr(o, 'client_order_id', ''))
                        o_id = o.get('order_id') if isinstance(o, dict) else getattr(o, 'order_id', None)
                        if 'lbuy_' in c_id: id_buy = o_id
                        elif 'lsell_' in c_id: id_sell = o_id
            return id_buy, id_sell
        except Exception as e:
            print(f"⚠️ Errore lettura ordini ({product_id}): {e}", flush=True)
            time.sleep(2)
    return None, None

def cancella_ordini_pair(product_id):
    try:
        res = client.list_orders(order_status=["OPEN"])
        ordini = res.get('orders', []) if isinstance(res, dict) else getattr(res, 'orders', [])
        ids_da_cancellare = []
        if ordini:
            for o in ordini:
                p_id = o.get('product_id') if isinstance(o, dict) else getattr(o, 'product_id', None)
                if p_id == product_id:
                    o_id = o.get('order_id') if isinstance(o, dict) else getattr(o, 'order_id', None)
                    if o_id: ids_da_cancellare.append(o_id)
        if ids_da_cancellare:
            client.cancel_orders(order_ids=ids_da_cancellare)
            print(f"-> [DEBUG] Cancellati ordini aperti per {product_id}", flush=True)
    except Exception as e:
        print(f"⚠️ Errore cancellazione ordini {product_id}: {e}", flush=True)

# ==========================================
# LOGICA DI PIAZZAMENTO GRIGLIA DEDICATA
# ==========================================
def piazza_nuova_griglia(pair, prezzo_rif, autorizza_buy=True, motivo_reset="Reset", ema50=0.0):
    global ULTIMO_STATO_CB
    cfg = CONFIG_ASSETS[pair]
    symbol_crypto = pair.split("-")[0]
    grid_dist = cfg["grid_dist"]
    min_order_eur = cfg["min_order_eur"]
    dec = cfg["decimals"]
    emoji = cfg["emoji"]

    saldo_eur, dict_cripto = controlla_saldi_globali()
    crypto_posseduta = dict_cripto.get(symbol_crypto, 0.0)

    prezzo_buy_grid = prezzo_rif * (1.0 - grid_dist)
    prezzo_sell = prezzo_rif * (1.0 + grid_dist)

    budget_buy_teorico = max(saldo_eur * PERCENTUALE_BUDGET_BUY, min_order_eur)
    
    cancella_ordini_pair(pair)

    ha_crypto_sufficiente = (crypto_posseduta * prezzo_rif) >= min_order_eur
    is_starter_buy = False
    piazza_buy = autorizza_buy

    # LOGICA STARTER: Se Prezzo < (EMA50 * 0.95) e 0 token, acquisto al PREZZO ATTUALE
    if not autorizza_buy and not ha_crypto_sufficiente:
        print(f"💡 [{pair} STARTER BUY] Prezzo < 95% EMA50 e 0 {symbol_crypto}: Acquisto immediato al prezzo attuale!", flush=True)
        piazza_buy = True
        is_starter_buy = True
        prezzo_compra_effettivo = prezzo_rif
        motivo_reset += " (Acquisto Starter Immediato)"
    else:
        prezzo_compra_effettivo = prezzo_buy_grid

    quantita_token = budget_buy_teorico / prezzo_compra_effettivo

    if saldo_eur < min_order_eur:
        piazza_buy = False

    for tentativo in range(3):
        try:
            if piazza_buy:
                id_buy = f"lbuy_{int(time.time())}"
                client.create_order(
                    client_order_id=id_buy, product_id=pair, side="BUY",
                    order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_token:.{dec}f}", "limit_price": f"{prezzo_compra_effettivo:.2f}", "post_only": False}}
                )

            if ha_crypto_sufficiente:
                id_sell = f"lsell_{int(time.time()) + 1}"
                quantita_sell = budget_buy_teorico / prezzo_sell
                client.create_order(
                    client_order_id=id_sell, product_id=pair, side="SELL",
                    order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_sell:.{dec}f}", "limit_price": f"{prezzo_sell:.2f}", "post_only": False}}
                )

            stato_cb_attuale = "ATTIVO" if not autorizza_buy else "DISATTIVATO"
            stato_precedente = ULTIMO_STATO_CB.get(pair)

            if stato_precedente != stato_cb_attuale or "Esecuzione" in motivo_reset or is_starter_buy:
                valore_totale = saldo_eur + (crypto_posseduta * prezzo_rif)
                msg_telegram = f"🔄 *COINBASE: UPDATE GRIGLIA {pair}* {emoji}\n" \
                               f"Evento: _{motivo_reset}_\n" \
                               f"Prezzo Pivot: *{prezzo_rif:.2f} EUR*\n" \
                               f"Pool EUR Libero: *{saldo_eur:.2f} EUR*"

                if not autorizza_buy:
                    msg_telegram += f"\n🛡️ *CIRCUIT BREAKER ATTIVO* (Prezzo < 95% EMA50: {ema50*0.95:.2f} EUR)."
                    if is_starter_buy:
                        msg_telegram += f"\n🛒 _Ordine d'acquisto immediato inviato a {prezzo_rif:.2f} EUR per non rimanere a 0 token._"

                invia_telegram(msg_telegram)
                ULTIMO_STATO_CB[pair] = stato_cb_attuale

            registra_su_diario_di_bordo(pair, prezzo_rif, ema50, saldo_eur, crypto_posseduta, motivo_reset, autorizza_buy)
            return True
        except Exception as e:
            print(f"⚠️ Errore piazzamento griglia ({pair}): {e}", flush=True)
            time.sleep(2)
    return False

# ==========================================
# ESECUZIONE DEL CICLO SINGLE/MULTI-ASSET
# ==========================================
def esegui_gestione_asset(pair):
    cfg = CONFIG_ASSETS[pair]
    symbol_crypto = pair.split("-")[0]

    prezzo_attuale, ema50 = ottieni_prezzo_e_ema50(pair)
    if not prezzo_attuale or not ema50: return None, False

    # NUOVA SOGLIA: trend_ok rimane True finché il prezzo è sopra il 95% della EMA50
    soglia_protezione = ema50 * SOGLIA_EMA_TOLLERANZA
    trend_ok = (prezzo_attuale >= soglia_protezione)
    
    id_buy, id_sell = recupera_ordini_pair(pair)

    saldo_eur_pool, dict_cripto = controlla_saldi_globali()
    crypto_posseduta = dict_cripto.get(symbol_crypto, 0.0)
    dec = cfg.get("decimals", 4)
    min_order_eur = cfg["min_order_eur"]

    ha_crypto_per_sell = (crypto_posseduta * prezzo_attuale) >= min_order_eur

    print(f"-> [DEBUG {pair}] Prezzo: {prezzo_attuale:.2f} | EMA50: {ema50:.2f} (Soglia 95%: {soglia_protezione:.2f}) | BUY: {bool(id_buy)} | SELL: {bool(id_sell)} | Posseduto: {crypto_posseduta:.{dec}f} {symbol_crypto}", flush=True)

    # 1. Inizializzazione Totale (Nessun ordine aperto)
    if id_buy is None and id_sell is None:
        piazza_nuova_griglia(pair, prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="Inizializzazione Multi-Asset", ema50=ema50)
        return prezzo_attuale, not trend_ok

    # 2. Circuit Breaker Trigger (Prezzo sotto 95% EMA50 ma BUY ancora pendente)
    if not trend_ok and id_buy is not None:
        piazza_nuova_griglia(pair, prezzo_attuale, autorizza_buy=False, motivo_reset="Attivazione Circuit Breaker (Sotto 95% EMA50)", ema50=ema50)
        return prezzo_attuale, True

    # 3. Gestione Asimmetria Intelligente
    if id_buy is None and id_sell is not None:
        print(f"⚠️ [DEBUG {pair}] Manca ordine BUY. Riallineamento griglia...", flush=True)
        piazza_nuova_griglia(pair, prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="Ripristino Ordine BUY Mancante", ema50=ema50)
        return prezzo_attuale, not trend_ok

    if id_buy is not None and id_sell is None:
        if ha_crypto_per_sell:
            print(f"⚠️ [DEBUG {pair}] Manca ordine SELL ma possediamo {crypto_posseduta:.{dec}f} {symbol_crypto}. Riallineamento...", flush=True)
            piazza_nuova_griglia(pair, prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="Riallineamento Ordine SELL Mancante", ema50=ema50)
        else:
            print(f"ℹ️ [DEBUG {pair}] Ordine BUY pendente in attesa di esecuzione (0 {symbol_crypto} in portafoglio). Nessuna azione richiesta.", flush=True)

    return prezzo_attuale, not trend_ok

def main():
    totale_cicli = 5      # 5 controlli consecutivi
    minuti_attesa = 11    # ogni 11 minuti (Totale: ~55 minuti continui)

    print("🚀 [DEBUG] Avvio Bot Multi-Asset (BTC, ETH, SOL) - Pool Fluido...", flush=True)

    for ciclo in range(1, totale_cicli + 1):
        print(f"\n⏱️ === CONTROLLO {ciclo} DI {totale_cicli} ===", flush=True)
        
        prezzi_attuali = {}
        stati_cb = {}

        for pair in CONFIG_ASSETS.keys():
            try:
                prezzo, cb_attivo = esegui_gestione_asset(pair)
                prezzi_attuali[pair] = prezzo
                stati_cb[pair] = cb_attivo
            except Exception as e:
                print(f"❌ Errore nella gestione di {pair}: {e}", flush=True)
        
        # TRACCIAMENTO ED ELABORAZIONE REPORT DOMENICALE
        try:
            saldo_eur, dict_cripto = controlla_saldi_globali()
            traccia_portafoglio_giornaliero(prezzi_attuali, saldo_eur, dict_cripto, stati_cb)
        except Exception as e:
            print(f"⚠️ Errore tracciamento portafoglio: {e}", flush=True)

        if ciclo < totale_cicli:
            print(f"😴 In attesa di {minuti_attesa} minuti per il prossimo controllo...", flush=True)
            time.sleep(minuti_attesa * 60)

    print("✅ Sessione completata con successo!", flush=True)

if __name__ == "__main__":
    main()
