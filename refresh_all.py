#!/usr/bin/env python3
import requests
import hashlib
import uuid
import time
import json

APP_ID = "100003"
APP_KEY = "38d2391985e2369a5fb8227d8e6cd5e5"
BASE_URL = "https://autoglm-api.autoglm.ai"


def generate_sign(timestamp):
    raw = f"{APP_ID}&{timestamp}&{APP_KEY}"
    return hashlib.md5(raw.encode()).hexdigest()


def get_headers():
    ts = str(int(time.time()))
    return {
        "content-type": "application/json",
        "x-auth-appid": APP_ID,
        "x-auth-timestamp": ts,
        "x-auth-sign": generate_sign(ts),
        "x-product": "autoclaw",
        "x-version": "1.9.1",
        "x-tm": "win",
        "x-trace-id": str(uuid.uuid4()),
    }


def refresh_token(device_id, refresh_tok):
    url = f"{BASE_URL}/userapi/v1/refresh"
    body = {
        "source_id": "web",
        "device_id": device_id,
        "refresh_token": refresh_tok.replace("Bearer ", ""),
    }
    resp = requests.post(url, json=body, headers=get_headers(), timeout=15)
    data = resp.json()
    if data.get("code") == 0:
        return data["data"]["access_token"], data["data"]["refresh_token"]
    return None, None


with open("autoclaw_accounts.json", "r") as f:
    accounts = json.load(f)

print(f"Refreshing {len(accounts)} tokens...")
ok, fail = 0, 0

for i, acc in enumerate(accounts):
    new_access, new_refresh = refresh_token(acc["device_id"], acc["refresh_token"])
    if new_access:
        acc["access_token"] = new_access
        acc["refresh_token"] = new_refresh
        ok += 1
        print(f"  [{i + 1}/{len(accounts)}] {acc['email']} ✓")
    else:
        fail += 1
        print(f"  [{i + 1}/{len(accounts)}] {acc['email']} ✗")

with open("autoclaw_accounts.json", "w") as f:
    json.dump(accounts, f, indent=2, ensure_ascii=False)

print(f"\nDone: {ok} ok, {fail} failed")
