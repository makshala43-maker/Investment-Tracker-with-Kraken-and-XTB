import os
import time
import base64
import hashlib
import hmac
import urllib.parse
import requests
import json
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

INFLUX_URL = "http://monitor_db:8086"
INFLUX_TOKEN = "my-super-secret-auth-token"
INFLUX_ORG = "my_org"
INFLUX_BUCKET = "portfolio"

KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET")
MANUAL_ASSETS_FILE = "manual_assets.json"

def get_kraken_signature(urlpath, data, secret):
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data['nonce']) + postdata).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    sigdigest = base64.b64encode(mac.digest())
    return sigdigest.decode()

def run_monitor():
    ticker_url = "https://api.kraken.com/0/public/Ticker"
    balance_url = "https://api.kraken.com/0/private/Balance"
    
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)

    while True:
        print("\n--- Starting Update Cycle ---")
        
        nonce = str(int(1000 * time.time()))
        headers = {
            "API-Key": KRAKEN_API_KEY,
            "API-Sign": get_kraken_signature('/0/private/Balance', {"nonce": nonce}, KRAKEN_API_SECRET)
        }

        try:
            res = requests.post(balance_url, headers=headers, data={"nonce": nonce}).json()
            if not res.get("error"):
                balances = res["result"]
                for asset, amount_raw in balances.items():
                    amount = float(amount_raw)
                    if amount <= 0.00001: 
                        continue
                    
                    if asset in ["ZUSD", "USD", "USDG"]:
                        val_usd = amount
                    else:
                        pair = f"{asset}USD"
                        if asset == "XXBT": 
                            pair = "XXBTZUSD"
                        elif asset == "XETH": 
                            pair = "XETHZUSD"
                        elif asset == "ZEUR": 
                            pair = "EURUSD"
                        elif asset == "XXDG": 
                            pair = "XDGUSD"
                        
                        p_res = requests.get(ticker_url, params={"pair": pair}).json()
                        
                        if p_res.get("error"): 
                            print(f"[WARNING] Kraken price rejected for {asset} (pair {pair}). Error: {p_res['error']}")
                            continue
                        
                        price = float(list(p_res["result"].values())[0]["c"][0])
                        val_usd = amount * price

                    point = Point("balance").tag("asset", asset).field("value_usd", val_usd)
                    write_api.write(bucket=INFLUX_BUCKET, record=point)
                    print(f"[SUCCESS] Kraken: {asset} = ${val_usd:.2f}")
        except Exception as e:
            print(f"[ERROR] Kraken phase: {e}")

        if os.path.exists(MANUAL_ASSETS_FILE) and os.path.isfile(MANUAL_ASSETS_FILE):
            try:
                with open(MANUAL_ASSETS_FILE, 'r') as f:
                    data = json.load(f)
                    for item in data.get("XTB_Stocks", []):
                        val = float(item['value_usd'])
                        point = Point("balance").tag("asset", item['name']).field("value_usd", val)
                        write_api.write(bucket=INFLUX_BUCKET, record=point)
                        print(f"[SUCCESS] Manual: {item['name']} = ${val:.2f}")
            except Exception as e:
                print(f"[ERROR] Manual phase: {e}")

        print("--- Cycle Completed. Sleeping 60s ---")
        time.sleep(60)

if __name__ == "__main__":
    run_monitor()