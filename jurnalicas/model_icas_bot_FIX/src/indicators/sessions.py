"""
ICT Session & Killzone Detection for Model Icas (Asian Range, London Open Burst, NY Open Burst)

[F-18] REPAIN FIX (audit backtest M1, 02 Sep 2026)
--------------------------------------------------------------------------
Versi lama menghitung asian_high/low dan london_high/low dengan
    df[mask].groupby('date').agg(max/min)  ->  pd.merge(df, stats, on='date')
yang menempelkan agregat SEPANJANG HARI ke SETIAP bar pada tanggal itu.
Akibatnya bar pukul 00:00 sudah "mengetahui" high Asia pukul 06:55 dan
high London pukul 11:55. Itu lookahead/repaint: level BSL/SSL yang menjadi
dasar seluruh sinyal berasal dari data masa depan.

Terbukti di research/test_antirepaint.py (T6) dan diukur dampaknya di
reports/m1_audit_compare_jan_jun_2026.txt:
    config A, Jan-Jun 2026, risk 1%
      level sesi bersih  : PF 0.93, net -$2.100
      level sesi bocor   : PF 1.36, net +$6.935      (selisih +$9.035 fiktif)

Aturan sekarang (kausal, sama dengan engine teraudit):
    Asian  03:00-06:59 server  -> baru dipublikasikan mulai 07:00
    London 08:00-11:59 server  -> baru dipublikasikan mulai 12:00
    Sebelum jam itu dipakai range hari SEBELUMNYA yang sudah lengkap.
    Bila jendela data tidak memuat sesi lengkap sama sekali, fallback ke
    high/low bar itu sendiri (degeneratif tapi tetap tanpa lookahead).
"""
import pandas as pd
import numpy as np

ASIAN_OPEN_H, ASIAN_CLOSE_H = 3, 7        # waktu server
LONDON_OPEN_H, LONDON_CLOSE_H = 8, 12


def calculate_session_killzones(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes Asian High/Low, London High/Low, and ICT Open Burst flags.
    Expected datetime in 'time' column (waktu SERVER, bukan UTC).

    [F-18] Semua level sesi bersifat point-in-time: nilai pada bar i hanya
    bergantung pada bar <= i.
    """
    df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df['time']):
        df['time'] = pd.to_datetime(df['time'])

    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    df['minute'] = df['time'].dt.minute

    hi = df['high'].to_numpy(dtype=float)
    lo = df['low'].to_numpy(dtype=float)
    hour = df['hour'].to_numpy()
    date = df['date'].to_numpy()
    n = len(df)

    a_hi = np.empty(n); a_lo = np.empty(n)
    l_hi = np.empty(n); l_lo = np.empty(n)

    cur = None
    run_ah = run_al = run_lh = run_ll = np.nan      # sesi hari ini, sedang berjalan
    day_ah = day_al = day_lh = day_ll = np.nan      # sesi hari ini, SUDAH tutup
    prev_ah = prev_al = prev_lh = prev_ll = np.nan  # sesi hari sebelumnya

    for i in range(n):
        if date[i] != cur:
            prev_ah, prev_al = day_ah, day_al
            prev_lh, prev_ll = day_lh, day_ll
            cur = date[i]
            run_ah = run_al = run_lh = run_ll = np.nan
        h = hour[i]

        if ASIAN_OPEN_H <= h < ASIAN_CLOSE_H:
            run_ah = hi[i] if np.isnan(run_ah) else max(run_ah, hi[i])
            run_al = lo[i] if np.isnan(run_al) else min(run_al, lo[i])
        elif h == ASIAN_CLOSE_H:
            day_ah, day_al = run_ah, run_al

        if LONDON_OPEN_H <= h < LONDON_CLOSE_H:
            run_lh = hi[i] if np.isnan(run_lh) else max(run_lh, hi[i])
            run_ll = lo[i] if np.isnan(run_ll) else min(run_ll, lo[i])
        elif h == LONDON_CLOSE_H:
            day_lh, day_ll = run_lh, run_ll

        if h >= ASIAN_CLOSE_H and not np.isnan(day_ah):
            a_hi[i], a_lo[i] = day_ah, day_al
        elif not np.isnan(prev_ah):
            a_hi[i], a_lo[i] = prev_ah, prev_al
        else:
            a_hi[i], a_lo[i] = hi[i], lo[i]        # fallback degeneratif, tetap kausal

        if h >= LONDON_CLOSE_H and not np.isnan(day_lh):
            l_hi[i], l_lo[i] = day_lh, day_ll
        elif not np.isnan(prev_lh):
            l_hi[i], l_lo[i] = prev_lh, prev_ll
        else:
            l_hi[i], l_lo[i] = a_hi[i], a_lo[i]

    df['asian_high'] = a_hi
    df['asian_low'] = a_lo
    df['london_high'] = l_hi
    df['london_low'] = l_lo

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
    is_ny = ((hour_server == 15 and min_server >= 30) or
             hour_server == 16 or (hour_server == 17 and min_server <= 30))
    return is_london or is_ny
