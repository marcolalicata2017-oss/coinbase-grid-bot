import os
import time
import requests
import pandas as pd
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
FILE_DIARIO = "diario_di_bordo.csv"

client = RESTClient(api_key=COINBASE_KEY_NAME, api_secret=COINBASE_KEY_SECRET, timeout=10)

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
# Variabile globale o di stato per tracciare la notifica precedente
ULTIMO_STATO_CB = None

def piazza_nuova_griglia(prezzo_rif, autorizza_buy=True, motivo_reset="Reset", ema50=0.0):
    global ULTIMO_STATO_CB
    
    saldo_eur, token_posseduti = controlla_saldi()
    prezzo_buy = prezzo_rif * (1.0 - GRID_DIST_PCT)
    prezzo_sell = prezzo_rif * (1.0 + GRID_DIST_PCT)
    
    budget_buy_teorico = max(saldo_eur * PERCENTUALE_BUDGET, MIN_BUDGET_EUR)
    quantita_token_fissa = budget_buy_teorico / prezzo_buy
    
    cancella_tutti_ordini()
    
    # --- LOGICA STARTER / ACCUMULO A ZERO TOKEN ---
    # Se il trend è negativo (CB attivo) MA abbiamo 0 token, autorizziamo l'acquisto iniziale!
    ha_token_sufficienti = (token_posseduti * prezzo_rif) >= MIN_BUDGET_EUR
    
    piazza_buy = autorizza_buy
    if not autorizza_buy and not ha_token_sufficienti:
        print("💡 [LOGICA STARTER] Prezzo < EMA50 ma 0 token in portafoglio: Autorizzato acquisto d'accumulo!", flush=True)
        piazza_buy = True
        motivo_reset += " (Acquisto Starter 0 Token)"

    if saldo_eur < MIN_BUDGET_EUR:
        piazza_buy = False

    for tentativo in range(3):
        try:
            if piazza_buy:
                id_buy = f"lbuy_{int(time.time())}"
                client.create_order(
                    client_order_id=id_buy, product_id=PRODUCT_ID, side="BUY",
                    order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_token_fissa:.4f}", "limit_price": f"{prezzo_buy:.2f}", "post_only": False}}
                )
            
            # Piazziamo il SELL solo se abbiamo token in portafoglio
            if ha_token_sufficienti:
                id_sell = f"lsell_{int(time.time()) + 1}"
                client.create_order(
                    client_order_id=id_sell, product_id=PRODUCT_ID, side="SELL",
                    order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_token_fissa:.4f}", "limit_price": f"{prezzo_sell:.2f}", "post_only": False}}
                )
            
            # --- GESTIONE NOTIFICHE TELEGRAM (ANTI-SPAM) ---
            stato_cb_attuale = "ATTIVO" if not autorizza_buy else "DISATTIVATO"
            
            # Notifica inviata SOLO se lo stato del CB è cambiato o se è un'azione reale (Reset/Trade)
            if ULTIMO_STATO_CB != stato_cb_attuale or "Esecuzione" in motivo_reset or "Starter" in motivo_reset:
                valore_totale_eur = saldo_eur + (token_posseduti * prezzo_rif)
                msg_telegram = f"🔄 *COINBASE: UPDATE GRIGLIA*\n" \
                               f"Evento: _{motivo_reset}_\n" \
                               f"Prezzo Pivot: *{prezzo_rif:.2f} EUR*\n" \
                               f"Portafoglio Totale: *{valore_totale_eur:.2f} EUR*"
                
                if not autorizza_buy:
                    msg_telegram += f"\n🛡️ *CIRCUIT BREAKER ATTIVO* (Prezzo < EMA50)."
                    if not ha_token_sufficienti:
                        msg_telegram += f"\n🛒 _Piazzato ordine d'acquisto starter per non restare a 0 token._"
                
                invia_telegram(msg_telegram)
                ULTIMO_STATO_CB = stato_cb_attuale
            
            registra_su_diario_di_bordo(prezzo_rif, ema50, saldo_eur, token_posseduti, motivo_reset, autorizza_buy)
            return True
        except Exception as e:
            print(f"⚠️ Errore piazzamento griglia: {e}", flush=True)
            time.sleep(2)
    return False

# ==========================================
# ESECUZIONE DEL CICLO SINGLE/MULTI-ASSET
# ==========================================
def esegui_gestione_asset(pair):
    cfg = CONFIG_ASSETS[pair]
    symbol_crypto = pair.split("-")[0]

    prezzo_attuale, ema50 = ottieni_prezzo_e_ema50(pair)
    if not prezzo_attuale or not ema50: return

    trend_ok = (prezzo_attuale >= ema50)
    id_buy, id_sell = recupera_ordini_pair(pair)

    # Legge i saldi correnti per capire quanti token possediamo
    saldo_eur_pool, dict_cripto = controlla_saldi_globali()
    crypto_posseduta = dict_cripto.get(symbol_crypto, 0.0)
    dec = cfg.get("decimals", 4)
    min_order_eur = cfg["min_order_eur"]

    # Calcola se la quantità di crypto posseduta basterebbe per un ordine SELL valido
    ha_crypto_per_sell = (crypto_posseduta * prezzo_attuale) >= min_order_eur

    print(f"-> [DEBUG {pair}] Prezzo: {prezzo_attuale:.2f} | EMA50: {ema50:.2f} | BUY: {bool(id_buy)} | SELL: {bool(id_sell)} | Posseduto: {crypto_posseduta:.{dec}f} {symbol_crypto}", flush=True)

    # 1. Inizializzazione Totale (Nessun ordine aperto)
    if id_buy is None and id_sell is None:
        piazza_nuova_griglia(pair, prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="Inizializzazione Multi-Asset", ema50=ema50)
        return

    # 2. Circuit Breaker Trigger (Prezzo sotto EMA50 ma BUY ancora pendente)
    if not trend_ok and id_buy is not None:
        piazza_nuova_griglia(pair, prezzo_attuale, autorizza_buy=False, motivo_reset="Attivazione Circuit Breaker", ema50=ema50)
        return

    # 3. Gestione Asimmetria Intelligente
    if id_buy is None and id_sell is not None:
        # Manca il BUY ma c'è il SELL -> VERO disallineamento -> Reset
        print(f"⚠️ [DEBUG {pair}] Manca ordine BUY. Riallineamento griglia...", flush=True)
        piazza_nuova_griglia(pair, prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="Ripristino Ordine BUY Mancante", ema50=ema50)
        return

    if id_buy is not None and id_sell is None:
        # Manca il SELL: è un'asimmetria valida SOLO SE possediamo token che dovrebbero essere in vendita!
        if ha_crypto_per_sell:
            print(f"⚠️ [DEBUG {pair}] Manca ordine SELL ma possediamo {crypto_posseduta:.{dec}f} {symbol_crypto}. Riallineamento...", flush=True)
            piazza_nuova_griglia(pair, prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="Riallineamento Ordine SELL Mancante", ema50=ema50)
            return
        else:
            # Abbiamo 0 token e il BUY è attivo: SITUAZIONE CORRETTA! Il bot non fa nulla e aspetta l'esecuzione.
            print(f"ℹ️ [DEBUG {pair}] Ordine BUY pendente in attesa di esecuzione (0 {symbol_crypto} in portafoglio). Nessuna azione richiesta.", flush=True)
            return

def main():
    totale_cicli = 5      # 5 controlli consecutivi
    minuti_attesa = 11    # ogni 11 minuti (Totale: ~55 minuti continui)

    print("🚀 [DEBUG] Avvio Bot Multi-Asset (BTC, ETH, SOL) - Pool Fluido...", flush=True)

    for ciclo in range(1, totale_cicli + 1):
        print(f"\n⏱️ === CONTROLLO {ciclo} DI {totale_cicli} ===", flush=True)
        for pair in CONFIG_ASSETS.keys():
            try:
                esegui_gestione_asset(pair)
            except Exception as e:
                print(f"❌ Errore nella gestione di {pair}: {e}", flush=True)
        
        if ciclo < totale_cicli:
            print(f"😴 In attesa di {minuti_attesa} minuti per il prossimo controllo...", flush=True)
            time.sleep(minuti_attesa * 60)

    print("✅ Sessione completata con successo!", flush=True)

if __name__ == "__main__":
    main()
