import time
import requests
import os
from coinbase.rest import RESTClient

# ================= CONFIGURAZIONE UTENTE (DA SELEZIONARE VIA GITHUB SECRETS) =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINBASE_KEY_NAME = os.getenv("COINBASE_KEY_NAME")
COINBASE_KEY_SECRET = os.getenv("COINBASE_KEY_SECRET")

PRODUCT_ID = "ETH-EUR"       
BUDGET_STEP_EUR = 19.90      
GRID_DIST_PCT = 0.0120       
FILE_STATO = "stato_bot.txt"  
# ============================================================================================

client = RESTClient(api_key=COINBASE_KEY_NAME, api_secret=COINBASE_KEY_SECRET)

def invia_telegram(messaggio):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": messaggio, "parse_mode": "Markdown"}
    try: 
        # NESSUN PROXY SU GITHUB: Connessione diretta e istantanea
        requests.post(url, json=payload, timeout=10)
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
    try: return float(client.get_product(product_id=PRODUCT_ID)['price'])
    except: return None

def cancella_tutti_ordini():
    try:
        ordini = client.list_orders(order_status=["OPEN"])
        if 'orders' in ordini:
            id_ordini = [o['order_id'] for o in ordini['orders'] if o['product_id'] == PRODUCT_ID]
            if id_ordini:
                client.cancel_orders(order_ids=id_ordini)
                time.sleep(2)
    except Exception as e:
        print(f"Errore cancellazione ordini: {e}")

def controlla_stato_ordine(order_id):
    try:
        ordine = client.get_order(order_id=order_id)
        return ordine['order']['status']
    except:
        return "UNKNOWN"

def recupera_ordini_griglia_esistenti():
    id_buy, id_sell = None, None
    try:
        ordini_aperti = client.list_orders(order_status=["OPEN"])
        if 'orders' in ordini_aperti:
            for o in ordini_aperti['orders']:
                if o['product_id'] == PRODUCT_ID:
                    c_id = o.get('client_order_id', '')
                    if 'lbuy_' in c_id:
                        id_buy = o['order_id']
                    elif 'lsell_' in c_id:
                        id_sell = o['order_id']
    except Exception as e:
        print(f"Errore recupero ordini: {e}")
    return id_buy, id_sell

def piazza_nuova_griglia(prezzo_rif):
    cancella_tutti_ordini()
    
    prezzo_buy = prezzo_rif * (1.0 - GRID_DIST_PCT)
    prezzo_sell = prezzo_rif * (1.0 + GRID_DIST_PCT)
    quantita_eth_sell = BUDGET_STEP_EUR / prezzo_sell
    
    try:
        # 1. LIMIT BUY
        id_buy = f"lbuy_{int(time.time())}"
        ord_buy = client.create_order(
            client_order_id=id_buy,
            product_id=PRODUCT_ID,
            side="BUY",
            order_configuration={
                "limit_limit_gtc": {
                    "quote_size": f"{BUDGET_STEP_EUR:.2f}",
                    "limit_price": f"{prezzo_buy:.2f}",
                    "post_only": False
                }
            }
        )
        id_acq = ord_buy.get('order_id') if isinstance(ord_buy, dict) else ord_buy.order_id
        
        # 2. LIMIT SELL
        id_sell = f"lsell_{int(time.time())}"
        ord_sell = client.create_order(
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
        id_ven = ord_sell.get('order_id') if isinstance(ord_sell, dict) else ord_sell.order_id
        
        if id_acq and id_ven:
            print(f"📐 Griglia piazzata. Buy: {prezzo_buy:.2f} | Sell: {prezzo_sell:.2f}")
            return True
    except Exception as e:
        print(f"Errore piazzamento ordini: {e}")
    return False

def main():
    prezzo_riferimento = leggi_prezzo_salvato()
    id_ordine_acquisto, id_ordine_vendita = recupera_ordini_griglia_esistenti()
    
    if id_ordine_acquisto is None and id_ordine_vendita is None:
        if prezzo_riferimento is None:
            prezzo_riferimento = ottieni_prezzo_reale()
            if prezzo_riferimento:
                salva_prezzo(prezzo_riferimento)
        
        if prezzo_riferimento:
            print("Nessun ordine sul book. Rigenerazione griglia...")
            piazza_nuova_griglia(prezzo_riferimento)
        return

    eseguito_acquisto = False
    eseguito_vendita = False

    if id_ordine_acquisto:
        stato_buy = controlla_stato_ordine(id_ordine_acquisto)
        if stato_buy == "FILLED":
            eseguito_acquisto = True

    if id_ordine_vendita:
        stato_sell = controlla_stato_ordine(id_ordine_vendita)
        if stato_sell == "FILLED":
            eseguito_vendita = True

    if eseguito_acquisto:
        nuovo_pivot = prezzo_riferimento * (1.0 - GRID_DIST_PCT)
        salva_prezzo(nuovo_pivot)
        if piazza_nuova_griglia(nuovo_pivot):
            invia_telegram(
                f"🟢 *COINBASE: ACQUISTO COMPLETATO!*\n"
                f"L'ordine Limit è stato eseguito a circa *{nuovo_pivot:.2f} EUR*.\n"
                f"Nuova griglia riposizionata."
            )
            
    elif eseguito_vendita:
        nuovo_pivot = prezzo_riferimento * (1.0 + GRID_DIST_PCT)
        salva_prezzo(nuovo_pivot)
        if piazza_nuova_griglia(nuovo_pivot):
            invia_telegram(
                f"🔴 *COINBASE: VENDITA COMPLETATA!*\n"
                f"Profitto incassato a circa *{nuovo_pivot:.2f} EUR*.\n"
                f"Nuova griglia riposizionata."
            )
    else:
        print("Entrambi gli ordini sono ancora pendenti sul book. Esco.")

if __name__ == "__main__":
    main()
