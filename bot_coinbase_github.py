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
def piazza_nuova_griglia(pair, prezzo_rif, autorizza_buy=True, motivo_reset="Reset", ema50=0.0):
    cfg = CONFIG_ASSETS[pair]
    dist_pct = cfg["grid_dist"]
    emoji = cfg["emoji"]
    min_order_eur = cfg["min_order_eur"]
    dec = cfg.get("decimals", 4)
    symbol_crypto = pair.split("-")[0]

    saldo_eur_pool, dict_cripto = controlla_saldi_globali()
    crypto_posseduta = dict_cripto.get(symbol_crypto, 0.0)

    prezzo_buy = prezzo_rif * (1.0 - dist_pct)
    prezzo_sell = prezzo_rif * (1.0 + dist_pct)

    # Budget BUY dinamico calcolato dal Pool EUR
    budget_buy_teorico = max(saldo_eur_pool * PERCENTUALE_BUDGET_BUY, min_order_eur)
    quantita_crypto_buy = budget_buy_teorico / prezzo_buy

    # Quantità SELL: il minimo tra la quantità teorica e la crypto realmente posseduta
    quantita_crypto_sell = min(quantita_crypto_buy, crypto_posseduta)

    # Formattazione rigorosa con la precisione decimali di ciascun asset
    base_size_buy = f"{quantita_crypto_buy:.{dec}f}"
    base_size_sell = f"{quantita_crypto_sell:.{dec}f}"

    cancella_ordini_pair(pair)

    piazza_buy = autorizza_buy and (saldo_eur_pool >= min_order_eur)
    piazza_sell = (quantita_crypto_sell * prezzo_sell) >= min_order_eur

    print(f"-> [DEBUG {pair}] Tentativo piazzamento -> BUY: {piazza_buy} (Budget EUR Pool: {saldo_eur_pool:.2f}) | SELL: {piazza_sell} ({crypto_posseduta:.{dec}f} {symbol_crypto})", flush=True)

    timestamp = int(time.time())

    # Invio Ordine BUY
    if piazza_buy:
        try:
            res_buy = client.create_order(
                client_order_id=f"lbuy_{symbol_crypto.lower()}_{timestamp}",
                product_id=pair,
                side="BUY",
                order_configuration={
                    "limit_limit_gtc": {
                        "base_size": base_size_buy,
                        "limit_price": f"{prezzo_buy:.2f}",
                        "post_only": False
                    }
                }
            )
            print(f"✅ [DEBUG {pair}] Ordine BUY Inviato: {res_buy}", flush=True)
        except Exception as e:
            print(f"❌ [DEBUG {pair}] ERRORE Invio Ordine BUY: {e}", flush=True)

    # Invio Ordine SELL
    if piazza_sell:
        try:
            res_sell = client.create_order(
                client_order_id=f"lsell_{symbol_crypto.lower()}_{timestamp+1}",
                product_id=pair,
                side="SELL",
                order_configuration={
                    "limit_limit_gtc": {
                        "base_size": base_size_sell,
                        "limit_price": f"{prezzo_sell:.2f}",
                        "post_only": False
                    }
                }
            )
            print(f"✅ [DEBUG {pair}] Ordine SELL Inviato: {res_sell}", flush=True)
        except Exception as e:
            print(f"❌ [DEBUG {pair}] ERRORE Invio Ordine SELL: {e}", flush=True)

    # Notifica Telegram
    msg = f"{emoji} *COINBASE: RESET GRIGLIA ({pair})*\n" \
          f"Motivo: _{motivo_reset}_\n" \
          f"Prezzo Pivot: *{prezzo_rif:.2f} EUR*\n" \
          f"Pool EUR Disponibile: *{saldo_eur_pool:.2f} EUR*\n" \
          f"Crypto Posseduta: *{crypto_posseduta:.{dec}f} {symbol_crypto}*"
    
    if not autorizza_buy:
        msg += f"\n🛡️ *CIRCUIT BREAKER*: Prezzo < EMA50. _Euro al sicuro nel Pool_."

    invia_telegram(msg)
    registra_su_diario_di_bordo(pair, prezzo_rif, ema50, saldo_eur_pool, crypto_posseduta, motivo_reset, autorizza_buy)
    return True

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
