import time
import requests
import os
import sys
import subprocess
import pandas as pd
import numpy as np
from coinbase.rest import RESTClient

print("1. [DEBUG] Avvio Bot Coinbase (Griglia + Circuit Breaker EMA50)...")

# ================= CONFIGURAZIONE UTENTE =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINBASE_KEY_NAME = os.getenv("COINBASE_KEY_NAME")
COINBASE_KEY_SECRET = os.getenv("COINBASE_KEY_SECRET")

PRODUCT_ID = "ETH-EUR"       
GRID_DIST_PCT = 0.0120       
FILE_STATO = "stato_bot.txt"  

PERCENTUALE_BUDGET = 0.10    # Usa il 10% del saldo EUR libero
MIN_BUDGET_EUR = 15.00        # Soglia minima Coinbase
# =========================================================

if not COINBASE_KEY_NAME or not COINBASE_KEY_SECRET:
    print("❌ [DEBUG] Errore: Chiavi API Coinbase mancanti nei Secrets!")
    sys.exit(1)

print("2. [DEBUG] Inizializzazione RESTClient...")
client = RESTClient(
    api_key=COINBASE_KEY_NAME, 
    api_secret=COINBASE_KEY_SECRET,
    timeout=15
)
print("3. [DEBUG] Client pronto.")

def invia_telegram(messaggio):
    print("-> [DEBUG] Invio messaggio Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": messaggio, "parse_mode": "Markdown"}
    try: 
        requests.post(url, json=payload, timeout=10)
        print("-> [DEBUG] Telegram inviato con successo.")
    except Exception as e: 
        print(f"⚠️ Telegram non raggiungibile: {e}")

def esegui_git_pull():
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "--permanent-auth", "pull", "--rebase", "origin", "main"], timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"⚠️ [DEBUG] Avviso durante il git pull: {e}")

def leggi_prezzo_salvato():
    esegui_git_pull()
    if os.path.exists(FILE_STATO):
        try:
            with open(FILE_STATO, "r") as f:
                contenuto = f.read().strip()
                if contenuto: return float(contenuto)
        except: pass
    return None

def salva_prezzo(prezzo):
    esegui_git_pull()
    try:
        with open(FILE_STATO, "w") as f: 
            f.write(f"{prezzo:.2f}")
        print(f"-> [DEBUG] Prezzo Pivot {prezzo:.2f} salvato su file.")
    except Exception as e: 
        print(f"Errore salvataggio file: {e}")

def ottieni_prezzo_e_ema50():
    print("-> [DEBUG] Calcolo prezzo attuale e EMA50 oraria...")
    for tentativo in range(3):
        try:
            # Richiediamo le candele orarie a Coinbase
            candles = client.get_candles(product_id=PRODUCT_ID, granularity="ONE_HOUR")
            lista_candele = candles.get('candles', []) if isinstance(candles, dict) else getattr(candles, 'candles', [])
            
            if not lista_candele or len(lista_candele) < 50:
                print("⚠️ Candele insufficienti per EMA50, riprovo...")
                time.sleep(2)
                continue

            # Invertiamo per avere la serie storica in ordine cronologico
            prezzi_chiusura = [float(c.get('close') if isinstance(c, dict) else getattr(c, 'close')) for c in reversed(lista_candele)]
            
            s_prezzi = pd.Series(prezzi_chiusura)
            ema50 = s_prezzi.ewm(span=50, adjust=False).mean().iloc[-1]
            prezzo_attuale = prezzi_chiusura[-1]

            return prezzo_attuale, ema50
        except Exception as e:
            print(f"⚠️ Errore recupero candele: {e}")
            time.sleep(2)
    return None, None

def controlla_saldo_eur():
    for tentativo in range(3):
        try:
            conti = client.get_accounts()
            lista_conti = conti.get('accounts', []) if isinstance(conti, dict) else getattr(conti, 'accounts', [])
            for conto in lista_conti:
                valuta = conto.get('currency') if isinstance(conto, dict) else getattr(conto, 'currency', None)
                if valuta == "EUR":
                    disponibile_data = conto.get('available_balance', {}) if isinstance(conto, dict) else getattr(conto, 'available_balance', None)
                    return float(disponibile_data.get('value', 0.0)) if isinstance(disponibile_data, dict) else float(getattr(disponibile_data, 'value', 0.0))
        except Exception as e:
            time.sleep(2)
    return 0.0

def cancella_tutti_ordini():
    for tentativo in range(3):
        try:
            res = client.list_orders(order_status=["OPEN"])
            ordini = res.get('orders', []) if isinstance(res, dict) else getattr(res, 'orders', [])
            if ordini:
                id_ordini = [o.get('order_id') if isinstance(o, dict) else getattr(o, 'order_id') for o in ordini if (o.get('product_id') if isinstance(o, dict) else getattr(o, 'product_id')) == PRODUCT_ID]
                if id_ordini:
                    client.cancel_orders(order_ids=id_ordini)
                    print(f"-> [DEBUG] Cancellati {len(id_ordini)} ordini pendenti.")
            return
        except Exception as e:
            time.sleep(2)

def controlla_stato_ordine(order_id):
    for tentativo in range(3):
        try:
            res = client.get_order(order_id=order_id)
            ordine_data = res.get('order', {}) if isinstance(res, dict) else getattr(res, 'order', None)
            return ordine_data.get('status') if isinstance(ordine_data, dict) else getattr(ordine_data, 'status', 'UNKNOWN')
        except Exception as e:
            time.sleep(2)
    return "UNKNOWN"

def recupera_ordini_griglia_esistenti():
    id_buy, id_sell = None, None
    for tentativo in range(3):
        try:
            res = client.list_orders(order_status=["OPEN"])
            ordini = res.get('orders', []) if isinstance(res, dict) else getattr(res, 'orders', [])
            if ordini:
                for o in ordini:
                    p_id = o.get('product_id') if isinstance(o, dict) else getattr(o, 'product_id', None)
                    if p_id == PRODUCT_ID:
                        c_id = str(o.get('client_order_id', '') if isinstance(o, dict) else getattr(o, 'client_order_id', ''))
                        o_id = o.get('order_id') if isinstance(o, dict) else getattr(o, 'order_id', None)
                        if 'lbuy_' in c_id: id_buy = o_id
                        elif 'lsell_' in c_id: id_sell = o_id
            return id_buy, id_sell
        except Exception as e:
            time.sleep(2)
    return None, None

def piazza_nuova_griglia(prezzo_rif, autorizza_buy=True, motivo_reset="Reset"):
    print(f"-> [DEBUG] Impostazione griglia (Circuit Breaker BUY = {autorizza_buy})...")
    
    saldo_eur = controlla_saldo_eur()
    prezzo_buy = prezzo_rif * (1.0 - GRID_DIST_PCT)
    prezzo_sell = prezzo_rif * (1.0 + GRID_DIST_PCT)
    
    budget_buy_teorico = max(saldo_eur * PERCENTUALE_BUDGET, MIN_BUDGET_EUR)
    quantita_eth_fissa = budget_buy_teorico / prezzo_buy
    
    cancella_tutti_ordini()
    
    piazza_buy = autorizza_buy
    if saldo_eur < MIN_BUDGET_EUR:
        print(f"⚠️ Saldo EUR insufficiente ({saldo_eur:.2f} EUR). Salto BUY.")
        piazza_buy = False

    for tentativo in range(3):
        try:
            # 1. Ordine BUY (Piazzato usando base_size esatta in ETH)
            if piazza_buy:
                id_buy = f"lbuy_{int(time.time())}"
                client.create_order(
                    client_order_id=id_buy, product_id=PRODUCT_ID, side="BUY",
                    order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_eth_fissa:.5f}", "limit_price": f"{prezzo_buy:.2f}", "post_only": False}}
                )
            
            # 2. Ordine SELL
            id_sell = f"lsell_{int(time.time()) + 1}"
            client.create_order(
                client_order_id=id_sell, product_id=PRODUCT_ID, side="SELL",
                order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_eth_fissa:.5f}", "limit_price": f"{prezzo_sell:.2f}", "post_only": False}}
            )
            
            # NOTIFICA TELEGRAM SOLO SU RESET/CAMBIO STATO
            msg_telegram = f"🔄 *COINBASE: RESET GRIGLIA*\n" \
                           f"Motivo: _{motivo_reset}_\n" \
                           f"Prezzo Pivot: *{prezzo_rif:.2f} EUR*\n" \
                           f"Saldo Libero: *{saldo_eur:.2f} EUR*"
            if not autorizza_buy:
                msg_telegram += f"\n🛡️ *CIRCUIT BREAKER ATTIVO*: Prezzo < EMA50. _Acquisti Sospesi (Euro al sicuro)_."
            elif not piazza_buy:
                msg_telegram += f"\n⚠️ _BUY disabilitato per Euro < {MIN_BUDGET_EUR}€_"
                
            invia_telegram(msg_telegram)
            return True
        except Exception as e:
            print(f"⚠️ Errore invio ordini: {e}")
            time.sleep(2)
    return False

def esegui_singolo_controllo():
    prezzo_attuale, ema50 = ottieni_prezzo_e_ema50()
    if not prezzo_attuale or not ema50:
        print("❌ Impossibile recuperare i dati di mercato. Salto ciclo.")
        return

    # REGOLA CIRCUIT BREAKER
    trend_ok = (prezzo_attuale >= ema50)
    prezzo_riferimento = leggi_prezzo_salvato()
    id_ordine_acquisto, id_ordine_vendita = recupera_ordini_griglia_esistenti()
    
    # 1. Prima Inizializzazione o Ripristino da Vuoto
    if id_ordine_acquisto is None and id_ordine_vendita is None:
        salva_prezzo(prezzo_attuale)
        piazza_nuova_griglia(prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="Inizializzazione / Ripristino")
        return

    # 2. Se scatta il Circuit Breaker mentre c'è un BUY aperto, lo cancelliamo subito
    if not trend_ok and id_ordine_acquisto is not None:
        print("🛡️ [CIRCUIT BREAKER] Il prezzo è sceso sotto EMA50. Cancello il BUY e metto gli Euro al sicuro.")
        salva_prezzo(prezzo_attuale)
        piazza_nuova_griglia(prezzo_attuale, autorizza_buy=False, motivo_reset="Attivazione Circuit Breaker (Bear Trend)")
        return

    # 3. Controllo Esecuzione Ordini
    eseguito_acquisto = False
    eseguito_vendita = False

    if id_ordine_acquisto:
        if controlla_stato_ordine(id_ordine_acquisto) == "FILLED": eseguito_acquisto = True
    if id_ordine_vendita:
        if controlla_stato_ordine(id_ordine_vendita) == "FILLED": eseguito_vendita = True

    if eseguito_acquisto:
        nuovo_pivot = prezzo_riferimento * (1.0 - GRID_DIST_PCT)
        salva_prezzo(nuovo_pivot)
        invia_telegram(f"🟢 *COINBASE: ACQUISTO COMPLETATO!*\nPrezzo: *{nuovo_pivot:.2f} EUR*.")
        piazza_nuova_griglia(nuovo_pivot, autorizza_buy=trend_ok, motivo_reset="Esecuzione Acquisto")
        
    elif eseguito_vendita:
        nuovo_pivot = prezzo_riferimento * (1.0 + GRID_DIST_PCT)
        salva_prezzo(nuovo_pivot)
        invia_telegram(f"🔴 *COINBASE: VENDITA COMPLETATA!*\nPrezzo: *{nuovo_pivot:.2f} EUR*.\nProfitti incassati!")
        piazza_nuova_griglia(nuovo_pivot, autorizza_buy=trend_ok, motivo_reset="Esecuzione Vendita")
    else:
        print("-> [DEBUG] Nessun trade eseguito. Ordini pendenti regolari.")

def main():
    # 5 cicli interni distanziati da 10 minuti = 50 minuti di esecuzione continua
    totale_cicli = 5
    minuti_attesa = 10
    
    print("-> [DEBUG] Avvio sessione di monitoraggio continuo (10 minuti di intervallo)...")

    for ciclo in range(1, totale_cicli + 1):
        print(f"\n⏱️ === CONTROLLO {ciclo} DI {totale_cicli} ===")
        try:
            esegui_singolo_controllo()
        except Exception as e:
            print(f"❌ Errore nel ciclo {ciclo}: {e}")
            
        if ciclo < totale_cicli:
            print(f"Controllo completato. In attesa di {minuti_attesa} minuti...")
            time.sleep(minuti_attesa * 60)
            
    print("\n🏁 Sessione terminata pulita. Il workflow si chiude per lasciare spazio al successivo.")

if __name__ == "__main__":
    main()
