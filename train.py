# train.py
import requests
import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier

def scarica_storico_coinbase(pair="BTC-EUR"):
    """Scarica le candele orarie storiche da Coinbase."""
    url = f"https://api.exchange.coinbase.com/products/{pair}/candles?granularity=3600"
    headers = {"User-Agent": "Python-Bot"}
    resp = requests.get(url, headers=headers, timeout=10)
    data = resp.json()
    
    df = pd.DataFrame(data, columns=['time', 'low', 'high', 'open', 'close', 'volume'])
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.sort_values('time').reset_index(drop=True)
    return df

def calcola_features_e_target(df):
    """Calcola indicatori tecnici come Feature per l'ML."""
    # 1. Feature: Ritorno percentuale
    df['returns'] = df['close'].pct_change()
    
    # 2. Feature: Volatilità a 24 ore
    df['volatility_24h'] = df['returns'].rolling(24).std()
    
    # 3. Feature: Distanza dalla EMA50
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['dist_ema50'] = (df['close'] - df['ema50']) / df['ema50']
    
    # 4. TARGET: Il mercato farà alta volatilità nelle prossime 6 ore? (1 = Sì, 0 = No)
    futura_volatilita = df['returns'].shift(-6).rolling(6).std()
    soglia_alta_vol = df['volatility_24h'].quantile(0.70)
    df['target_alta_volatilita'] = (futura_volatilita > soglia_alta_vol).astype(int)
    
    df = df.dropna()
    return df

def addestra_modello():
    print("🧠 [ML TRAIN] Download dati storici in corso...")
    df = scarica_storico_coinbase("BTC-EUR")
    df = calcola_features_e_target(df)
    
    X = df[['returns', 'volatility_24h', 'dist_ema50']]
    y = df['target_alta_volatilita']
    
    # Addestramento Random Forest
    model = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=42)
    model.fit(X, y)
    
    # Salva il modello su disco
    joblib.dump(model, "modello_volatilta.pkl")
    print("✅ [ML TRAIN] Modello addestrato e salvato in 'modello_volatilta.pkl'")

if __name__ == "__main__":
    addestra_modello()
