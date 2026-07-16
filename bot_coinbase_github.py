import time
import requests
import os
import sys
from coinbase.rest import RESTClient

print("1. [DEBUG] Avvio dello script (Versione Size Dinamica su Saldo Reale)...")

# ================= CONFIGURAZIONE UTENTE =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINBASE_KEY_NAME = os.getenv("COINBASE_KEY_NAME")
COINBASE_KEY_SECRET = os.getenv("COINBASE_KEY_SECRET")

PRODUCT_ID = "ETH-EUR"       
GRID_DIST_PCT = 0.0120       
FILE_STATO = "stato_bot.txt"  

# --- PARAMETRI COMPOSITING DINAMICO ---
PERCENTUALE_BUDGET = 0.10    # Usa il 10.0% del saldo EUR libero su Coinbase
MIN_BUDGET_EUR = 15.00        # Soglia minima di sicurezza per evitare blocchi Coinbase
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

def leggi_prezzo_salvato():
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
    except Exception as e: 
        print(f"Errore salvataggio file: {e}")

def ottieni_prezzo_reale():
    print("-> [DEBUG] Richiesta prezzo ETH...")
    for tentativo in range(3):
        try: 
            res = client.get_product(product_id=PRODUCT_ID)
            prezzo_str = res.get('price') if isinstance(res, dict) else getattr(res, 'price', None)
            if prezzo_str:
                prezzo = float(prezzo_str)
                print(f"-> [DEBUG] Prezzo ottenuto: {prezzo}")
                return prezzo
        except Exception as e: 
            print(f"⚠️ [Tentativo {tentativo+1}/3] Errore richiesta prezzo: {e}")
            time.sleep(2)
    print("❌ [DEBUG] Impossibile ottenere il prezzo reale.")
    return None

def calcola_budget_dinamico():
    print("-> [DEBUG] Recupero del saldo EUR disponibile su Coinbase...")
    for tentativo in range(3):
        try:
            conti = client.get_accounts()
            lista_conti = conti.get('accounts', []) if isinstance(conti, dict) else getattr(conti, 'accounts', [])

            for conto in lista_conti:
                valuta = conto.get('currency') if isinstance(conto, dict) else getattr(conto, 'currency', None)
                if valuta == "EUR":
                    disponibile_data = conto.get('available_balance', {}) if isinstance(conto, dict) else getattr(conto, 'available_balance', None)
                    saldo_libero = float(disponibile_data.get('value', 0.0)) if isinstance(disponibile_data, dict) else float(getattr(disponibile_data, 'value', 0.0))

                    # Calcoliamo la size in base alla percentuale desiderata
                    size_calcolata = saldo_libero * PERCENTUALE_BUDGET

                    # Applichiamo i limiti di salvaguardia
                    size_finale = max(size_calcolata, MIN_BUDGET_EUR)
                    print(f"💰 [DEBUG] Saldo EUR libero: {saldo_libero:.2f} EUR | Size calcolata ({PERCENTUALE_BUDGET*100}%): {size_calcolata:.2f} EUR -> Utilizzo: {size_finale:.2f} EUR")
                    return round(size_finale, 2)

            print("⚠️ [DEBUG] Conto EUR non trovato nella lista degli account.")
        except Exception as e:
            print(f"⚠️ [Tentativo {tentativo+1}/3] Errore recupero saldo: {e}")
            time.sleep(2)

    print(f"❌ [DEBUG] Recupero saldo fallito. Utilizzo valore minimo di default: {MIN_BUDGET_EUR} EUR")
    return MIN_BUDGET_EUR

def cancella_tutti_ordini():
    print("-> [DEBUG] Controllo cancellazione vecchi ordini...")
    for tentativo in range(3):
        try:
            res = client.list_orders(order_status=["OPEN"])
            ordini = res.get('orders', []) if isinstance(res, dict) else getattr(res, 'orders', [])
            if ordini:
                id_ordini = []
                for o in ordini:
                    p_id = o.get('product_id') if isinstance(o, dict) else getattr(o, 'product_id', None)
                    o_id = o.get('order_id') if isinstance(o, dict) else getattr(o, 'order_id', None)
                    if p_id == PRODUCT_ID and o_id:
                        id_ordini.append(o_id)

                if id_ordini:
                    client.cancel_orders(order_ids=id_ordini)
                    print(f"-> [DEBUG] Cancellati {len(id_ordini)} ordini pendenti.")
                    time.sleep(1)
            return
        except Exception as e:
            print(f"⚠️ [Tentativo {tentativo+1}/3] Errore cancellazione: {e}")
            time.sleep(2)

def controlla_stato_ordine(order_id):
    for tentativo in range(3):
        try:
            res = client.get_order(order_id=order_id)
            ordine_data = res.get('order', {}) if isinstance(res, dict) else getattr(res, 'order', None)
            stato = ordine_data.get('status') if isinstance(ordine_data, dict) else getattr(ordine_data, 'status', 'UNKNOWN')
            return stato
        except Exception as e:
            print(f"⚠️ [Tentativo {tentativo+1}/3] Errore stato ordine {order_id}: {e}")
            time.sleep(2)
    return "UNKNOWN"

def recupera_ordini_griglia_esistenti():
    print("-> [DEBUG] Tentativo di recupero ordini esistenti...")
    id_buy, id_sell = None, None
    for tentativo in range(3):
        try:
            res = client.list_orders(order_status=["OPEN"])
            print("-> [DEBUG] Risposta ricevuta correttamente da Coinbase!")

            ordini = res.get('orders', []) if isinstance(res, dict) else getattr(res, 'orders', [])

            if ordini:
                print(f"-> [DEBUG] Trovati {len(ordini)} ordini aperti totali sul tuo account.")
                for o in ordini:
                    p_id = o.get('product_id') if isinstance(o, dict) else getattr(o, 'product_id', None)
                    if p_id == PRODUCT_ID:
                        c_id = o.get('client_order_id', '') if isinstance(o, dict) else getattr(o, 'client_order_id', '')
                        o_id = o.get('order_id') if isinstance(o, dict) else getattr(o, 'order_id', None)

                        if 'lbuy_' in str(c_id):
                            id_buy = o_id
                            print(f"-> [DEBUG] Identificato ordine BUY esistente: {id_buy}")
                        elif 'lsell_' in str(c_id):
                            id_sell = o_id
                            print(f"-> [DEBUG] Identificato ordine SELL esistente: {id_sell}")
            else:
                print("-> [DEBUG] Nessun ordine aperto presente sul book.")
            return id_buy, id_sell
        except Exception as e:
            print(f"⚠️ [Tentativo {tentativo+1}/3] Errore recupero ordini: {e}")
            time.sleep(2)
    print("❌ [DEBUG] Impossibile recuperare gli ordini dopo 3 tentativi.")
    return None, None

def piazza_nuova_griglia(prezzo_rif):
    print("-> [DEBUG] Preparazione piazzamento nuova griglia...")
    cancella_tutti_ordini()

    # Recuperiamo il budget dinamico calcolato sul saldo EUR attuale
    budget_step = calcola_budget_dinamico()

    prezzo_buy = prezzo_rif * (1.0 - GRID_DIST_PCT)
    prezzo_sell = prezzo_rif * (1.0 + GRID_DIST_PCT)
    
    # Calcolo quantita ETH troncando a 5 decimali per evitare rifiuti sul book di Coinbase
    quantita_eth_sell = round(budget_step / prezzo_sell, 5)

    for tentativo in range(3):
        try:
            # 1. LIMIT BUY
            id_buy = f"lbuy_{int(time.time())}"
            print(f"-> [DEBUG] Invio Limit BUY a {prezzo_buy:.2f} EUR (Valore: {budget_step:.2f} EUR)...")
            client.create_order(
                client_order_id=id_buy,
                product_id=PRODUCT_ID,
                side="BUY",
                order_configuration={
                    "limit_limit_gtc": {
                        "quote_size": f"{budget_step:.2f}",
                        "limit_price": f"{prezzo_buy:.2f}",
                        "post_only": False
                    }
                }
            )

            # 2. LIMIT SELL
            id_sell = f"lsell_{int(time.time())}"
            print(f"-> [DEBUG] Invio Limit SELL a {prezzo_sell:.2f} EUR (Quantità: {quantita_eth_sell:.5f} ETH)...")
            client.create_order(
                client_order_id=id_sell,
                product_id=PRODUCT_ID,
                side="SELL",
                order_configuration={
                    "limit_limit_gtc": {
                        "base_size": f"{quantita_eth_sell:.5f}",
                        "limit_price": f"{prezzo_sell:.2f}",
                        "post_only": False
                    }
                }
            )

            print("📐 Griglia dinamica inviata con successo a Coinbase!")
            return True

        except Exception as e:
            print(f"⚠️ [Tentativo {tentativo+1}/3] Errore invio ordini: {e}")
            time.sleep(2)
    return False

def main():
    print("4. [DEBUG] Lettura prezzo salvato...")
    prezzo_riferimento = leggi_prezzo_salvato()
    print(f"5. [DEBUG] Prezzo salvato nel file: {prezzo_riferimento}")

    id_ordine_acquisto, id_ordine_vendita = recupera_ordini_griglia_esistenti()
    print(f"6. [DEBUG] Analisi completata. Buy: {id_ordine_acquisto} | Sell: {id_ordine_vendita}")

    if id_ordine_acquisto is None and id_ordine_vendita is None and prezzo_riferimento is None:
        print("❌ [DEBUG] Recupero dati fallito per problemi di rete. Termino l'esecuzione per sicurezza.")
        return

    if id_ordine_acquisto is None and id_ordine_vendita is None:
        if prezzo_riferimento is None:
            prezzo_riferimento = ottieni_prezzo_reale()
            if prezzo_riferimento:
                salva_prezzo(prezzo_riferimento)

        if prezzo_riferimento:
            print("Nessun ordine attivo trovato. Genero nuova griglia...")
            piazza_nuova_griglia(prezzo_riferimento)
        return

    eseguito_acquisto = False
    eseguito_vendita = False

    if id_ordine_acquisto:
        stato_buy = controlla_stato_ordine(id_ordine_acquisto)
        print(f"-> [DEBUG] Stato ordine d'acquisto: {stato_buy}")
        if stato_buy == "FILLED":
            eseguito_acquisto = True
    else:
        print("⚠️ [DEBUG] Ordine ACQUISTO non rilevato sul book.")

    if id_ordine_vendita:
        stato_sell = controlla_stato_ordine(id_ordine_vendita)
        print(f"-> [DEBUG] Stato ordine di vendita: {stato_sell}")
        if stato_sell == "FILLED":
            eseguito_vendita = True
    else:
        print("⚠️ [DEBUG] Ordine VENDITA non rilevato sul book.")

    # --- LOGICA DI SICUREZZA AGGIORNATA ---
    if eseguito_acquisto:
        nuovo_pivot = prezzo_riferimento * (1.0 - GRID_DIST_PCT)
        salva_prezzo(nuovo_pivot)
        if piazza_nuova_griglia(nuovo_pivot):
            invia_telegram(f"🟢 *COINBASE: ACQUISTO COMPLETATO!*\nPrezzo: *{nuovo_pivot:.2f} EUR*.")

    elif eseguito_vendita:
        nuovo_pivot = prezzo_riferimento * (1.0 + GRID_DIST_PCT)
        salva_prezzo(nuovo_pivot)
        if piazza_nuova_griglia(nuovo_pivot):
            invia_telegram(f"🔴 *COINBASE: VENDITA COMPLETATA!*\nPrezzo: *{nuovo_pivot:.2f} EUR*.")

    # Rilevamento asimmetria: uno dei due ordini è sparito senza essere stato riempito (caso tuo screenshot)
    elif (id_ordine_acquisto is None and id_ordine_vendita is not None) or (id_ordine_acquisto is not None and id_ordine_vendita is None):
        print("⚠️ [DEBUG] Rilevata griglia asimmetrica (un ordine manca all'appello). Sblocco la situazione...")
        nuovo_prezzo = ottieni_prezzo_reale()
        if nuovo_prezzo:
            salva_prezzo(nuovo_prezzo)
            piazza_nuova_griglia(nuovo_prezzo)

    else:
        print("7. [DEBUG] Entrambi gli ordini sono regolarmente aperti e pendenti. Esco in silenzio.")

if __name__ == "__main__":
    main()
