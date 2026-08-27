import os
import pandas as pd

FILE_DIARIO = "diario_di_bordo.csv"

if os.path.exists(FILE_DIARIO):
    df = pd.read_csv(FILE_DIARIO)
    righe_prima = len(df)
    
    # 1. Parsing cronologico
    if "Data_Ora" in df.columns:
        df["Data_Ora"] = pd.to_datetime(df["Data_Ora"], errors="coerce")
        df = df.sort_values(by=["Pair", "Data_Ora"]).reset_index(drop=True)
    
    # 2. Rileva i record consecutivi per Pair in cui né la crypto né l'EUR sono cambiati
    maschera_saldo_invariato = (
        (df["Crypto_Posseduta"] == df.groupby("Pair")["Crypto_Posseduta"].shift(1)) &
        (df["Saldo_EUR_Pool"] == df.groupby("Pair")["Saldo_EUR_Pool"].shift(1))
    )
    
    # 3. Mantiene solo i cambi di stato reali (trade e inizializzazioni)
    df_pulito = df[~maschera_saldo_invariato].copy()
    
    # 4. Ripristina l'ordine cronologico globale
    if "Data_Ora" in df_pulito.columns:
        df_pulito = df_pulito.sort_values(by="Data_Ora").reset_index(drop=True)
        df_pulito["Data_Ora"] = df_pulito["Data_Ora"].dt.strftime("%Y-%m-%d %H:%M:%S")
    
    df_pulito.to_csv(FILE_DIARIO, index=False)
    rimosse = righe_prima - len(df_pulito)
    print(f"✅ Pulizia completata: rimosse {rimosse} righe a saldo invariato. Righe reali conservate: {len(df_pulito)}")
else:
    print(f"⚠️ File {FILE_DIARIO} non trovato.")
