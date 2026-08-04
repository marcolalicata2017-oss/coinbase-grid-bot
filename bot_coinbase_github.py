import os
import time
import uuid
import json
import requests
import joblib
import numpy as np
import pandas as pd
from datetime import datetime
from coinbase.rest import RESTClient

# ==========================================
# CONFIGURAZIONE GENERALE & CARICAMENTO CONFIG.JSON
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COINBASE_KEY_NAME = os.getenv("COINBASE_KEY_NAME")
COINBASE_KEY_SECRET = os.getenv("COINBASE_KEY_SECRET")

FILE_CONFIG = "config.json"
FILE_DIARIO = "diario_di_bordo.csv"
FILE_PORTAFOGLIO_GIORNALIERO = "storico_portafoglio_giornaliero.csv"
FILE_MODELLO_ML = "modello_volatilta.pkl"

# Configurazione fallback di base
CONFIG_ASSETS = {
    "ETH-EUR": {
        "grid_dist": 0.012,
        "emoji": "🔷",
        "min_order_eur": 5.0,
        "decimals": 4,
        "target_weight_pct": 45.0,
        "type": "core",
        "is_active": True,
        "exit_strategy": "none"
    },
    "BTC-EUR": {
        "grid_dist": 0.010,
        "emoji": "🪙",
        "min_order_eur": 5.0,
        "decimals": 8,
        "target_weight_pct": 45.0,
        "type": "core",
        "is_active": True,
        "exit_strategy": "none"
    },
    "SOL-EUR": {
        "grid_dist": 0.018,
        "emoji": "🟣",
        "min_order_eur": 5.0,
        "decimals": 2,
        "target_weight_pct": 10.0,
        "type": "satellite",
        "is_active": True,
        "exit_strategy": "none"
    }
}

EMOJI_MAP = {
    "BTC": "🪙", "ETH": "🔷", "SOL": "🟣", "AVAX": "🔴", 
    "LINK": "🔗", "ADA": "🔵", "NEAR": "🟢", "SUI": "💧", "DOT": "🔴"
}

def carica_e_sincronizza_config():
    """Carica il file config.json aggiornato dall'AI Auditor ed allinea CONFIG_ASSETS."""
    global CONFIG_ASSETS
    if os.path.exists(FILE_CONFIG):
        try:
            with open(FILE_CONFIG, "r", encoding="utf-8") as f:
                cfg_json = json.load(f)
            
            assets_json = cfg_json.get("assets", {})
            nuovo_config = {}
            
            for pair, data in assets_json.items():
                sym = pair.split("-")[0]
                emoji = EMOJI_MAP.get(sym, "🪙")
                decimals = 8 if sym == "BTC" else (4 if sym in ["ETH", "SOL"] else 2)
                
                nuovo_config[pair] = {
                    "grid_dist": data.get("grid_dist_buy", 0.015),
                    "grid_dist_sell": data.get("grid_dist_sell", 0.015),
                    "emoji": emoji,
                    "min_order_eur": 5.0,
                    "decimals": decimals,
                    "target_weight_pct": data.get("target_weight_pct", 0.0),
                    "type": data.get("type", "core"),
                    "is_active": data.get("is_active", True),
                    "exit_strategy": data.get("exit_strategy", "none")
                }
            if nuovo_config:
                CONFIG_ASSETS = nuovo_config
                print("✅ [CONFIG] Configurazione sincronizzata con successo da config.json", flush=True)
        except Exception as e:
            print(f"⚠️ [CONFIG] Errore caricamento config.json: {e}", flush=True)

# Sincronizzazione iniziale
carica_e_sincronizza_config()

SOGLIA_EMA_TOLLERANZA = 0.95
client = RESTClient(api_key=COINBASE_KEY_NAME, api_secret=COINBASE_KEY_SECRET, timeout=10)
ULTIMO_STATO_CB = {}

# Caricamento Modello ML al boot
MODELLO_ML = None
if os.path.exists(FILE_MODELLO_ML):
    try:
        MODELLO_ML = joblib.load(FILE_MODELLO_ML)
        print("🤖 [ML INFERENCE] Modello di volatilità caricato con successo!", flush=True)
    except Exception as e:
        print(f"⚠️ [ML INFERENCE] Errore caricamento modello: {e}", flush=True)
else:
    print("ℹ️ [ML INFERENCE] File modello non trovato. Operatività con parametri standard.", flush=True)

# ==========================================
# UTILITIES TELEGRAM & DIARIO DI BORDO AVANZATO
# ==========================================
def invia_telegram(messaggio):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": messaggio, "parse_mode": "Markdown"}
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print(f"⚠️ [DEBUG] Errore invio Telegram: {e}", flush=True)

def registra_su_diario_di_bordo(pair, prezzo_pivot, ema50, saldo_eur, crypto_posseduta, motivo, trend_ok,
                                rsi=50.0, vol_ratio=1.0, target_buy=0.0, target_sell=0.0, 
                                grid_buy_pct=0.0, grid_sell_pct=0.0):
    ora_corrente = time.strftime("%Y-%m-%d %H:%M:%S")
    file_esistente = os.path.exists(FILE_DIARIO)
    
    # Normalizzazione diciture per non trarre in inganno Gemini
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
        print(f"⚠️ Errore scrittura diario di bordo ({pair}): {e}", flush=True)

# ==========================================
# TRACCIAMENTO ED ELABORAZIONE REPORT SETTIMANALE VISIVO
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
        print(f"📊 [CSV] Registrazione valore portafoglio per il giorno {oggi}...", flush=True)
        intestazione = "Data,Saldo_EUR,Valore_Crypto_EUR,Valore_Totale_EUR\n"
        riga = f"{oggi},{saldo_eur_totale:.2f},{valore_cripto_totale:.2f},{valore_totale:.2f}\n"
        
        try:
            with open(FILE_PORTAFOGLIO_GIORNALIERO, "a", encoding="utf-8") as f:
                if not file_esiste:
                    f.write(intestazione)
                f.write(riga)
        except Exception as e:
            print(f"Errore registrazione CSV portafoglio: {e}", flush=True)

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
        valore_iniziale_esperimento = valore_totale
        
        try:
            if os.path.exists(FILE_PORTAFOGLIO_GIORNALIERO):
                df = pd.read_csv(FILE_PORTAFOGLIO_GIORNALIERO)
                if not df.empty:
                    valore_iniziale_esperimento = float(df.iloc[0]["Valore_Totale_EUR"])
                    if len(df) >= 7:
                        valore_7_gg_fa = float(df.iloc[-7]["Valore_Totale_EUR"])
                    else:
                        valore_7_gg_fa = valore_iniziale_esperimento
        except Exception as e:
            print(f"Avviso lettura storico per delta: {e}", flush=True)

        diff_sett = valore_totale - valore_7_gg_fa
        pct_sett = ((diff_sett) / valore_7_gg_fa * 100) if valore_7_gg_fa > 0 else 0.0
        emoji_sett = "🟢" if diff_sett >= 0 else "🔴"
        segno_sett = "+" if diff_sett >= 0 else ""

        diff_overall = valore_totale - valore_iniziale_esperimento
        pct_overall = ((diff_overall) / valore_iniziale_esperimento * 100) if valore_iniziale_esperimento > 0 else 0.0
        emoji_overall = "🟢" if diff_overall >= 0 else "🔴"
        segno_overall = "+" if diff_overall >= 0 else ""

        pct_eur = (saldo_eur_totale / valore_totale) if valore_totale > 0 else 1.0
        barra_eur = genera_barra_progresso(pct_eur)

        msg_report = f"📊 *REPORT SETTIMANALE PORTAFOGLIO*\n" \
                     f"📅 Domenica {ora_dt.strftime('%d/%m/%Y')}\n\n" \
                     f"💰 Valore Totale: *{valore_totale:.2f} EUR*\n" \
                     f"📈 Rispetto a Dom. Scorsa: *{segno_sett}{pct_sett:.2f}%* ({emoji_sett} {segno_sett}{diff_sett:.2f} EUR)\n" \
                     f"🚀 Crescita Overall: *{segno_overall}{pct_overall:.2f}%* ({emoji_overall} {segno_overall}{diff_overall:.2f} EUR)\n\n" \
                     f"📊 *Composizione Portafoglio (Inclusi Ordini Pendenti):*\n" \
                     f"`[{barra_eur}]` {pct_eur*100:.0f}% Saldo EUR ({saldo_eur_totale:.2f} EUR)\n"

        for pair, cfg in CONFIG_ASSETS.items():
            sym = pair.split("-")[0]
            val, qta = dettagli_cripto_val.get(sym, (0.0, 0.0))
            pct_asset = (val / valore_totale) if valore_totale > 0 else 0.0
            barra_asset = genera_barra_progresso(pct_asset)
            msg_report += f"`[{barra_asset}]` {pct_asset*100:.0f}% {cfg['emoji']} {sym} ({val:.2f} EUR | {qta:.{cfg['decimals']}f} {sym})\n"

        msg_report += "\n🛡️ *Stato Circuit Breaker (Soglia 95% EMA50):*\n"
        for pair, cb_attivo in stati_cb.items():
            emoji_asset = CONFIG_ASSETS.get(pair, {}).get("emoji", "🪙")
            stato_txt = "ATTIVO 🔴" if cb_attivo else "DISATTIVATO 🟢"
            msg_report += f"{emoji_asset} {pair}: *{stato_txt}*\n"

        invia_telegram(msg_report)

        try:
            with open(file_flag_domenica, "w", encoding="utf-8") as f:
                f.write(oggi)
        except: pass

# ==========================================
# CHIAMATE API COINBASE & FEATURE ENGINEERING
# ==========================================
def ottieni_dati_mercato_avanzati(product_id):
    url = f"https://api.exchange.coinbase.com/products/{product_id}/candles?granularity=3600"
    headers = {"User-Agent": "Python-Bot"}
    for tentativo in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if len(data) >= 50:
                    candele = list(reversed(data))
                    prezzi_chiusura = [float(c[4]) for c in candele]
                    volumi = [float(c[5]) for c in candele]

                    s_prezzi = pd.Series(prezzi_chiusura)
                    s_volumi = pd.Series(volumi)

                    prezzo_attuale = prezzi_chiusura[-1]
                    ema50 = s_prezzi.ewm(span=50, adjust=False).mean().iloc[-1]

                    delta = s_prezzi.diff()
                    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                    rs = gain / loss
                    rsi_series = 100 - (100 / (1 + rs))
                    rsi_attuale = rsi_series.iloc[-1] if not pd.isna(rsi_series.iloc[-1]) else 50.0

                    vol_ora_attuale = s_volumi.iloc[-1]
                    vol_medio_24h = s_volumi.tail(24).mean()
                    volume_ratio = (vol_ora_attuale / vol_medio_24h) if vol_medio_24h > 0 else 1.0

                    returns = s_prezzi.pct_change()
                    returns_ultimo = returns.iloc[-1] if not pd.isna(returns.iloc[-1]) else 0.0
                    vol_24h = returns.tail(24).std() if len(returns) >= 24 else 0.0
                    vol_24h = 0.0 if pd.isna(vol_24h) else vol_24h

                    return prezzo_attuale, ema50, returns_ultimo, vol_24h, rsi_attuale, volume_ratio
        except Exception as e:
            print(f"⚠️ Errore API candele ({product_id}): {e}", flush=True)
        time.sleep(1)
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
                    try:
                        return float(obj)
                    except:
                        return 0.0

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
            
    return 0.0, cripto_dict_totale

def recupera_ordini_pair(product_id):
    id_buy, id_sell = None, None
    for tentativo in range(3):
        try:
            res = client.list_orders(product_id=product_id, order_status=["OPEN"])
            ordini = res.get('orders', []) if isinstance(res, dict) else getattr(res, 'orders', [])
            
            for o in ordini:
                side = o.get('side') if isinstance(o, dict) else getattr(o, 'side', None)
                o_id = o.get('order_id') if isinstance(o, dict) else getattr(o, 'order_id', None)
                
                if side == "BUY":
                    id_buy = o_id
                elif side == "SELL":
                    id_sell = o_id
                    
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
            tipo_txt = "BUY " if cancella_solo_buy else ""
            print(f"-> [DEBUG] Cancellati ordini {tipo_txt}aperti per {product_id}", flush=True)
    except Exception as e:
        print(f"⚠️ Errore cancellazione ordini {product_id}: {e}", flush=True)

# ==========================================
# LOGICA DI PIAZZAMENTO GRIGLIA & GESTIONE IN CORSA
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

    # 1. DISCESA / BUY: ML Volatility Grid Spacing
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
            print(f"⚠️ Errore inferenza ML su {pair}: {e}", flush=True)

    # 2. SALITA / SELL: DYNAMIC PROFIT TAKING
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

    prezzo_buy_grid = prezzo_rif * (1.0 - grid_dist_buy)
    prezzo_sell = prezzo_rif * (1.0 + grid_dist_sell)

    # 3. BUDGET DINAMICO IN CORSA SUI SALDI REALI
    budget_totale_asset = (valore_totale_portafoglio * target_weight_pct) / 100.0 if valore_totale_portafoglio > 0 else saldo_eur_totale
    scarto_ema = (prezzo_rif - ema50) / ema50 if ema50 > 0 else 0.0
    
    # Frazione per singolo ordine della griglia
    pct_frazione_order = 0.20  # 20% del budget destinato all'asset per singolo ordine
    pct_budget_sell = pct_frazione_order

    if scarto_ema > 0.04:
        pct_budget_sell = pct_frazione_order * 1.6
        label_martingala = " (SELL Martingala Salita +60%)"
    elif scarto_ema > 0.02:
        pct_budget_sell = pct_frazione_order * 1.3
        label_martingala = " (SELL Martingala Salita +30%)"
    else:
        label_martingala = ""

    budget_buy_teorico = max(budget_totale_asset * pct_frazione_order, min_order_eur)
    motivo_reset += label_martingala

    cancella_ordini_pair(pair)

    valore_crypto_eur = crypto_posseduta * prezzo_rif
    ha_crypto_sufficiente = valore_crypto_eur >= (min_order_eur * 1.05)
    is_starter_buy = False
    piazza_buy = autorizza_buy

    if not autorizza_buy and not ha_crypto_sufficiente:
        print(f"💡 [{pair} STARTER BUY] Prezzo < 95% EMA50 e 0 {symbol_crypto}: Acquisto immediato!", flush=True)
        piazza_buy = True
        is_starter_buy = True
        prezzo_compra_effettivo = prezzo_rif
        motivo_reset += " (Acquisto Starter Immediato)"
    else:
        prezzo_compra_effettivo = prezzo_buy_grid

    quantita_token_buy = budget_buy_teorico / prezzo_compra_effettivo

    if saldo_eur_totale < min_order_eur:
        piazza_buy = False

    for tentativo in range(3):
        try:
            if piazza_buy:
                id_buy = f"lbuy_{uuid.uuid4().hex[:8]}"
                client.create_order(
                    client_order_id=id_buy, product_id=pair, side="BUY",
                    order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_token_buy:.{dec}f}", "limit_price": f"{prezzo_compra_effettivo:.2f}", "post_only": False}}
                )

            if ha_crypto_sufficiente:
                id_sell = f"lsell_{uuid.uuid4().hex[:8]}"
                quantita_sell_teorica = (budget_totale_asset * pct_budget_sell) / prezzo_sell
                quantita_sell = min(quantita_sell_teorica, crypto_posseduta)
                
                if (quantita_sell * prezzo_sell) >= min_order_eur:
                    client.create_order(
                        client_order_id=id_sell, product_id=pair, side="SELL",
                        order_configuration={"limit_limit_gtc": {"base_size": f"{quantita_sell:.{dec}f}", "limit_price": f"{prezzo_sell:.2f}", "post_only": False}}
                    )

            stato_cb_attuale = "ATTIVO" if not autorizza_buy else "DISATTIVATO"
            stato_precedente = ULTIMO_STATO_CB.get(pair)

            if stato_precedente != stato_cb_attuale or "Esecuzione" in motivo_reset or is_starter_buy or "Dynamic" in motivo_reset:
                msg_telegram = f"🔄 *COINBASE: UPDATE GRIGLIA {pair}* {emoji}\n" \
                               f"Evento: _{motivo_reset}_\n" \
                               f"Prezzo Pivot: *{prezzo_rif:.2f} EUR*\n" \
                               f"Target SELL (+{grid_dist_sell*100:.1f}%): *{prezzo_sell:.2f} EUR*\n" \
                               f"Target BUY (-{grid_dist_buy*100:.1f}%): *{prezzo_buy_grid:.2f} EUR*\n" \
                               f"RSI: *{rsi:.1f}* | Volume Ratio: *{volume_ratio:.2f}x*\n" \
                               f"Pool EUR Totale: *{saldo_eur_totale:.2f} EUR*"

                if not autorizza_buy:
                    msg_telegram += f"\n🛡️ *CIRCUIT BREAKER ATTIVO* (Prezzo < 95% EMA50: {ema50*0.95:.2f} EUR)."
                    if is_starter_buy:
                        msg_telegram += f"\n🛒 _Ordine d'acquisto immediato inviato a {prezzo_rif:.2f} EUR per non rimanere a 0 token._"

                invia_telegram(msg_telegram)
                ULTIMO_STATO_CB[pair] = stato_cb_attuale

            # Registrazione completa sul Diario di Bordo per AI Auditor
            registra_su_diario_di_bordo(
                pair=pair, prezzo_pivot=prezzo_rif, ema50=ema50, saldo_eur=saldo_eur_totale, 
                crypto_posseduta=crypto_posseduta, motivo=motivo_reset, trend_ok=autorizza_buy,
                rsi=rsi, vol_ratio=volume_ratio, target_buy=prezzo_buy_grid, target_sell=prezzo_sell,
                grid_buy_pct=grid_dist_buy, grid_sell_pct=grid_dist_sell
            )
            return True
        except Exception as e:
            print(f"⚠️ Errore piazzamento griglia ({pair}): {e}", flush=True)
            time.sleep(2)
    return False
def rimuovi_asset_dismesso_da_config(pair_da_rimuovere):
    """Rimuove l'asset dismesso dal config.json ed esegue il commit automatico su GitHub."""
    try:
        if os.path.exists(FILE_CONFIG):
            with open(FILE_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            
            if pair_da_rimuovere in cfg.get("assets", {}):
                del cfg["assets"][pair_da_rimuovere]
                
                with open(FILE_CONFIG, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2)
                
                # Commit e push automatico delle modifiche su GitHub
                subprocess.run(["git", "config", "user.name", "Trading-Bot-AutoClean"], check=True)
                subprocess.run(["git", "config", "user.email", "bot@local.cleaner"], check=True)
                subprocess.run(["git", "add", FILE_CONFIG], check=True)
                
                result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
                if result.stdout.strip():
                    subprocess.run(["git", "commit", "-m", f"🧹 [AUTO-CLEAN] Rimosso {pair_da_rimuovere} a saldo zero"], check=True)
                    subprocess.run(["git", "push"], check=True)
                    print(f"✅ [AUTO-CLEAN] {pair_da_rimuovere} rimosso da config.json su GitHub!", flush=True)
    except Exception as e:
        print(f"⚠️ Errore durante la pulizia automatica di config.json: {e}", flush=True)
# ==========================================
# ESECUZIONE DEL CICLO SINGLE/MULTI-ASSET
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

    # 1. GESTIONE MARKET SELL (Liquidazione Immediata Disposta da AI Auditor)
    if exit_strategy == "market_sell":
        print(f"🚨 [MARKET SELL] AI Auditor ha ordinato la vendita immediata per {pair}!", flush=True)
        cancella_ordini_pair(pair)
        
        # Se possediamo ancora crypto sopra il minimo d'ordine, vendiamo a mercato
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
                # Pulisce subito l'asset dal config dopo la vendita
                rimuovi_asset_dismesso_da_config(pair)
            except Exception as e:
                print(f"⚠️ Errore esecuzione Market Sell per {pair}: {e}", flush=True)
        else:
            # Se la crypto è già a 0, rimuove la voce da config.json e fa il push
            print(f"ℹ️ [MARKET SELL COMPLETO] Saldo {pair} pari a 0. Rimuovo l'asset dal config...", flush=True)
            rimuovi_asset_dismesso_da_config(pair)

        return prezzo_attuale, False

    # 2. GESTIONE SOFT EXIT O ASSET INATTIVO (Annulla ordini BUY, mantieni SELL)
    if exit_strategy == "soft_exit" or not is_active:
        print(f"⏸️ [SOFT EXIT] Asset {pair} in modalità dismissione. Cancello ordini d'acquisto.", flush=True)
        cancella_ordini_pair(pair, cancella_solo_buy=True)
        return prezzo_attuale, False

    # OPERATIVITÀ STANDARD A GRIGLIA
    soglia_protezione = ema50 * SOGLIA_EMA_TOLLERANZA
    trend_ok = (prezzo_attuale >= soglia_protezione)
    
    id_buy, id_sell = recupera_ordini_pair(pair)
    ha_crypto_per_sell = (crypto_posseduta * prezzo_attuale) >= min_order_eur

    print(f"-> [DEBUG {pair}] Prezzo: {prezzo_attuale:.2f} | EMA50: {ema50:.2f} | RSI: {rsi:.1f} | BUY: {bool(id_buy)} | SELL: {bool(id_sell)}", flush=True)

    # A. Inizializzazione Totale
    if id_buy is None and id_sell is None:
        piazza_nuova_griglia(pair=pair, prezzo_rif=prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="Inizializzazione Multi-Asset", 
                             ema50=ema50, returns_24h=returns_24h, vol_24h=vol_24h, rsi=rsi, volume_ratio=volume_ratio,
                             valore_totale_portafoglio=valore_totale_portafoglio)
        return prezzo_attuale, not trend_ok

    # B. Circuit Breaker Trigger
    if not trend_ok and id_buy is not None:
        piazza_nuova_griglia(pair=pair, prezzo_rif=prezzo_attuale, autorizza_buy=False, motivo_reset="Attivazione Circuit Breaker (Sotto 95% EMA50)", 
                             ema50=ema50, returns_24h=returns_24h, vol_24h=vol_24h, rsi=rsi, volume_ratio=volume_ratio,
                             valore_totale_portafoglio=valore_totale_portafoglio)
        return prezzo_attuale, True

    # C. Ripristino Griglia dopo esecuzione BUY
    if id_buy is None and id_sell is not None:
        print(f"⚠️ [DEBUG {pair}] Manca ordine BUY. Ordine precedente eseguito, riallineamento griglia...", flush=True)
        piazza_nuova_griglia(pair=pair, prezzo_rif=prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="Ripristino Griglia per BUY Eseguito", 
                             ema50=ema50, returns_24h=returns_24h, vol_24h=vol_24h, rsi=rsi, volume_ratio=volume_ratio,
                             valore_totale_portafoglio=valore_totale_portafoglio)
        return prezzo_attuale, not trend_ok

    # D. Riallineamento Ordine SELL
    if id_buy is not None and id_sell is None:
        if ha_crypto_per_sell:
            print(f"⚠️ [DEBUG {pair}] Manca ordine SELL ma possediamo crypto. Riallineamento...", flush=True)
            piazza_nuova_griglia(pair=pair, prezzo_rif=prezzo_attuale, autorizza_buy=trend_ok, motivo_reset="SELL Eseguito su Exchange (Saldo Riallineato)", 
                                 ema50=ema50, returns_24h=returns_24h, vol_24h=vol_24h, rsi=rsi, volume_ratio=volume_ratio,
                                 valore_totale_portafoglio=valore_totale_portafoglio)
        else:
            print(f"ℹ️ [DEBUG {pair}] Ordine BUY pendente in attesa di esecuzione. Nessuna azione richiesta.", flush=True)

    return prezzo_attuale, not trend_ok

def main():
    print("🚀 [DEBUG] Avvio Bot Multi-Asset (In corsa su saldi reali con Core-Satellite AI Integration)...", flush=True)

    # Ricarica configurazione prima dell'esecuzione del ciclo
    carica_e_sincronizza_config()

    saldo_eur_totale, dict_cripto_totale = controlla_saldi_globali()
    prezzi_attuali = {}
    stati_cb = {}

    # Calcolo valore totale iniziale del portafoglio in EUR
    valore_crypto_stimato = 0.0
    for pair in CONFIG_ASSETS.keys():
        p, _, _, _, _, _ = ottieni_dati_mercato_avanzati(pair)
        if p:
            prezzi_attuali[pair] = p
            sym = pair.split("-")[0]
            valore_crypto_stimato += dict_cripto_totale.get(sym, 0.0) * p

    valore_totale_portafoglio = saldo_eur_totale + valore_crypto_stimato
    print(f"💰 Valore Totale Portafoglio Stimato: {valore_totale_portafoglio:.2f} EUR (EUR liquidi: {saldo_eur_totale:.2f} EUR)", flush=True)

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
