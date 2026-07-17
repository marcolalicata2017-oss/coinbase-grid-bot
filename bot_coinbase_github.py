import time
import requests
import os
import sys
import subprocess
from coinbase.rest import RESTClient

print("1. [DEBUG] Avvio dello script (Flusso Ottimizzato con Rilevamento Intelligente Esecuzioni)...")

# ================= CONFIGURAZIONE UTENTE =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINBASE_KEY_NAME = os.getenv("COINBASE_KEY_NAME")
COINBASE_KEY_SECRET = os.getenv("COINBASE_KEY_SECRET")

PRODUCT_ID = "ETH-EUR"       
GRID_DIST_PCT = 0.0120       
FILE_STATO = "stato_bot.txt"  

# --- PARAMETRI COMPOSITING DINAMICO ---
PERCENTUALE_BUDGET = 0.10    # Usa il 10% del saldo EUR libero su Coinbase
MIN_BUDGET_EUR = 15.00        # Soglia minima di sicurezza imposta da Coinbase
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
        print("-> [DEBUG] Esecuzione git pull preventivo per sincronizzare lo stato...")
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "--permanent-auth", "pull", "--rebase", "origin", "main"], timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"⚠️ [DEBUG] Avviso durante il git pull: {e}. Procedo comunque.")

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
        print(f"-> [DEBUG] Prezzo {prezzo:.2f} salvato nel file locale.")
    except Exception as e: 
        print(f"Errore salvataggio file: {e}")

def ottieni_prezzo_reale():
    print("-> [DEBUG] Richiesta prezzo ETH...")
    for tentativo in range(3):
        try: 
            res = client.get_product(product_id=PRODUCT_ID)
            prezzo_str = res.get('price') if isinstance(res, dict) else getattr(res, 'price', None)
            if prezzo_str:
                return float(prezzo_str)
        except Exception as e: 
            time.sleep(2)
    return None

def controlla_saldo_eur():
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
                    return saldo_libero
        except Exception as e:
            time.sleep(2)
    return 0.0

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
                        c_id = o.get('client_order_id', '') if isinstance(o, dict) else getattr(o, 'client_order_id', '')
                        o_id = o.get('order_id') if isinstance(o, dict) else getattr(o, 'order_id', None)
                        if 'lbuy_' in str(c_id): id_buy = o_id
                        elif 'lsell_' in str(c_id): id_sell = o_id
            return id_buy, id_sell
        except Exception as e:
            time.sleep(2)
    return None, None

def piazza_nuova_griglia(prezzo_rif, motivo_reset="Reset", tipo_notifica="RESET"):
    print(f"-> [DEBUG] Preparazione piazzamento nuova griglia per: {motivo_reset}...")
    
    saldo_eur = controlla_saldo_eur()
    prezzo_buy = prezzo_rif * (1.0 - GRID_DIST_PCT)
    prezzo_sell = prezzo_rif * (1.0 + GRID_DIST_PCT)
    
    budget_buy_teorico = max(saldo_eur * PERCENTUALE_BUDGET, MIN_BUDGET_EUR)
    quantita_eth_fissa = budget_buy_teorico / prezzo_buy
    
    cancella_tutti_ordini()
    
    piazza_buy = True
    if saldo_eur < MIN_BUDGET_EUR:
        print(f"⚠️ [ECCEZIONE] Saldo EUR insufficiente ({saldo_eur:.2f} EUR). Salto il BUY.")
        piazza_buy = False

    for tentativo in range(3):
        try:
            if piazza_buy:
                id_buy = f"lbuy_{int(time.time())}"
                client.create_order(
                    client_order_id=id_buy, product_id=PRODUCT_ID, side="BUY",
                    order_configuration={"limit_limit_gtc": {"quote_size": f"{budget_buy_teorico:.2f}", "limit_price": f"{prezzo_buy:.2f}", "post_only": False}}
                )
            
            id_sell = f"lsell_{int(time.time()) + 1}"
            client.create_order(
                client_order_id=id_sell, product_id=PRODUCT_ID, side="SELL",
                order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_eth_fissa:.5f}", "limit_price": f"{prezzo_sell:.2f}", "post_only": False}}
            )
            
            # --- STRUTTURA DELLE NOTIFICHE IN BASE AL CONTESTO ---
            if tipo_notifica == "ACQUISTO":
                msg_telegram = f"🟢 *COINBASE: ACQUISTO COMPLETATO!*\n" \
                               f"Nuovo Pivot: *{prezzo_rif:.2f} EUR*\n" \
                               f"Saldo Libero: *{saldo_eur:.2f} EUR*"
            elif tipo_notifica == "VENDITA":
                msg_telegram = f"🔴 *COINBASE: VENDITA COMPLETATA!*\n" \
                               f"Nuovo Pivot: *{prezzo_rif:.2f} EUR*\n" \
                               f"Profitti Incassati! Saldo: *{saldo_eur:.2f} EUR*"
            else:
                msg_telegram = f"🔄 *COINBASE: GRIGLIA RESETTATA*\n" \
                               f"Motivo: _{motivo_reset}_\n" \
                               f"Prezzo Pivot: *{prezzo_rif:.2f} EUR*\n" \
                               f"Saldo Libero: *{saldo_eur:.2f} EUR*"
                               
            if not piazza_buy:
                msg_telegram += f"\n⚠️ _Solo ordine SELL attivo (Euro < {MIN_BUDGET_EUR}€)_"
                
            invia_telegram(msg_telegram)
            return True
        except Exception as e:
            print(f"⚠️ Errore invio ordini: {e}")
            time.sleep(2)
    return False

def esegui_singolo_controllo():
    prezzo_riferimento = leggi_prezzo_salvato()
    id_ordine_acquisto, id_ordine_vendita = recupera_ordini_griglia_esistenti()
    
    # 1. Prima inizializzazione assoluta
    if id_ordine_acquisto is None and id_ordine_vendita is None and prezzo_riferimento is None:
        prezzo_riferimento = ottieni_prezzo_reale()
        if prezzo_riferimento:
            salva_prezzo(prezzo_riferimento)
            piazza_nuova_griglia(prezzo_riferimento, motivo_reset="Prima Inizializzazione", tipo_notifica="RESET")
        return
        
    # 2. SE ENTRAMBI GLI ORDINI SONO SPARITI DAL BOOK MA IL PIVOT ESISTE (Il nocciolo del problema)
    if id_ordine_acquisto is None and id_ordine_vendita is None and prezzo_riferimento is not None:
        print("-> [DEBUG] Entrambi gli ordini sono spariti dagli OPEN. Verifico la posizione del mercato...")
        prezzo_spot = ottieni_prezzo_reale()
        if prezzo_spot:
            if prezzo_spot < prezzo_riferimento:
                # Il mercato è sceso sotto il pivot: ha eseguito l'acquisto
                nuovo_pivot = prezzo_riferimento * (1.0 - GRID_DIST_PCT)
                salva_prezzo(nuovo_pivot)
                piazza_nuova_griglia(nuovo_pivot, motivo_reset="Esecuzione Acquisto Rilevata", tipo_notifica="ACQUISTO")
            else:
                # Il mercato è salito sopra il pivot: ha eseguito la vendita
                nuovo_pivot = prezzo_riferimento * (1.0 + GRID_DIST_PCT)
                salva_prezzo(nuovo_pivot)
                piazza_nuova_griglia(nuovo_pivot, motivo_reset="Esecuzione Vendita Rilevata", tipo_notifica="VENDITA")
        return

    # 3. SE UN SOLO ORDINE È SPARITO DALLO STATO OPEN (Asimmetria temporanea da ritardo API)
    if (id_ordine_acquisto is None and id_ordine_vendita is not None) or (id_ordine_acquisto is not None and id_ordine_vendita is None):
        print("-> [DEBUG] Rilevato sbilanciamento momentaneo. Interrogo il prezzo spot per determinare l'eseguito...")
        prezzo_spot = ottieni_prezzo_reale()
        if prezzo_spot and prezzo_riferimento:
            if prezzo_spot < prezzo_riferimento and id_ordine_acquisto is None:
                # Mancava l'acquisto ed il prezzo conferma il trend in discesa
                nuovo_pivot = prezzo_riferimento * (1.0 - GRID_DIST_PCT)
                salva_prezzo(nuovo_pivot)
                piazza_nuova_griglia(nuovo_pivot, motivo_reset="Esecuzione Acquisto (Da Asimmetria)", tipo_notifica="ACQUISTO")
            elif prezzo_spot > prezzo_riferimento and id_ordine_vendita is None:
                # Mancava la vendita ed il prezzo conferma il trend in salita
                nuovo_pivot = prezzo_riferimento * (1.0 + GRID_DIST_PCT)
                salva_prezzo(nuovo_pivot)
                piazza_nuova_griglia(nuovo_pivot, motivo_reset="Esecuzione Vendita (Da Asimmetria)", tipo_notifica="VENDITA")
            else:
                # Caso limite: asimmetria casuale o ordine rimosso a mano -> Reset standard prudenziale
                salva_prezzo(prezzo_spot)
                piazza_nuova_griglia(prezzo_spot, motivo_reset="Reset Asimmetria Generica", tipo_notifica="RESET")
        return

    # 4. CONTROLLO STANDARD (Se entrambi gli ordini sono presenti, controlliamo il FILLED classico)
    eseguito_acquisto = False
    eseguito_vendita = False

    if id_ordine_acquisto:
        if controlla_stato_ordine(id_ordine_acquisto) == "FILLED": eseguito_acquisto = True
    if id_ordine_vendita:
        if controlla_stato_ordine(id_ordine_vendita) == "FILLED": eseguito_vendita = True

    if eseguito_acquisto:
        nuovo_pivot = prezzo_riferimento * (1.0 - GRID_DIST_PCT)
        salva_prezzo(nuovo_pivot)
        piazza_nuova_griglia(nuovo_pivot, motivo_reset="Esecuzione Standard BUY", tipo_notifica="ACQUISTO")
    elif eseguito_vendita:
        nuovo_pivot = prezzo_riferimento * (1.0 + GRID_DIST_PCT)
        salva_prezzo(nuovo_pivot)
        piazza_nuova_griglia(nuovo_pivot, motivo_reset="Esecuzione Standard SELL", tipo_notifica="VENDITA")
    else:
        print("-> [DEBUG] Ordini pendenti analizzati. Nessun movimento rilevato.")

def main():
    totale_cicli = 11
    minuti_attesa = 5
    
    print("-> [DEBUG] Avvio sessione di monitoraggio in background...")

    for ciclo in range(1, totale_cicli + 1):
        print(f"\n⏱️ === INIZIO CICLO {ciclo} DI {totale_cicli} ===")
        try:
            esegui_singolo_controllo()
        except Exception as e:
            print(f"❌ Errore critico nel ciclo {ciclo}: {e}")
            
        if ciclo < totale_cicli:
            print(f"Ciclo completato. In attesa di {minuti_attesa} minuti...")
            time.sleep(minuti_attesa * 60)
            
    print("\n🏁 Sessione di monitoraggio completata. Il workflow termina qui.")

if __name__ == "__main__":
    main()
