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
            esclusi = ["USDC-EUR", "EURC-EUR", "USDT-EUR"]
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
    return ["BTC-EUR", "ETH-EUR", "SOL-EUR", "LINK-EUR", "ADA-EUR", "NEAR-EUR", "AVAX-EUR", "DOT-EUR"]

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
            subprocess.run(["git", "commit", "-m", "🤖 AI Auditor: Ribilanciamento dinamico a Bande Flessibili"], check=True)
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

    # Diagnosi Liquidità e Valore Totale
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
        stato_liquidita_alert = "ALLERTA CRITICA LIQUIDITÀ (RISCHIO BLOCCO GRIGLIE BUY)"

    prompt = f"""
    Sei il Direttore Investimenti e Risk Manager Quantitativo di un Hedge Fund Crypto su Coinbase Advanced.
    Il tuo compito è gestire un portafoglio a BANDE FLESSIBILI SENZA DISTINZIONE FISSA CORE/SATELLITE.

    Data Corrente: {ora_dt.strftime('%Y-%m-%d')}
    Tipo Esecuzione: {"SETTIMANALE STRATEGICO (Ribilanciamento Macro Pesi & Memoria)" if is_domenica else "GIORNALIERO TATTICO (Riallocazione Pesi, Sizing & Ribilanciamento Liquidità)"}

    ⚡ COMMISSIONI COINBASE ADVANCED (INTRO 2): Maker 0.35%, Taker 0.75%, Ordine Minimo 5.00 EUR.
    🎯 NET SPREAD RULE: 'grid_dist_sell' NON deve mai scendere sotto 0.020 (2.0%).

    💰 STATO REALE PORTAFOGLIO & LIQUIDITÀ:
    - Valore Totale Portafoglio: {valore_totale_portafoglio:.2f} EUR
    - Cassa EUR Libera: {saldo_eur_effettivo:.2f} EUR ({pct_cassa_eur:.1f}% del portafoglio)
    - Controvalore Totale Crypto in Carico: {valore_crypto_totale:.2f} EUR
    - Stato Riserva Cassa: {stato_liquidita_alert}

    CONFIGURAZIONE ATTUALE (config.json):
    {json.dumps(config_attuale, indent=2) if config_attuale else "Nessun config.json trovato."}

    MEMORIA STORICA ULTIME DECISIONI & LEZIONI APPRESE:
    {json.dumps(memoria_storica[-5:], indent=2) if memoria_storica else "Nessuna memoria registrata."}

    DATI RECENTI DIARIO DI BORDO (Prezzi medi di carico, acquisti e vendite eseguite):
    {diario_rec.to_string() if not diario_rec.empty else "Nessuna operazione registrata nel periodo."}

    PAIR SPOT EUR SCAMBIABILI SU COINBASE:
    {json.dumps(altcoin_disponibili)}

    🏛️ REGOLE DEL MODELLO A BANDE FLESSIBILI (FULL DYNAMIC ALLOCATION):
    1. Libertà di Allocazione ("target_weight_pct"):
       - La somma totale dei "target_weight_pct" per tutti gli asset attivi deve fare SEMPRE 100.0.
       - BTC-EUR ed ETH-EUR sono gli asset cardine: ciascuno deve avere un peso compreso tra 20.0% e 60.0% (possono scendere quando sono in ipercomprato per monetizzare, ma non possono essere azzerati).
       - Qualsiasi altra altcoin (es. SOL, LINK, ecc.): peso flessibile tra 0.0% e 25.0% ciascuna.
       - Puoi decidere di dismettere una moneta impostando "target_weight_pct": 0.0 ed "exit_strategy": "soft_exit".

    2. GESTIONE DELLA LIQUIDITÀ & SOVRAESPOSIZIONE (CASH DRAIN PROTOCOL):
       - Se la Cassa EUR è < 15% (o < 40 EUR), oppure un asset pesa molto più del suo target (es. ETH al 60% invece del 35%):
         * REGOLA DI FERRO: NON VENDERE MAI IN PERDITA!
         * Se l'asset sovraesposto è IN PROFITTO rispetto al prezzo di carico:
           - Riduci 'buy_conviction' a 0.5 per congelare acquisti.
           - Imposta 'sell_action': 'scale_out' (per vendere il 50% dell'accumulo sul target di presa profitto) o 'liquidate_all' se ha raggiunto massimi storici/ipercomprato, trasformandolo in cassa EUR da reinvestire.
         * Se l'asset sovraesposto è IN PERDITA (drawdown):
           - NON liquidare l'accumulo. Lascia 'sell_action': 'tranche' e riduci 'buy_conviction' a 0.5 per non spendere altri soldi, attendendo il recupero.

    3. PARAMETRI OPERATIVI PER OGNI ASSET IN 'assets':
       - "target_weight_pct": Peso percentuale nel portafoglio.
       - "buy_conviction": Moltiplicatore di size d'acquisto (0.5x prudente, 1.0x standard, 1.5x-2.0x aggressivo su supporto/ipervenduto).
       - "sell_action": "tranche" (Modo B standard), "scale_out" (monetizza 50% solo se in utile), "liquidate_all" (monetizza 100% solo se in utile).
       - "grid_dist_buy": Tra 0.008 e 0.050.
       - "grid_dist_sell": Minimo 0.020 (>= 2.0%).

    STRUTTURA DELLA RISPOSTA (OBBLIGATORIA):
    Separa le 3 parti con '---JSON_CONFIG---' e '---JSON_MEMORIA---':

    Parte 1: Report narrativo per Telegram (Markdown) con:
    - 💧 Quadro Liquidità e Riserva EUR ({pct_cassa_eur:.1f}% cassa)
    - ⚖️ Ribilanciamento Pesi e Strategia di Scale-Out/Rotazione (Verifica No-Loss)
    - 🎯 Matrice Operativa per ogni Pair (Conviction, Sell Action, Spread)
    ---JSON_CONFIG---
    Parte 2: Il JSON completo valido per config.json (o 'NO_CHANGE').
    ---JSON_MEMORIA---
    Parte 3: Scheda di memoria JSON (data, tipo_audit, decisione, motivazione, lezione_appresa) o 'NO_CHANGE'.
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

    intestazione = "🧠 *[AI AUDITOR - SETTIMANALE BANDE FLESSIBILI]*\n\n" if is_domenica else "⚡ *[AI AUDITOR - DAILY REBALANCING & SIZING]*\n\n"
    if modificato:
        report_telegram += "\n\n🚀 *[RIBILANCIAMENTO APPLICATO]*: config.json aggiornato su GitHub."

    invia_telegram(intestazione + report_telegram)
    print("✅ Audit completato con successo!", flush=True)

if __name__ == "__main__":
    esegui_audit()
