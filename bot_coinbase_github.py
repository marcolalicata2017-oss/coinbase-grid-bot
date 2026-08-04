import os
import time
import uuid
import json
import requests
import joblib
import subprocess
import numpy as np
import pandas as pd
from datetime import datetime
from coinbase.rest import RESTClient

# ==========================================
# CONFIGURAZIONE GENERALE & CARICAMENTO DINAMICO
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINBASE_KEY_NAME = os.getenv("COINBASE_KEY_NAME")
COINBASE_KEY_SECRET = os.getenv("COINBASE_KEY_SECRET")

FILE_CONFIG = "config.json"
FILE_DIARIO = "diario_di_bordo.csv"
FILE_PORTAFOGLIO_GIORNALIERO = "storico_portafoglio_giornaliero.csv"
FILE_MODELLO_ML = "modello_volatilta.pkl"

# Mappa visuale per le notifiche Telegram
# Mappa visuale per le notifiche Telegram
EMOJI_MAP = {
    "BTC": "🪙",
    "ETH": "🔷",
    "SOL": "🟣",
    "DEFAULT_SATELLITE": "🛰️"  # Icona spaziale predefinita per il modulo Satellite (oppure 🚀)
}

def ottieni_decimali_asset(pair):
    """Interroga l'API pubblica di Coinbase e restituisce il numero esatto di decimali ammessi per la quantità."""
    try:
        url = f"https://api.exchange.coinbase.com/products/{pair}"
        headers = {"User-Agent": "Python-Bot"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            base_increment = data.get("base_increment", "0.01")
            if "." in base_increment:
                return len(base_increment.split(".")[1].rstrip("0"))
    except Exception as e:
        print(f"⚠️ Errore lettura decimali per {pair} da API Coinbase: {e}", flush=True)
    
    # Fallback di sicurezza in caso di API irraggiungibile
    fallback_map = {"BTC-EUR": 8, "ETH-EUR": 4, "SOL-EUR": 2, "LINK-EUR": 2}
    return fallback_map.get(pair, 2)
    
def carica_e_sincronizza_config():
    """Carica dinamicamente qualsiasi asset presente in config.json recuperando la precisione dei decimali direttamente da Coinbase."""
    global CONFIG_ASSETS
    if os.path.exists(FILE_CONFIG):
        try:
            with open(FILE_CONFIG, "r", encoding="utf-8") as f:
                cfg_json = json.load(f)
            
            assets_json = cfg_json.get("assets", {})
            nuovo_config = {}
            
            for pair, data in assets_json.items():
                sym = pair.split("-")[0]
                asset_type = data.get("type", "core")
                
                # 1. Assegna l'emoji (satellite vs core)
                if asset_type == "satellite":
                    emoji = EMOJI_MAP.get("DEFAULT_SATELLITE", "🛰️")
                else:
                    emoji = EMOJI_MAP.get(sym, "🪙")
                
                # 2. Estrazione dinamica e automatica dei decimali reali via API Coinbase
                decimals = ottieni_decimali_asset(pair)
                
                nuovo_config[pair] = {
                    "grid_dist": data.get("grid_dist_buy", 0.015),
                    "grid_dist_sell": data.get("grid_dist_sell", 0.015),
                    "emoji": emoji,
                    "min_order_eur": 5.0,
                    "decimals": decimals,
                    "target_weight_pct": data.get("target_weight_pct", 0.0),
                    "type": asset_type,
                    "is_active": data.get("is_active", True),
                    "exit_strategy": data.get("exit_strategy", "none")
                }
            
            if nuovo_config:
                CONFIG_ASSETS = nuovo_config
                print(f"✅ [CONFIG] Caricati {len(CONFIG_ASSETS)} asset attivi da config.json: {list(CONFIG_ASSETS.keys())}", flush=True)
        except Exception as e:
            print(f"⚠️ [CONFIG] Errore caricamento config.json: {e}", flush=True)

# Caricamento iniziale
carica_e_sincronizza_config()

SOGLIA_EMA_TOLLERANZA = 0.95
client = RESTClient(api_key=COINBASE_KEY_NAME, api_secret=COINBASE_KEY_SECRET, timeout=10)
ULTIMO_STATO_CB = {}

MODELLO_ML = None
if os.path.exists(FILE_MODELLO_ML):
    try:
        MODELLO_ML = joblib.load(FILE_MODELLO_ML)
        print("🤖 [ML INFERENCE] Modello di volatilità caricato con successo!", flush=True)
    except Exception as e:
        print(f"⚠️ [ML INFERENCE] Errore caricamento modello: {e}", flush=True)

# ==========================================
# UTILITIES TELEGRAM & DIARIO DI BORDO
# ==========================================
def invia_telegram(messaggio):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": messaggio, "parse_mode": "Markdown"}
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print(f"⚠️ Errore invio Telegram: {e}", flush=True)

def registra_su_diario_di_bordo(pair, prezzo_pivot, ema50, saldo_eur, crypto_posseduta, motivo, trend_ok,
                                rsi=50.0, vol_ratio=1.0, target_buy=0.0, target_sell=0.0, 
                                grid_buy_pct=0.0, grid_sell_pct=0.0):
    ora_corrente = time.strftime("%Y-%m-%d %H:%M:%S")
    file_esistente = os.path.exists(FILE_DIARIO)
    
    if "Riallineamento" in motivo and "SELL" in motivo:
        motivo = "SELL Eseguito su Exchange (Saldo Riallineato)"

    intestazione = "Data_Ora,Pair,Prezzo_Pivot,EMA50,Saldo_EUR_Pool,Crypto_Posseduta,Trend_OK,RSI,Vol_Ratio,Target_BUY,Target_SELL,Grid_BUY_Pct,Grid_SELL_Pct,Motivo\n"
    riga = f"{ora_corrente},{pair},{prezzo_pivot:.2f},{ema50:.2f},{saldo_eur:.2f},{crypto_posseduta:.5f},{trend_ok},{rsi:.1f},{vol_ratio:.2f},{target_buy:.2f},{target_sell:.2f},{grid_buy_pct*100:.2f}%,{grid_sell_pct*100:.2f}%,{motivo}\n"

    try:
        with open(FILE_DIARIO, "a", encoding="utf-8") as f:
            if not file_esistente:
                f.write(intestazione)
            f.write(riga)
    except Exception as e:
        print(f"⚠️ Errore scrittura diario ({pair}): {e}", flush=True)

# ==========================================
# TRACCIAMENTO PORTAFOGLIO
# ==========================================
def genera_barra_progresso(percentuale, lung=10):
    p = max(0.0, min(1.0, percentuale))
    pieni = int(round(p * lung))
    vuoti = lung - pieni
    return "█" * pieni + "░" * vuoti

def traccia_portafoglio_giornaliero(prezzi_attuali, saldo_eur_totale, dict_cripto_totale, stati_cb):
    ora_dt = datetime.now()
    oggi = ora_dt.strftime("%Y-%m-%d")

    valore_cripto_totale = 0.0
    dettagli_cripto_val = {}
    
    for pair, prezzo in prezzi_attuali.items():
        sym = pair.split("-")[0]
        qta = dict_cripto_totale.get(sym, 0.0)
        val = qta * (prezzo if prezzo else 0.0)
        dettagli_cripto_val[sym] = (val, qta)
        valore_cripto_totale += val

    valore_totale = saldo_eur_totale + valore_cripto_totale

    file_esiste = os.path.exists(FILE_PORTAFOGLIO_GIORNALIERO)
    gia_registrato_oggi = False

    if file_esiste:
        try:
            with open(FILE_PORTAFOGLIO_GIORNALIERO, "r", encoding="utf-8") as f:
                righe = f.readlines()
                if any(riga.startswith(oggi) for riga in righe):
                    gia_registrato_oggi = True
        except: pass

    if not gia_registrato_oggi:
        print(f"📊 [CSV] Registrazione portafoglio per il giorno {oggi}...", flush=True)
        intestazione = "Data,Saldo_EUR,Valore_Crypto_EUR,Valore_Totale_EUR\n"
        riga = f"{oggi},{saldo_eur_totale:.2f},{valore_cripto_totale:.2f},{valore_totale:.2f}\n"
        
        try:
            with open(FILE_PORTAFOGLIO_GIORNALIERO, "a", encoding="utf-8") as f:
                if not file_esiste:
                    f.write(intestazione)
                f.write(riga)
        except Exception as e:
            print(f"Errore registrazione CSV portafoglio: {e}", flush=True)

# ==========================================
# API COINBASE & MERCATO
# ==========================================
def ottieni_dati_mercato_avanzati(product_id):
    url = f"https://api.exchange.coinbase.com/products/{product_id}/candles?granularity=3600"
    headers = {"User-Agent": "Python-Bot"}
    for tentativo in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) >= 12:  # Soglia ridotta a 12 candele
                    candele = list(reversed(data))
                    prezzi_chiusura = [float(c[4]) for c in candele]
                    volumi = [float(c[5]) for c in candele]

                    s_prezzi = pd.Series(prezzi_chiusura)
                    s_volumi = pd.Series(volumi)

                    prezzo_attuale = prezzi_chiusura[-1]
                    span_ema = min(50, len(s_prezzi))
                    ema50 = s_prezzi.ewm(span=span_ema, adjust=False).mean().iloc[-1]

                    delta = s_prezzi.diff()
                    window_rsi = min(14, len(s_prezzi) - 1)
                    gain = (delta.where(delta > 0, 0)).rolling(window=max(1, window_rsi)).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(window=max(1, window_rsi)).mean()
                    rs = gain / loss
                    rsi_series = 100 - (100 / (1 + rs))
                    rsi_attuale = rsi_series.iloc[-1] if not pd.isna(rsi_series.iloc[-1]) else 50.0

                    vol_ora_attuale = s_volumi.iloc[-1]
                    vol_medio = s_volumi.tail(min(24, len(s_volumi))).mean()
                    volume_ratio = (vol_ora_attuale / vol_medio) if vol_medio > 0 else 1.0

                    returns = s_prezzi.pct_change()
                    returns_ultimo = returns.iloc[-1] if not pd.isna(returns.iloc[-1]) else 0.0
                    vol_24h = returns.tail(min(24, len(returns))).std()
                    vol_24h = 0.0 if pd.isna(vol_24h) else vol_24h

                    return prezzo_attuale, ema50, returns_ultimo, vol_24h, rsi_attuale, volume_ratio
        except Exception as e:
            print(f"⚠️ Errore API candele ({product_id}): {e}", flush=True)
        time.sleep(1)
    
    # Backup: se le candele falliscono, recupera almeno il prezzo ticker corrente
    try:
        url_ticker = f"https://api.exchange.coinbase.com/products/{product_id}/ticker"
        resp_t = requests.get(url_ticker, headers=headers, timeout=5)
        if resp_t.status_code == 200:
            px = float(resp_t.json().get('price', 0.0))
            if px > 0:
                print(f"⚠️ [BACKUP TICKER] Dati candele insufficienti per {product_id}. Usato prezzo istantaneo: {px}", flush=True)
                return px, px, 0.0, 0.0, 50.0, 1.0
    except Exception as e:
        print(f"❌ Fallito recupero ticker di emergenza per {product_id}: {e}", flush=True)

    print(f"❌ [SKIP] Impossibile recuperare i dati di mercato per {product_id}", flush=True)
    return None, None, 0.0, 0.0, 50.0, 1.0

def controlla_saldi_globali():
    saldo_eur_totale = 0.0
    cripto_dict_totale = {}
    
    for tentativo in range(3):
        try:
            conti = client.get_accounts()
            lista_conti = conti.get('accounts', []) if isinstance(conti, dict) else getattr(conti, 'accounts', [])
            
            for conto in lista_conti:
                valuta = conto.get('currency') if isinstance(conto, dict) else getattr(conto, 'currency', None)
                disp_obj = conto.get('available_balance', {}) if isinstance(conto, dict) else getattr(conto, 'available_balance', {})
                hold_obj = conto.get('hold', {}) if isinstance(conto, dict) else getattr(conto, 'hold', {})
                
                def estrai_valore(obj):
                    if not obj: return 0.0
                    if isinstance(obj, dict):
                        return float(obj.get('value', 0.0))
                    elif hasattr(obj, 'value'):
                        return float(getattr(obj, 'value', 0.0))
                    try: return float(obj)
                    except: return 0.0

                v_disp = estrai_valore(disp_obj)
                v_hold = estrai_valore(hold_obj)
                valore_totale = v_disp + v_hold
                
                if valuta == "EUR":
                    saldo_eur_totale = valore_totale
                elif valuta:
                    cripto_dict_totale[valuta] = valore_totale
                    
            return saldo_eur_totale, cripto_dict_totale
        except Exception as e:
            print(f"⚠️ Errore lettura saldi (tentativo {tentativo+1}): {e}", flush=True)
            time.sleep(2)
            
    return saldo_eur_totale, cripto_dict_totale

def recupera_ordini_pair(product_id):
    id_buy, id_sell = None, None
    for tentativo in range(3):
        try:
            res = client.list_orders(product_id=product_id, order_status=["OPEN"])
            ordini = res.get('orders', []) if isinstance(res, dict) else getattr(res, 'orders', [])
            for o in ordini:
                side = o.get('side') if isinstance(o, dict) else getattr(o, 'side', None)
                o_id = o.get('order_id') if isinstance(o, dict) else getattr(o, 'order_id', None)
                if side == "BUY": id_buy = o_id
                elif side == "SELL": id_sell = o_id
            return id_buy, id_sell
        except Exception as e:
            print(f"⚠️ Errore lettura ordini ({product_id}): {e}", flush=True)
            time.sleep(2)
    return None, None

def cancella_ordini_pair(product_id, cancella_solo_buy=False):
    try:
        res = client.list_orders(product_id=product_id, order_status=["OPEN"])
        ordini = res.get('orders', []) if isinstance(res, dict) else getattr(res, 'orders', [])
        ids_da_cancellare = []
        if ordini:
            for o in ordini:
                side = o.get('side') if isinstance(o, dict) else getattr(o, 'side', None)
                o_id = o.get('order_id') if isinstance(o, dict) else getattr(o, 'order_id', None)
                if cancella_solo_buy:
                    if side == "BUY" and o_id: ids_da_cancellare.append(o_id)
                else:
                    if o_id: ids_da_cancellare.append(o_id)

        if ids_da_cancellare:
            client.cancel_orders(order_ids=ids_da_cancellare)
            print(f"-> [DEBUG] Cancellati ordini per {product_id}", flush=True)
    except Exception as e:
        print(f"⚠️ Errore cancellazione ordini {product_id}: {e}", flush=True)

# ==========================================
# LOGICA DI PIAZZAMENTO GRIGLIA
# ==========================================
def piazza_nuova_griglia(pair, prezzo_rif, autorizza_buy=True, motivo_reset="Reset", 
                         ema50=0.0, returns_24h=0.0, vol_24h=0.0, rsi=50.0, volume_ratio=1.0,
                         valore_totale_portafoglio=0.0):
    global ULTIMO_STATO_CB
    cfg = CONFIG_ASSETS[pair]
    symbol_crypto = pair.split("-")[0]
    grid_dist_base = cfg.get("grid_dist", 0.012)
    grid_dist_sell_base = cfg.get("grid_dist_sell", grid_dist_base)
    min_order_eur = cfg["min_order_eur"]
    dec = cfg["decimals"]
    emoji = cfg["emoji"]
    target_weight_pct = cfg.get("target_weight_pct", 10.0)

    # 1. Spaziatura Dinamica ML / Dynamic Profit
    grid_dist_buy = grid_dist_base
    if MODELLO_ML is not None and ema50 > 0:
        try:
            dist_ema50 = (prezzo_rif - ema50) / ema50
            input_ml = [[returns_24h, vol_24h, dist_ema50]]
            predizione_alta_vol = MODELLO_ML.predict(input_ml)[0]
            if predizione_alta_vol == 1:
                grid_dist_buy = grid_dist_base * 1.5
                motivo_reset += " ⚡[ML: High Vol Grid]"
        except Exception as e:
            print(f"⚠️ Errore ML su {pair}: {e}", flush=True)

    if rsi >= 65 and volume_ratio >= 1.5:
        grid_dist_sell = max(grid_dist_sell_base * 2.0, 0.025)
        label_profit = f" 🚀[Dynamic Profit HIGH: +{grid_dist_sell*100:.1f}%]"
    elif rsi >= 55:
        grid_dist_sell = grid_dist_sell_base * 1.3
        label_profit = f" 📈[Dynamic Profit MED: +{grid_dist_sell*100:.1f}%]"
    elif rsi <= 40:
        grid_dist_sell = max(grid_dist_sell_base * 0.75, 0.008)
        label_profit = f" 🎯[Dynamic Profit FAST: +{grid_dist_sell*100:.1f}%]"
    else:
        grid_dist_sell = grid_dist_sell_base
        label_profit = ""

    motivo_reset += label_profit

    saldo_eur_totale, dict_cripto_totale = controlla_saldi_globali()
    crypto_posseduta = dict_cripto_totale.get(symbol_crypto, 0.0)

    budget_totale_asset = (valore_totale_portafoglio * target_weight_pct) / 100.0 if valore_totale_portafoglio > 0 else saldo_eur_totale
    budget_buy_teorico = max(budget_totale_asset * 0.20, min_order_eur)

    cancella_ordini_pair(pair)

    valore_crypto_eur = crypto_posseduta * prezzo_rif
    ordine_inviato_con_successo = False

    # 2. STARTER BUY A MERCATO (Solo ed esclusivamente alla primissima inizializzazione a saldo 0)
    is_primo_ingresso = (crypto_posseduta == 0 and "Nuova Coin" in motivo_reset)
    if is_primo_ingresso and saldo_eur_totale >= min_order_eur:
        print(f"🛒 [{pair} STARTER BUY A MERCATO] Primo ingresso. Acquisto immediato di {budget_buy_teorico:.2f} EUR...", flush=True)
        try:
            id_buy = f"mbuy_{uuid.uuid4().hex[:8]}"
            client.create_order(
                client_order_id=id_buy,
                product_id=pair,
                side="BUY",
                order_configuration={"market_market_ioc": {"quote_size": f"{budget_buy_teorico:.2f}"}}
            )
            motivo_reset += " (Starter Buy Eseguito)"
            ordine_inviato_con_successo = True
            time.sleep(1.5)  # Attesa allineamento saldi API Coinbase
            saldo_eur_totale, dict_cripto_totale = controlla_saldi_globali()
            crypto_posseduta = dict_cripto_totale.get(symbol_crypto, 0.0)
            valore_crypto_eur = crypto_posseduta * prezzo_rif
        except Exception as e:
            print(f"❌ Errore Starter Buy a Mercato su {pair}: {e}", flush=True)

    # 3. CALCOLO LIVELLI GRIGLIA
    prezzo_buy_grid = prezzo_rif * (1.0 - grid_dist_buy)
    prezzo_sell = prezzo_rif * (1.0 + grid_dist_sell)
    quantita_token_buy = budget_buy_teorico / prezzo_buy_grid

    # A. PIAZZAMENTO ORDINE BUY (LIMIT)
    if autorizza_buy and saldo_eur_totale >= min_order_eur and not ordine_inviato_con_successo:
        try:
            id_buy = f"lbuy_{uuid.uuid4().hex[:8]}"
            client.create_order(
                client_order_id=id_buy, product_id=pair, side="BUY",
                order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_token_buy:.{dec}f}", "limit_price": f"{prezzo_buy_grid:.2f}", "post_only": False}}
            )
            ordine_inviato_con_successo = True
        except Exception as e:
            print(f"⚠️ Errore ordine BUY limite ({pair}): {e}", flush=True)

    # B. PIAZZAMENTO ORDINE SELL (LIMIT - Adattivo per superare la soglia di 5.00 EUR)
    if valore_crypto_eur >= (min_order_eur * 0.90):  # Se il controvalore sfiora o supera i 5€
        quantita_sell_teorica = (budget_totale_asset * 0.20) / prezzo_sell
        valore_sell_teorico = quantita_sell_teorica * prezzo_sell

        # Se il 20% teorico vale meno di 5 EUR (es. posizione piccola sotto i 10€), 
        # mettiamo in vendita il 100% dei token posseduti per superare il minimo d'ordine di Coinbase
        if valore_sell_teorico < min_order_eur:
            quantita_sell = crypto_posseduta
        else:
            quantita_sell = min(quantita_sell_teorica, crypto_posseduta)

        valore_sell_effettivo = quantita_sell * prezzo_sell

        if valore_sell_effettivo >= min_order_eur:
            try:
                id_sell = f"lsell_{uuid.uuid4().hex[:8]}"
                client.create_order(
                    client_order_id=id_sell, product_id=pair, side="SELL",
                    order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_sell:.{dec}f}", "limit_price": f"{prezzo_sell:.2f}", "post_only": False}}
                )
                print(f"✅ Ordine SELL limite piazzato per {pair}: {quantita_sell:.{dec}f} {symbol_crypto} a {prezzo_sell:.2f} EUR", flush=True)
                ordine_inviato_con_successo = True
            except Exception as e:
                print(f"⚠️ Errore ordine SELL limite ({pair}): {e}", flush=True)

    # 4. REGISTRAZIONE DIARIO & TELEGRAM (Solo a conferma dell'invio API reale)
    if ordine_inviato_con_successo:
        msg_telegram = f"🔄 *COINBASE: UPDATE GRIGLIA {pair}* {emoji}\n" \
                       f"Evento: _{motivo_reset}_\n" \
                       f"Prezzo Pivot: *{prezzo_rif:.2f} EUR*\n" \
                       f"Target SELL (+{grid_dist_sell*100:.1f}%): *{prezzo_sell:.2f} EUR*\n" \
                       f"Target BUY (-{grid_dist_buy*100:.1f}%): *{prezzo_buy_grid:.2f} EUR*\n" \
                       f"Pool EUR Totale: *{saldo_eur_totale:.2f} EUR*"
        invia_telegram(msg_telegram)

        registra_su_diario_di_bordo(
            pair=pair, prezzo_pivot=prezzo_rif, ema50=ema50, saldo_eur=saldo_eur_totale, 
            crypto_posseduta=crypto_posseduta, motivo=motivo_reset, trend_ok=autorizza_buy,
            rsi=rsi, vol_ratio=volume_ratio, target_buy=prezzo_buy_grid, target_sell=prezzo_sell,
            grid_buy_pct=grid_dist_buy, grid_sell_pct=grid_dist_sell
        )
        return True

    return False

def rimuovi_asset_dismesso_da_config(pair_da_rimuovere):
    """Elimina la coin a saldo 0 da config.json ed esegue il commit automatico su GitHub."""
    try:
        if os.path.exists(FILE_CONFIG):
            with open(FILE_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            
            if pair_da_rimuovere in cfg.get("assets", {}):
                del cfg["assets"][pair_da_rimuovere]
                
                with open(FILE_CONFIG, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2)
                
                subprocess.run(["git", "config", "user.name", "Trading-Bot-AutoClean"], check=True)
                subprocess.run(["git", "config", "user.email", "bot@local.cleaner"], check=True)
                subprocess.run(["git", "add", FILE_CONFIG], check=True)
                
                result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
                if result.stdout.strip():
                    subprocess.run(["git", "commit", "-m", f"🧹 [AUTO-CLEAN] Rimosso {pair_da_rimuovere} a saldo zero"], check=True)
                    subprocess.run(["git", "push"], check=True)
                    print(f"✅ [AUTO-CLEAN] {pair_da_rimuovere} rimosso da config.json su GitHub!", flush=True)
    except Exception as e:
        print(f"⚠️ Errore pulizia config.json: {e}", flush=True)

# ==========================================
# ESECUZIONE CICLO PRINCIPALE
# ==========================================
def esegui_gestione_asset(pair, valore_totale_portafoglio):
    cfg = CONFIG_ASSETS[pair]
    symbol_crypto = pair.split("-")[0]
    exit_strategy = cfg.get("exit_strategy", "none")
    is_active = cfg.get("is_active", True)

    prezzo_attuale, ema50, returns_24h, vol_24h, rsi, volume_ratio = ottieni_dati_mercato_avanzati(pair)
    if not prezzo_attuale or not ema50: return None, False

    saldo_eur_totale, dict_cripto_totale = controlla_saldi_globali()
    crypto_posseduta = dict_cripto_totale.get(symbol_crypto, 0.0)
    min_order_eur = cfg["min_order_eur"]

    if exit_strategy == "market_sell":
        print(f"🚨 [MARKET SELL] AI Auditor ha ordinato la vendita immediata per {pair}!", flush=True)
        cancella_ordini_pair(pair)
        
        if (crypto_posseduta * prezzo_attuale) >= min_order_eur:
            try:
                dec = cfg["decimals"]
                client.create_order(
                    client_order_id=f"msell_{uuid.uuid4().hex[:8]}",
                    product_id=pair,
                    side="SELL",
                    order_configuration={"market_market_ioc": {"base_size": f"{crypto_posseduta:.{dec}f}"}}
                )
                msg = f"🚨 *COINBASE: MARKET SELL ESEGUITO PER {pair}*\nPosizione liquidata su indicazione AI Auditor."
                invia_telegram(msg)
                registra_su_diario_di_bordo(
                    pair=pair, prezzo_pivot=prezzo_attuale, ema50=ema50, saldo_eur=saldo_eur_totale,
                    crypto_posseduta=0.0, motivo="LIQUIDATO IN MARKET SELL DA AI (Capitale Liberato)", trend_ok=False
                )
                rimuovi_asset_dismesso_da_config(pair)
            except Exception as e:
                print(f"⚠️ Errore esecuzione Market Sell per {pair}: {e}", flush=True)
                return prezzo_attuale, False
        else:
            print(f"ℹ️ [MARKET SELL COMPLETO] Saldo {pair} pari a 0. Rimuovo l'asset dal config...", flush=True)
            rimuovi_asset_dismesso_da_config(pair)
            carica_e_sincronizza_config()

        return prezzo_attuale, False

    if exit_strategy == "soft_exit" or not is_active:
        print(f"⏸️ [SOFT EXIT] Asset {pair} in modalità dismissione. Cancello ordini d'acquisto.", flush=True)
        cancella_ordini_pair(pair, cancella_solo_buy=True)
        return prezzo_attuale, False

    soglia_protezione = ema50 * SOGLIA_EMA_TOLLERANZA
    trend_ok = (prezzo_attuale >= soglia_protezione)
    
    id_buy, id_sell = recupera_ordini_pair(pair)
    ha_crypto_per_sell = (crypto_posseduta * prezzo_attuale) >= min_order_eur

    # STARTER BUY: Se è una nuova coin e il saldo è 0, autorizziamo l'acquisto
    # per permettere all'AI di posizionarsi subito sul mercato
    autorizza_buy_effettivo = trend_ok or (crypto_posseduta == 0)

    print(f"-> [DEBUG {pair}] Prezzo: {prezzo_attuale:.2f} | EMA50: {ema50:.2f} | RSI: {rsi:.1f} | BUY: {bool(id_buy)} | SELL: {bool(id_sell)}", flush=True)

    # A. Inizializzazione Totale
    if id_buy is None and id_sell is None:
        piazza_nuova_griglia(pair=pair, prezzo_rif=prezzo_attuale, autorizza_buy=autorizza_buy_effettivo, motivo_reset="Inizializzazione Nuova Coin Satellite (AI Auditor)", 
                             ema50=ema50, returns_24h=returns_24h, vol_24h=vol_24h, rsi=rsi, volume_ratio=volume_ratio,
                             valore_totale_portafoglio=valore_totale_portafoglio)
        return prezzo_attuale, not trend_ok

    if not trend_ok and id_buy is not None:
        piazza_nuova_griglia(pair=pair, prezzo_rif=prezzo_attuale, autorizza_buy=False, motivo_reset="Attivazione Circuit Breaker (Sotto 95% EMA50)", 
                             ema50=ema50, returns_24h=returns_24h, vol_24h=vol_24h, rsi=rsi, volume_ratio=volume_ratio,
                             valore_totale_portafoglio=valore_totale_portafoglio)
        return prezzo_attuale, True

    if id_buy is None and id_sell is not None:
        print(f"⚠️ [DEBUG {pair}] Manca ordine BUY. Ordine precedente eseguito, riallineamento griglia...", flush=True)
        piazza_nuova_griglia(pair=pair, prezzo_rif=prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="Ripristino Griglia per BUY Eseguito", 
                             ema50=ema50, returns_24h=returns_24h, vol_24h=vol_24h, rsi=rsi, volume_ratio=volume_ratio,
                             valore_totale_portafoglio=valore_totale_portafoglio)
        return prezzo_attuale, not trend_ok

    if id_buy is not None and id_sell is None:
        if ha_crypto_per_sell:
            print(f"⚠️ [DEBUG {pair}] Manca ordine SELL ma possediamo crypto. Riallineamento...", flush=True)
            piazza_nuova_griglia(pair=pair, prezzo_rif=prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="SELL Eseguito su Exchange (Saldo Riallineato)", 
                                 ema50=ema50, returns_24h=returns_24h, vol_24h=vol_24h, rsi=rsi, volume_ratio=volume_ratio,
                                 valore_totale_portafoglio=valore_totale_portafoglio)
        else:
            print(f"ℹ️ [DEBUG {pair}] Ordine BUY pendente in attesa di esecuzione.", flush=True)

    return prezzo_attuale, not trend_ok

def main():
    print("🚀 [DEBUG] Avvio Bot Multi-Asset...", flush=True)

    # Legge dinamicamente dal file config.json
    carica_e_sincronizza_config()

    saldo_eur_totale, dict_cripto_totale = controlla_saldi_globali()
    prezzi_attuali = {}
    stati_cb = {}

    valore_crypto_stimato = 0.0
    for pair in list(CONFIG_ASSETS.keys()):
        p, _, _, _, _, _ = ottieni_dati_mercato_avanzati(pair)
        if p:
            prezzi_attuali[pair] = p
            sym = pair.split("-")[0]
            valore_crypto_stimato += dict_cripto_totale.get(sym, 0.0) * p

    valore_totale_portafoglio = saldo_eur_totale + valore_crypto_stimato
    print(f"💰 Valore Totale Portafoglio Stimato: {valore_totale_portafoglio:.2f} EUR (EUR liquidi: {saldo_eur_totale:.2f} EUR)", flush=True)

    # Itera su tutti i pair attivi compresi quelli inseriti al volo dall'AI Auditor
    for pair in list(CONFIG_ASSETS.keys()):
        try:
            prezzo, cb_attivo = esegui_gestione_asset(pair, valore_totale_portafoglio)
            if prezzo:
                prezzi_attuali[pair] = prezzo
            stati_cb[pair] = cb_attivo
        except Exception as e:
            print(f"❌ Errore nella gestione di {pair}: {e}", flush=True)
    
    try:
        saldo_eur_totale, dict_cripto_totale = controlla_saldi_globali()
        traccia_portafoglio_giornaliero(prezzi_attuali, saldo_eur_totale, dict_cripto_totale, stati_cb)
    except Exception as e:
        print(f"⚠️ Errore tracciamento portafoglio: {e}", flush=True)

    print("✅ Ciclo completato in pochi secondi!", flush=True)

if __name__ == "__main__":
    main()
