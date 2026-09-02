"""
ICT Session & Killzone Detection for Model Icas (Asian Range, London Open Burst, NY Open Burst)
"""
import pandas as pd
import numpy as np

def calculate_session_killzones(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes Asian High/Low, London High/Low, and ICT Open Burst flags.
    Expected datetime in 'time' column.
    """
    df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df['time']):
        df['time'] = pd.to_datetime(df['time'])
        
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    df['minute'] = df['time'].dt.minute

    # Asian Range (07:00 - 11:00 WIB = 03:00 - 07:00 MT5 Server)
    asian_mask = (df['hour'] >= 3) & (df['hour'] < 7)
    asian_stats = df[asian_mask].groupby('date').agg(
        asian_high=('high', 'max'),
        asian_low=('low', 'min')
    ).reset_index()
    df = pd.merge(df, asian_stats, on='date', how='left')
    df['asian_high'] = df['asian_high'].ffill().fillna(df['high'])
    df['asian_low'] = df['asian_low'].ffill().fillna(df['low'])

    # London Session (12:00 - 15:30 WIB = 08:00 - 11:30 MT5 Server)
    london_mask = (df['hour'] >= 8) & (df['hour'] < 12)
    london_stats = df[london_mask].groupby('date').agg(
        london_high=('high', 'max'),
        london_low=('low', 'min')
    ).reset_index()
    df = pd.merge(df, london_stats, on='date', how='left')
    df['london_high'] = df['london_high'].ffill().fillna(df['asian_high'])
    df['london_low'] = df['london_low'].ffill().fillna(df['asian_low'])

    # ICT Burst Windows:
    # London Open Burst : 14:00 - 16:00 WIB (10:00 - 12:00 Server)
    # New York Open Burst: 19:30 - 21:30 WIB (15:30 - 17:30 Server)
    h = df['hour'].values
    m = df['minute'].values
    is_london_burst = (h >= 10) & (h < 12)
    is_ny_burst = ((h == 15) & (m >= 30)) | (h == 16) | ((h == 17) & (m <= 30))
    df['in_ict_burst'] = is_london_burst | is_ny_burst

    return df

def is_current_in_burst(hour_server: int, min_server: int) -> bool:
    """Check if current server timestamp falls inside an active ICT burst."""
    is_london = (10 <= hour_server < 12)
    is_ny = ((hour_server == 15 and min_server >= 30) or (hour_server == 16) or (hour_server == 17 and min_server <= 30))
    return is_london or is_ny
