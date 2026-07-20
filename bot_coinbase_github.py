import time
import requests
import os
import sys
import subprocess
import pandas as pd
import numpy as np
from datetime import datetime
from coinbase.rest import RESTClient

print("1. [DEBUG] Avvio Bot Coinbase (Griglia + Circuit Breaker + Diario di Bordo)...")

# ================= CONFIGURAZIONE UTENTE =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINBASE_KEY_NAME = os.getenv("COINBASE_KEY_NAME")
COINBASE_KEY_SECRET = os.getenv("COINBASE_KEY_SECRET")

PRODUCT_ID = "ETH-EUR"       
GRID_DIST_PCT = 0.0120       
FILE_STATO = "stato_bot.txt"  
FILE_DIARIO = "diario_di_bordo.csv"

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

def esegui_git_sync():
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "--permanent-auth", "pull", "--rebase", "origin", "main"], timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"⚠️ [DEBUG] Avviso durante il git pull: {e}")

def esegui_git_push(messaggio_commit="Update stato bot"):
    try:
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", messaggio_commit], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "push", "origin", "main"], timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"-> [DEBUG] Git push completato: {messaggio_commit}")
    except Exception as e:
        print(f"⚠️ [DEBUG] Avviso durante il git push: {e}")

def leggi_prezzo_salvato():
    esegui_git_sync()
    if os.path.exists(FILE_STATO):
        try:
            with open(FILE_STATO, "r") as f:
                contenuto = f.read().strip()
                if contenuto: return float(contenuto)
        except: pass
    return None

def salva_prezzo(prezzo):
    try:
        with open(FILE_STATO, "w") as f: 
            f.write(f"{prezzo:.2f}")
        print(f"-> [DEBUG] Prezzo Pivot {prezzo:.2f} salvato su file.")
    except Exception as e: 
        print(f"Errore salvataggio file: {e}")

def registra_su_diario_di_bordo(prezzo_eth, ema50, saldo_eur, eth_posseduti, evento, trend_ok):
    esegui_git_sync()
    valore_eth_eur = eth_posseduti * prezzo_eth
    valore_totale = saldo_eur + valore_eth_eur
    ora_attuale = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stato_cb = "DISATTIVATO" if trend_ok else "ATTIVO (PROTEZIONE EUR)"

    intestazione = "Data_Ora,Prezzo_ETH,EMA50,Saldo_EUR,ETH_Posseduti,Valore_Totale_EUR,Stato_Circuit_Breaker,Evento\n"
    riga = f"{ora_attuale},{prezzo_eth:.2f},{ema50:.2f},{saldo_eur:.2f},{eth_posseduti:.6f},{valore_totale:.2f},{stato_cb},{evento}\n"

    file_esiste = os.path.exists(FILE_DIARIO)
    try:
        with open(FILE_DIARIO, "a") as f:
            if not file_esiste:
                f.write(intestazione)
            f.write(riga)
        print(f"-> [DEBUG] Diario di Bordo aggiornato: {evento}")
        esegui_git_push(f"Diario di bordo: {evento}")
    except Exception as e:
        print(f"Errore scrittura Diario di Bordo: {e}")

def ottieni_prezzo_e_ema50():
    print("-> [DEBUG] Calcolo prezzo attuale e EMA50 oraria...")
    for tentativo in range(3):
        try:
            candles = client.get_candles(product_id=PRODUCT_ID, granularity="ONE_HOUR")
            lista_candele = candles.get('candles', []) if isinstance(candles, dict) else getattr(candles, 'candles', [])
            
            if not lista_candele or len(lista_candele) < 50:
                time.sleep(2)
                continue

            prezzi_chiusura = [float(c.get('close') if isinstance(c, dict) else getattr(c, 'close')) for c in reversed(lista_candele)]
            s_prezzi = pd.Series(prezzi_chiusura)
            ema50 = s_prezzi.ewm(span=50, adjust=False).mean().iloc[-1]
            prezzo_attuale = prezzi_chiusura[-1]

            return prezzo_attuale, ema50
        except Exception as e:
            time.sleep(2)
    return None, None

def controlla_saldi():
    saldo_eur = 0.0
    eth_posseduti = 0.0
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
                elif valuta == "ETH":
                    eth_posseduti = valore
            return saldo_eur, eth_posseduti
        except Exception as e:
            time.sleep(2)
    return 0.0, 0.0

def cancella_tutti_ordini():
    for tentativo in range(3):
        try:
            res = client.list_orders(order_status=["OPEN"])
            ordini = res.get('orders', []) if isinstance(res, dict) else getattr(res, 'orders', [])
            if ordini:
                id_ordini = [o.get('order_id') if isinstance(o, dict) else getattr(o, 'order_id') for o in ordini if (o.get('product_id') if isinstance(o, dict) else getattr(o, 'product_id')) == PRODUCT_ID]
                if id_ordini:
                    client.cancel_orders(order_ids=id_ordini)
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

def piazza_nuova_griglia(prezzo_rif, autorizza_buy=True, motivo_reset="Reset", ema50=0.0):
    saldo_eur, eth_posseduti = controlla_saldi()
    prezzo_buy = prezzo_rif * (1.0 - GRID_DIST_PCT)
    prezzo_sell = prezzo_rif * (1.0 + GRID_DIST_PCT)
    
    budget_buy_teorico = max(saldo_eur * PERCENTUALE_BUDGET, MIN_BUDGET_EUR)
    quantita_eth_fissa = budget_buy_teorico / prezzo_buy
    
    cancella_tutti_ordini()
    
    piazza_buy = autorizza_buy
    if saldo_eur < MIN_BUDGET_EUR:
        piazza_buy = False

    for tentativo in range(3):
        try:
            if piazza_buy:
                id_buy = f"lbuy_{int(time.time())}"
                client.create_order(
                    client_order_id=id_buy, product_id=PRODUCT_ID, side="BUY",
                    order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_eth_fissa:.5f}", "limit_price": f"{prezzo_buy:.2f}", "post_only": False}}
                )
            
            id_sell = f"lsell_{int(time.time()) + 1}"
            client.create_order(
                client_order_id=id_sell, product_id=PRODUCT_ID, side="SELL",
                order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_eth_fissa:.5f}", "limit_price": f"{prezzo_sell:.2f}", "post_only": False}}
            )
            
            # NOTIFICA TELEGRAM
            valore_totale_eur = saldo_eur + (eth_posseduti * prezzo_rif)
            msg_telegram = f"🔄 *COINBASE: RESET GRIGLIA*\n" \
                           f"Motivo: _{motivo_reset}_\n" \
                           f"Prezzo Pivot: *{prezzo_rif:.2f} EUR*\n" \
                           f"Portafoglio Totale: *{valore_totale_eur:.2f} EUR*"
            if not autorizza_buy:
                msg_telegram += f"\n🛡️ *CIRCUIT BREAKER ATTIVO*: Prezzo < EMA50. _Euro al sicuro_."
            
            invia_telegram(msg_telegram)
            registra_su_diario_di_bordo(prezzo_rif, ema50, saldo_eur, eth_posseduti, motivo_reset, autorizza_buy)
            return True
        except Exception as e:
            time.sleep(2)
    return False

def esegui_singolo_controllo():
    prezzo_attuale, ema50 = ottieni_prezzo_e_ema50()
    if not prezzo_attuale or not ema50: return

    trend_ok = (prezzo_attuale >= ema50)
    prezzo_riferimento = leggi_prezzo_salvato()
    id_ordine_acquisto, id_ordine_vendita = recupera_ordini_griglia_esistenti()
    
    # 1. Inizializzazione / Prima Esecuzione
    if id_ordine_acquisto is None and id_ordine_vendita is None:
        salva_prezzo(prezzo_attuale)
        piazza_nuova_griglia(prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="Inizializzazione", ema50=ema50)
        return

    # 2. Circuit Breaker Trigger
    if not trend_ok and id_ordine_acquisto is not None:
        salva_prezzo(prezzo_attuale)
        piazza_nuova_griglia(prezzo_attuale, autorizza_buy=False, motivo_reset="Attivazione Circuit Breaker", ema50=ema50)
        return

    # 3. Controllo Esecuzione Ordini
    eseguito_acquisto = (controlla_stato_ordine(id_ordine_acquisto) == "FILLED") if id_ordine_acquisto else False
    eseguito_vendita = (controlla_stato_ordine(id_ordine_vendita) == "FILLED") if id_ordine_vendita else False

    if eseguito_acquisto:
        nuovo_pivot = prezzo_riferimento * (1.0 - GRID_DIST_PCT)
        salva_prezzo(nuovo_pivot)
        saldo_eur, eth_posseduti = controlla_saldi()
        invia_telegram(f"🟢 *COINBASE: ACQUISTO COMPLETATO!*\nPrezzo: *{nuovo_pivot:.2f} EUR*.")
        piazza_nuova_griglia(nuovo_pivot, autorizza_buy=trend_ok, motivo_reset="Esecuzione Acquisto", ema50=ema50)
        
    elif eseguito_vendita:
        nuovo_pivot = prezzo_riferimento * (1.0 + GRID_DIST_PCT)
        salva_prezzo(nuovo_pivot)
        saldo_eur, eth_posseduti = controlla_saldi()
        invia_telegram(f"🔴 *COINBASE: VENDITA COMPLETATA!*\nPrezzo: *{nuovo_pivot:.2f} EUR*.\nProfitti incassati!")
        piazza_nuova_griglia(nuovo_pivot, autorizza_buy=trend_ok, motivo_reset="Esecuzione Vendita", ema50=ema50)

def main():
    totale_cicli = 2
    minuti_attesa = 12
    
    print("-> [DEBUG] Avvio sessione di monitoraggio (2 controlli per finestra di 30m)...")

    for ciclo in range(1, totale_cicli + 1):
        print(f"\n⏱️ === CONTROLLO {ciclo} DI {totale_cicli} ===")
        try:
            esegui_singolo_controllo()
        except Exception as e:
            print(f"❌ Errore nel ciclo {ciclo}: {e}")
            
        if ciclo < totale_cicli:
            time.sleep(minuti_attesa * 60)

if __name__ == "__main__":
    main()
