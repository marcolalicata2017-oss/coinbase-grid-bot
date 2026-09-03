import os
import json
import time
import subprocess
import pandas as pd
import requests
from datetime import datetime, timedelta
from google import genai

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

FILE_DIARIO = "diario_di_bordo.csv"
FILE_PORTAFOGLIO = "storico_portafoglio_giornaliero.csv"
FILE_CONFIG = "config.json"
FILE_MEMORIA = "memoria_decisioni_ai.json"

def invia_telegram(messaggio):
    """Invia un messaggio a Telegram gestendo automaticamente i fallimenti di parsing Markdown."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Token o Chat ID Telegram non configurati.", flush=True)
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload_markdown = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": messaggio, 
        "parse_mode": "Markdown"
    }
    
    try:
        resp = requests.post(url, json=payload_markdown, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ Errore Telegram API ({resp.status_code}): {resp.text}", flush=True)
            print("🔄 Riprovo in formato TESTO SEMPLICE...", flush=True)
            payload_plain = {"chat_id": TELEGRAM_CHAT_ID, "text": messaggio}
            resp_retry = requests.post(url, json=payload_plain, timeout=10)
            if resp_retry.status_code == 200:
                print("✅ Notifica inviata in testo semplice!", flush=True)
        else:
            print("✅ Notifica Telegram inviata con successo!", flush=True)
    except Exception as e:
        print(f"❌ Errore invio Telegram: {e}", flush=True)

def ottieni_altcoin_eur_disponibili_coinbase():
    """Recupera dinamicamente l'elenco di tutti i pair SPOT EUR attivi su Coinbase."""
    try:
        url = "https://api.exchange.coinbase.com/products"
        headers = {"User-Agent": "Python-Bot"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            prodotti = resp.json()
            coppie_eur_valide = []
            esclusi = ["USDC-EUR", "EURC-EUR", "USDT-EUR", "BTC-EUR", "ETH-EUR"]
            for p in prodotti:
                id_pair = p.get("id", "")
                quote = p.get("quote_currency", "")
                status = p.get("status", "")
                disabled = p.get("trading_disabled", False)
                if quote == "EUR" and status == "online" and not disabled:
                    if id_pair not in esclusi:
                        coppie_eur_valide.append(id_pair)
            coppie_eur_valide.sort()
            return coppie_eur_valide
    except Exception as e:
        print(f"⚠️ Errore recupero pair dinamici da Coinbase: {e}", flush=True)
    return ["LINK-EUR", "ADA-EUR", "NEAR-EUR", "DOT-EUR", "AVAX-EUR", "XRP-EUR", "ATOM-EUR", "ALGO-EUR"]

def carica_memoria_storica():
    if os.path.exists(FILE_MEMORIA):
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                contenuto = f.read().strip()
                if contenuto: return json.loads(contenuto)
        except Exception as e:
            print(f"⚠️ Errore lettura memoria storica: {e}", flush=True)
    return []

def salva_memoria_storica(memoria):
    try:
        with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
            json.dump(memoria, f, indent=2, ensure_ascii=False)
        print("🧠 Memoria decisionale salvata su file.", flush=True)
    except Exception as e:
        print(f"⚠️ Errore salvataggio memoria storica: {e}", flush=True)

def applica_commit_github(nuovo_config, nuova_scheda_memoria=None):
    try:
        with open(FILE_CONFIG, "w", encoding="utf-8") as f:
            json.dump(nuovo_config, f, indent=2)
        
        if nuova_scheda_memoria:
            memoria = carica_memoria_storica()
            memoria.append(nuova_scheda_memoria)
            salva_memoria_storica(memoria)

        subprocess.run(["git", "config", "user.name", "AI-Auditor-Bot"], check=True)
        subprocess.run(["git", "config", "user.email", "ai-auditor@bot.local"], check=True)
        subprocess.run(["git", "add", FILE_CONFIG], check=True)
        if os.path.exists(FILE_MEMORIA):
            subprocess.run(["git", "add", FILE_MEMORIA], check=True)

        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if result.stdout.strip():
            subprocess.run(["git", "commit", "-m", "🤖 AI Auditor: Calibrazione dinamica liquidità, Core & Satellite"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("✅ config.json e memoria_decisioni_ai.json committati su GitHub!", flush=True)
            return True
        else:
            print("ℹ️ Nessuna modifica sostanziale da committare.", flush=True)
            return False
    except Exception as e:
        print(f"❌ Errore auto-commit su GitHub: {e}", flush=True)
        return False

def esegui_audit():
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY non configurata!", flush=True)
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    df_diario = pd.read_csv(FILE_DIARIO, on_bad_lines='skip') if os.path.exists(FILE_DIARIO) else pd.DataFrame()
    df_portafoglio = pd.read_csv(FILE_PORTAFOGLIO) if os.path.exists(FILE_PORTAFOGLIO) else pd.DataFrame()
    memoria_storica = carica_memoria_storica()
    altcoin_disponibili = ottieni_altcoin_eur_disponibili_coinbase()

    config_attuale = {}
    if os.path.exists(FILE_CONFIG):
        try:
            with open(FILE_CONFIG, "r", encoding="utf-8") as f:
                config_attuale = json.load(f)
        except Exception as e:
            print(f"⚠️ Errore lettura config.json: {e}", flush=True)

    ora_dt = datetime.now()
    is_domenica = (ora_dt.weekday() == 6)

    data_limite = (ora_dt - timedelta(days=7 if is_domenica else 1)).strftime("%Y-%m-%d")
    diario_rec = df_diario[df_diario['Data_Ora'] >= data_limite] if not df_diario.empty and 'Data_Ora' in df_diario.columns else pd.DataFrame()

    # =========================================================
    # DIAGNOSI LIQUIDITÀ & STATO REALE DEL PORTAFOGLIO
    # =========================================================
    saldo_eur_effettivo = 0.0
    valore_crypto_totale = 0.0
    valore_totale_portafoglio = 1.0
    pct_cassa_eur = 100.0

    if not df_portafoglio.empty:
        ultima_riga = df_portafoglio.iloc[-1]
        saldo_eur_effettivo = float(ultima_riga.get("Saldo_EUR", 0.0))
        valore_crypto_totale = float(ultima_riga.get("Valore_Crypto_EUR", 0.0))
        valore_totale_portafoglio = float(ultima_riga.get("Valore_Totale_EUR", saldo_eur_effettivo + valore_crypto_totale))
        if valore_totale_portafoglio > 0:
            pct_cassa_eur = (saldo_eur_effettivo / valore_totale_portafoglio) * 100.0

    stato_liquidita_alert = "NORMALE"
    if pct_cassa_eur < 15.0 or saldo_eur_effettivo < 35.0:
        stato_liquidita_alert = "ALLERTA CRITICA LIQUIDITÀ (RISCHIO BLOCCO ORDINI BUY)"

    prompt = f"""
    Sei un Quantitative Crypto Portfolio Manager e Risk Officer di massimo livello su Coinbase Advanced.

    Data Corrente: {ora_dt.strftime('%Y-%m-%d')}
    Modalità Audit: {"SETTIMANALE STRATEGICO (Ribilanciamento Macro Pesi + Tuning Completo)" if is_domenica else "GIORNALIERO TATTICO DUAL-SPEED (Tuning Completo Core & Satellite)"}

    ⚡ FEE COINBASE ADVANCED (INTRO 2): Maker 0.35%, Taker 0.75%, Ordine Minimo 5.00 EUR.
    🎯 NET SPREAD RULE: 'grid_dist_sell' NON deve mai scendere sotto 0.020 (2.0%).

    💰 STATO ATTUALE LIQUIDITÀ & ASSET ALLOCATION:
    - Valore Portafoglio Totale: {valore_totale_portafoglio:.2f} EUR
    - Cassa EUR Libera/Disponibile: {saldo_eur_effettivo:.2f} EUR ({pct_cassa_eur:.1f}% del portafoglio)
    - Valore Totale Crypto in carico: {valore_crypto_totale:.2f} EUR
    - Stato Riserva di Cassa: {stato_liquidita_alert}

    🚨 PROTOCOLLO LIQUIDITY CRUNCH & REBALANCING CON VINCOLO DI NON-PERDITA (NO-LOSS RULE):
    Se la Cassa EUR scende sotto il 15-20% (o sotto 40 EUR), c'è rischio di esaurire la liquidità per piazzare i BUY sulle altre monete.
    Devi intervenire seguendo TASSATIVAMENTE questa gerarchia di regole:
    1. Identifica l'asset maggiormente sovraesposto rispetto al suo 'target_weight_pct' (es. ETH con peso reale > 50% a fronte di un target del 35%).
    2. VALUTAZIONE PROFITTO / CARICO (REGOLA D'ORO: NON REALIZZARE MAI PERDITE):
       - Esamina i prezzi dal diario di bordo o dal mercato recente:
         * SE L'ASSET SOVRAESPOSTO È IN PROFITTO (prezzo attuale superiore ai prezzi medi di carico):
           -> Riduci 'buy_conviction' a 0.5 (o 0.0) per congelare le uscite di cassa.
           -> Imposta 'sell_action': 'scale_out' (per vendere il 50% dell'accumulo al target di profitto) oppure 'liquidate_all' se siamo su spike/ipercomprato, così da monetizzare il guadagno e ricostituire la liquidità EUR.
         * SE L'ASSET SOVRAESPOSTO È IN DRAWDOWN / IN PERDITA RISPETTO AL CARICO:
           -> NON DEVI MAI VENDERE IN PERDITA! Non impostare 'scale_out' né 'liquidate_all' svendendo in perdita.
           -> Mantieni 'sell_action': 'tranche' e azzera/riduci drasticamente 'buy_conviction' a 0.5 (o 0.0) per bloccare ulteriori compere sull'asset in perdita, attendendo che risalga sopra la parità prima di alleggerire.
    3. Quando la cassa EUR torna capiente (>25%) e l'asset torna vicino al peso target, ripristina la normale operatività ('sell_action': 'tranche' e 'buy_conviction': 1.0).

    CONFIGURAZIONE ATTUALE BOT (config.json):
    {json.dumps(config_attuale, indent=2) if config_attuale else "Nessun config.json trovato."}

    MEMORIA STORICA ULTIME DECISIONI:
    {json.dumps(memoria_storica[-5:], indent=2) if memoria_storica else "Nessuna memoria registrata."}

    DATI RECENTI DIARIO DI BORDO (Saldi Reali EUR e Crypto in pancia):
    {diario_rec.to_string() if not diario_rec.empty else "Nessuna operazione registrata."}

    ALTCOIN SPOT EUR DISPONIBILI SU COINBASE (Per Satellite):
    {json.dumps(altcoin_disponibili)}

    🚀 POTERI DECISIONALI DINAMICI DUAL-SPEED:
    1. PARAMETRI TATTICI (AGGIORNABILI OGNI GIORNO SU CORE E SATELLITE):
       - "buy_conviction": 0.5x (bassa/difensiva), 1.0x (neutra), 1.5x-2.0x (alta convinzione su supporti).
       - "sell_action": "tranche" (Modo B standard), "scale_out" (monetizza il 50% solo se in utile), "liquidate_all" (monetizza il 100% solo se in utile).
       - "grid_dist_buy" (tra 0.008 e 0.050) e "grid_dist_sell" (>= 0.020).
    2. PARAMETRI STRATEGICI ("target_weight_pct"):
       - Giorni feriali: Pesi Core congelati; ruota solo il Satellite (max 10%).
       - Domenica: Ribilanciamento libero di tutti i target weight (somma attiva = 100.0).

    STRUTTURA DI RISPOSTA OBBLIGATORIA:
    Separa rigorosamente le 3 parti con i delimitatori '---JSON_CONFIG---' e '---JSON_MEMORIA---':

    Parte 1: Report sintetico per Telegram (Markdown) contenente:
    - 💧 Analisi Liquidità e Riserva EUR ({pct_cassa_eur:.1f}% cassa)
    - ⚖️ Bilanciamento Portafoglio & Valutazione P&L dell'asset sovraesposto (Conferma di NON vendita in perdita)
    - 🎯 Decisioni Tattiche (Conviction, Sell Action per ogni pair)
    ---JSON_CONFIG---
    Parte 2: Il JSON completo valido per config.json (o 'NO_CHANGE').
    ---JSON_MEMORIA---
    Parte 3: Oggetto JSON per la scheda di memoria (data, tipo_audit, decisione, motivazione, lezione_appresa) o 'NO_CHANGE'.
    """

    modelli = ['gemini-3.5-flash', 'gemini-3.6-flash']
    testo_risposta = None

    for modello in modelli:
        for tentativo in range(3):
            try:
                print(f"🔄 Chiamata con modello {modello} (tentativo {tentativo + 1})...", flush=True)
                response = client.models.generate_content(model=modello, contents=prompt)
                testo_risposta = response.text
                break
            except Exception as e:
                print(f"⚠️ Errore con {modello}: {e}", flush=True)
                time.sleep(3)
        if testo_risposta:
            break

    if not testo_risposta:
        print("❌ Impossibile completare l'audit.", flush=True)
        return

    parti_config = testo_risposta.split("---JSON_CONFIG---")
    report_telegram = parti_config[0].strip()
    
    resto = parti_config[1].strip() if len(parti_config) > 1 else "NO_CHANGE"
    parti_memoria = resto.split("---JSON_MEMORIA---")
    
    json_config_str = parti_memoria[0].strip()
    json_memoria_str = parti_memoria[1].strip() if len(parti_memoria) > 1 else "NO_CHANGE"

    modificato = False
    if json_config_str != "NO_CHANGE":
        try:
            if json_config_str.startswith("```"):
                json_config_str = json_config_str.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            nuovo_config = json.loads(json_config_str)
            
            nuova_scheda = None
            if json_memoria_str != "NO_CHANGE":
                if json_memoria_str.startswith("```"):
                    json_memoria_str = json_memoria_str.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                nuova_scheda = json.loads(json_memoria_str)

            modificato = applica_commit_github(nuovo_config, nuova_scheda)
        except Exception as e:
            print(f"⚠️ Errore parsing JSON da Gemini: {e}", flush=True)

    intestazione = "🧠 *[AI AUDITOR - MACRO AUDIT SETTIMANALE]*\n\n" if is_domenica else "⚡ *[AI AUDITOR - DAILY TACTICAL RUN]*\n\n"
    if modificato:
        report_telegram += "\n\n🚀 *[AUTO-TUNING & GESTIONE LIQUIDITÀ APPLICATI]*: Parametri aggiornati su GitHub."

    invia_telegram(intestazione + report_telegram)
    print("✅ Audit Dual-Speed completato con successo!", flush=True)

if __name__ == "__main__":
    esegui_audit()
