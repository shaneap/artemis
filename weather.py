"""Daily weather and holiday context for Artemis (Ronkonkoma, NY).

Kept separate from `artemis.py` so the core pipeline stays free of network dependencies --
the analysis must run offline, and it does: the first call caches to disk and every call
after that reads the cache.

Source is Open-Meteo's historical archive: free, no API key, no attribution requirement.

    import weather
    wx = weather.load_weather('2026-01-15', '2026-07-15')
    nightly = weather.add_weather(nightly)      # joins on Service_Date
    nightly = weather.add_holidays(nightly)
"""

import json
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

# Ronkonkoma, NY.
LATITUDE = 40.8151
LONGITUDE = -73.1279
TIMEZONE = 'America/New_York'

CACHE_PATH = Path(__file__).with_name('weather_cache.csv')
ARCHIVE_URL = 'https://archive-api.open-meteo.com/v1/archive'

DAILY_FIELDS = [
    'temperature_2m_max',
    'temperature_2m_min',
    'precipitation_sum',
    'wind_speed_10m_max',
]

RENAME = {
    'temperature_2m_max': 'Temp_High_F',
    'temperature_2m_min': 'Temp_Low_F',
    'precipitation_sum': 'Precip_In',
    'wind_speed_10m_max': 'Wind_Max_Mph',
}

# Days a bar actually feels, which is not the federal holiday list. Valentine's and Mother's
# Day move more covers than Presidents' Day does. Dates are for the export window; extend as
# the data range grows.
US_HOLIDAYS = {
    '2026-02-14': "Valentine's Day",
    '2026-02-16': "Presidents' Day",
    '2026-03-17': "St Patrick's Day",
    '2026-04-05': 'Easter Sunday',
    '2026-05-10': "Mother's Day",
    '2026-05-25': 'Memorial Day',
    '2026-06-21': "Father's Day",
    '2026-07-04': 'Independence Day',
}


def _ssl_context():
    """An SSL context that can actually verify certificates on this machine.

    Python installs on macOS ship without a CA bundle and do not read the system keychain,
    so a plain urlopen fails with CERTIFICATE_VERIFY_FAILED. Prefer certifi when it exists;
    otherwise export the system roots, which is what the keychain holds anyway.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass

    try:
        pem = subprocess.run(
            ['security', 'find-certificate', '-a', '-p',
             '/System/Library/Keychains/SystemRootCertificates.keychain'],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        raise RuntimeError(
            'Cannot verify HTTPS certificates: no certifi module and the macOS system root '
            'certificates could not be read. Fix with either:\n'
            '  pip install certifi\n'
            '  or run "/Applications/Python 3.x/Install Certificates.command"'
        ) from exc

    if 'BEGIN CERTIFICATE' not in pem:
        raise RuntimeError('System keychain returned no certificates; run `pip install certifi`.')
    return ssl.create_default_context(cadata=pem)


def fetch_daily_weather(start, end, latitude=LATITUDE, longitude=LONGITUDE):
    """Fetch daily weather for a date range from Open-Meteo. Returns a dataframe."""
    query = (
        f'{ARCHIVE_URL}?latitude={latitude}&longitude={longitude}'
        f'&start_date={start}&end_date={end}'
        f'&daily={",".join(DAILY_FIELDS)}'
        f'&temperature_unit=fahrenheit&precipitation_unit=inch&timezone={TIMEZONE.replace("/", "%2F")}'
    )
    try:
        with urllib.request.urlopen(query, context=_ssl_context(), timeout=60) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Could not reach the Open-Meteo archive: {exc.reason}') from exc

    daily = pd.DataFrame(payload['daily']).rename(columns=RENAME)
    daily['Service_Date'] = pd.to_datetime(daily.pop('time'))
    return daily[['Service_Date'] + list(RENAME.values())]


def load_weather(start, end, refresh=False):
    """Weather for a date range, served from the local cache and only fetching what's missing.

    The cache means the notebook runs offline after the first execution, and that repeated
    runs can't drift because of an upstream revision.
    """
    wanted = pd.date_range(start, end, freq='D')

    cached = pd.DataFrame()
    if CACHE_PATH.exists() and not refresh:
        cached = pd.read_csv(CACHE_PATH, parse_dates=['Service_Date'])

    have = set(cached['Service_Date']) if len(cached) else set()
    missing = [d for d in wanted if d not in have]

    if missing:
        fetched = fetch_daily_weather(min(missing).date().isoformat(),
                                      max(missing).date().isoformat())
        cached = (pd.concat([cached, fetched], ignore_index=True)
                    .drop_duplicates(subset='Service_Date')
                    .sort_values('Service_Date'))
        cached.to_csv(CACHE_PATH, index=False)
        print(f'Fetched {len(fetched)} day(s) from Open-Meteo; cache now holds {len(cached)}.')
    else:
        print(f'Weather served entirely from cache ({len(cached)} days, no network call).')

    return cached[cached['Service_Date'].isin(wanted)].reset_index(drop=True)


def add_weather(nightly, refresh=False):
    """Join daily weather onto a frame that has a `Service_Date` column."""
    start = nightly['Service_Date'].min().date().isoformat()
    end = nightly['Service_Date'].max().date().isoformat()
    wx = load_weather(start, end, refresh=refresh)
    merged = nightly.merge(wx, on='Service_Date', how='left')

    unmatched = merged['Temp_High_F'].isna().sum()
    if unmatched:
        print(f'WARNING: {unmatched} night(s) have no weather data.')
    return merged


def add_holidays(nightly):
    """Label nights that fall on a holiday a bar would actually notice."""
    holidays = {pd.Timestamp(d): name for d, name in US_HOLIDAYS.items()}
    nightly = nightly.copy()
    nightly['Holiday'] = nightly['Service_Date'].map(holidays)
    nightly['Is_Holiday'] = nightly['Holiday'].notna()
    return nightly
