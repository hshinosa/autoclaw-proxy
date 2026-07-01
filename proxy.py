#!/usr/bin/env python3
"""
AutoClaw OpenAI-Compatible Proxy

Exposes AutoClaw LLM API as OpenAI-compatible endpoint with:
- Token rotation across multiple accounts
- Automatic token refresh
- Load balancing
- Health monitoring
"""

from flask import Flask, request, jsonify, Response, stream_with_context
import requests
import hashlib
import uuid
import time
import json
import random
import threading
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
APP_ID = "100003"
APP_KEY = "38d2391985e2369a5fb8227d8e6cd5e5"
BASE_URL = "https://autoglm-api.autoglm.ai"
PROXY_URL = f"{BASE_URL}/autoclaw-proxy/proxy/autoclaw"

ACCOUNTS_FILE = "autoclaw_accounts.json"
TOKEN_REFRESH_INTERVAL = 3600

DEFAULT_MODEL = "glm-5.2"
VALID_API_KEY = os.getenv("API_KEY")
ROUTING_STRATEGY = os.getenv("ROUTING_STRATEGY", "sticky")

MODEL_MAP = {
    "glm-5.2": "openrouter_glm-5.2",
    "glm-5-turbo": "zai_glm-5-turbo",
    "deepseek-v4-pro": "zai_auto",
    "deepseek-v4": "zai_auto",
    "auto": "zai_auto",
}

# Account pool with health tracking
accounts_pool = []
pool_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
def generate_sign(timestamp):
    raw = f"{APP_ID}&{timestamp}&{APP_KEY}"
    return hashlib.md5(raw.encode()).hexdigest()


def get_auth_headers():
    ts = str(int(time.time()))
    return {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://autoclaw.z.ai",
        "referer": "https://autoclaw.z.ai/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "x-auth-appid": APP_ID,
        "x-auth-timestamp": ts,
        "x-auth-sign": generate_sign(ts),
        "x-product": "autoclaw",
        "x-version": "1.9.1",  # Match docs version
        "x-tm": "win",  # Match docs
        "x-trace-id": str(uuid.uuid4()),
    }


def refresh_token(device_id, refresh_tok):
    """Refresh access token"""
    url = f"{BASE_URL}/userapi/v1/refresh"
    body = {
        "source_id": "web",
        "device_id": device_id,
        "refresh_token": refresh_tok.replace("Bearer ", ""),
    }
    try:
        resp = requests.post(url, json=body, headers=get_auth_headers(), timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            return data["data"]["access_token"], data["data"]["refresh_token"]
    except:
        pass
    return None, None


def load_accounts():
    """Load accounts from JSON file"""
    global accounts_pool
    try:
        with open(ACCOUNTS_FILE, "r") as f:
            raw_accounts = json.load(f)

        with pool_lock:
            accounts_pool = []
            for acc in raw_accounts:
                accounts_pool.append(
                    {
                        "email": acc["email"],
                        "device_id": acc["device_id"],
                        "access_token": acc["access_token"],
                        "refresh_token": acc["refresh_token"],
                        "balance": acc.get("balance", 0),
                        "healthy": True,
                        "last_used": 0,
                        "fail_count": 0,
                    }
                )

        print(f"[INFO] Loaded {len(accounts_pool)} accounts")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to load accounts: {e}")
        return False


def save_accounts():
    """Save accounts back to JSON file"""
    with pool_lock:
        raw_accounts = []
        for acc in accounts_pool:
            raw_accounts.append(
                {
                    "email": acc["email"],
                    "device_id": acc["device_id"],
                    "access_token": acc["access_token"],
                    "refresh_token": acc["refresh_token"],
                    "balance": acc["balance"],
                }
            )

    try:
        with open(ACCOUNTS_FILE, "w") as f:
            json.dump(raw_accounts, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] Failed to save accounts: {e}")


def get_next_account():
    """Get next healthy account (round-robin with health check)"""
    with pool_lock:
        # Filter healthy accounts
        healthy = [acc for acc in accounts_pool if acc["healthy"]]
        if not healthy:
            return None

        # Sort by last_used (least recently used first)
        healthy.sort(key=lambda x: x["last_used"])

        account = healthy[0]
        account["last_used"] = time.time()
        return account


def get_session_hash(session_id):
    """Consistent hash for session-based routing"""
    return int(hashlib.md5(session_id.encode()).hexdigest(), 16)


def get_account_for_session(session_id):
    """Get account for session (sticky routing)"""
    with pool_lock:
        healthy = [acc for acc in accounts_pool if acc["healthy"]]
        if not healthy:
            return None

        idx = get_session_hash(session_id) % len(healthy)
        account = healthy[idx]
        account["last_used"] = time.time()
        return account


def get_account_for_request(headers):
    """Smart account selection based on ROUTING_STRATEGY"""
    if ROUTING_STRATEGY == "sticky":
        session_id = headers.get("Authorization") or headers.get(
            "X-Session-ID", "default"
        )
        return get_account_for_session(session_id)
    else:
        return get_next_account()


def mark_account_failed(account):
    """Mark account as failed"""
    with pool_lock:
        account["fail_count"] += 1
        if account["fail_count"] >= 3:
            account["healthy"] = False
            print(
                f"[WARN] Account {account['email']} marked unhealthy (fail_count={account['fail_count']})"
            )


def mark_account_success(account):
    """Reset fail count on success"""
    with pool_lock:
        account["fail_count"] = 0


def refresh_account_token(account):
    """Refresh account token if needed"""
    new_access, new_refresh = refresh_token(
        account["device_id"], account["refresh_token"]
    )
    if new_access:
        with pool_lock:
            account["access_token"] = new_access
            account["refresh_token"] = new_refresh
            account["healthy"] = True
            account["fail_count"] = 0
        save_accounts()
        print(f"[INFO] Refreshed token for {account['email']}")
        return True
    return False


def mark_account_depleted(account):
    """Mark account as depleted (insufficient balance)"""
    with pool_lock:
        account["balance"] = 0
        account["healthy"] = False
        account["fail_count"] = 3
    save_accounts()
    print(f"[WARN] Account {account['email']} depleted (insufficient balance)")


def update_account_balance(account, usage_data):
    """Update account balance based on usage/cost from response"""
    if not usage_data:
        return

    cost = usage_data.get("cost", 0)
    if cost > 0:
        points_used = int(cost * 10000)
        with pool_lock:
            old_balance = account.get("balance", 0)
            account["balance"] = max(0, old_balance - points_used)

            if account["balance"] < 100:
                account["healthy"] = False
                print(
                    f"[WARN] Account {account['email']} low balance: {account['balance']}"
                )

        save_accounts()


def refresh_account_balance_from_api(account):
    """Query real balance from AutoClaw API"""
    try:
        url = f"{BASE_URL}/agent-assetmgr/api/v2/wallets"
        params = {"biz_app_id": "autoclaw"}
        headers = {
            "authorization": f"Bearer {account['access_token']}",
            "content-type": "application/json",
        }
        headers.update(get_auth_headers())

        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            total_balance = data.get("total_balance", 0)

            with pool_lock:
                account["balance"] = total_balance
                account["healthy"] = total_balance >= 100

            save_accounts()
            print(f"[INFO] Updated balance for {account['email']}: {total_balance}")
            return total_balance
    except Exception as e:
        print(f"[ERROR] Failed to refresh balance for {account['email']}: {e}")

    return None


def get_fallback_account(exclude_account):
    """Get next healthy account excluding specified account"""
    with pool_lock:
        healthy = [
            acc for acc in accounts_pool if acc["healthy"] and acc != exclude_account
        ]
        if not healthy:
            return None

        healthy.sort(key=lambda x: x["last_used"])
        account = healthy[0]
        account["last_used"] = time.time()
        return account

    return False


# ═══════════════════════════════════════════════════════════
# BACKGROUND TOKEN REFRESH
# ═══════════════════════════════════════════════════════════
def token_refresh_worker():
    while True:
        time.sleep(TOKEN_REFRESH_INTERVAL)
        print("[INFO] Refreshing all tokens...")

        with pool_lock:
            accounts_copy = accounts_pool.copy()

        refreshed = 0
        for account in accounts_copy:
            new_access, new_refresh = refresh_token(
                account["device_id"], account["refresh_token"]
            )
            if new_access:
                with pool_lock:
                    account["access_token"] = new_access
                    account["refresh_token"] = new_refresh
                    account["healthy"] = True
                    account["fail_count"] = 0

                refresh_account_balance_from_api(account)
                refreshed += 1

        save_accounts()
        print(f"[INFO] Refreshed {refreshed}/{len(accounts_copy)} tokens")


# ═══════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════
@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    try:
        auth_header = request.headers.get("Authorization", "")
        api_key = auth_header.replace("Bearer ", "").strip()

        if VALID_API_KEY is not None and api_key != VALID_API_KEY:
            return jsonify(
                {
                    "error": {
                        "message": "Invalid API key",
                        "type": "invalid_request_error",
                    }
                }
            ), 401

        data = request.json

        model = MODEL_MAP.get(
            data.get("model", DEFAULT_MODEL), data.get("model", DEFAULT_MODEL)
        )

        account = get_account_for_request(request.headers)
        if not account:
            return jsonify(
                {
                    "error": {
                        "message": "No healthy accounts available",
                        "type": "server_error",
                    }
                }
            ), 503

        ts = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-Authorization": account["access_token"],
            "X-Request-Id": str(uuid.uuid4()),
            "X-Request-Model": model,
            "X-Auth-Appid": APP_ID,
            "X-Auth-Timestamp": ts,
            "X-Auth-Sign": generate_sign(ts),
            "X-Product": "autoclaw",
            "X-Version": "1.9.1",
            "X-Tm": "win",
            "X-Trace-Id": str(uuid.uuid4()),
        }

        body = data.copy()
        body["stream"] = True

        # Forward request
        try:
            resp = requests.post(
                f"{PROXY_URL}/chat/completions",
                json=body,
                headers=headers,
                stream=True,
                timeout=60,
            )

            if resp.status_code != 200:
                mark_account_failed(account)
                if refresh_account_token(account):
                    ts = str(int(time.time()))
                    headers["X-Authorization"] = account["access_token"]
                    headers["X-Auth-Timestamp"] = ts
                    headers["X-Auth-Sign"] = generate_sign(ts)
                    headers["X-Trace-Id"] = str(uuid.uuid4())

                    resp = requests.post(
                        f"{PROXY_URL}/chat/completions",
                        json=body,
                        headers=headers,
                        stream=True,
                        timeout=60,
                    )

                    if resp.status_code != 200:
                        if resp.status_code == 402:
                            mark_account_depleted(account)

                            fallback_account = get_fallback_account(account)
                            if fallback_account:
                                print(
                                    f"[INFO] Fallback to {fallback_account['email']} after 402"
                                )

                                ts = str(int(time.time()))
                                headers["X-Authorization"] = fallback_account[
                                    "access_token"
                                ]
                                headers["X-Auth-Timestamp"] = ts
                                headers["X-Auth-Sign"] = generate_sign(ts)
                                headers["X-Trace-Id"] = str(uuid.uuid4())

                                resp = requests.post(
                                    f"{PROXY_URL}/chat/completions",
                                    json=body,
                                    headers=headers,
                                    stream=True,
                                    timeout=60,
                                )

                                if resp.status_code == 200:
                                    mark_account_success(fallback_account)
                                    account = fallback_account
                                else:
                                    return jsonify(
                                        {
                                            "error": {
                                                "message": f"Fallback also failed: {resp.text[:200]}",
                                                "type": "fallback_failed",
                                            }
                                        }
                                    ), resp.status_code
                            else:
                                return jsonify(
                                    {
                                        "error": {
                                            "message": "Insufficient balance and no fallback accounts available",
                                            "type": "no_balance",
                                        }
                                    }
                                ), 402
                        else:
                            return jsonify(
                                {
                                    "error": {
                                        "message": f"Retry failed after token refresh: {resp.text[:200]}",
                                        "type": "retry_failed",
                                    }
                                }
                            ), resp.status_code
                else:
                    return jsonify(
                        {
                            "error": {
                                "message": f"Upstream error: {resp.text[:200]}",
                                "type": "upstream_error",
                            }
                        }
                    ), resp.status_code

            mark_account_success(account)

            def generate():
                usage_data = None
                done_sent = False
                for line in resp.iter_lines():
                    if line:
                        line_str = (
                            line.decode("utf-8") if isinstance(line, bytes) else line
                        )

                        if done_sent:
                            break

                        if not line_str.startswith("data: "):
                            if line_str == "[DONE]":
                                yield b"data: [DONE]\n\n"
                                done_sent = True
                                break
                            else:
                                try:
                                    json.loads(line_str)
                                    yield f"data: {line_str}\n\n".encode("utf-8")
                                except json.JSONDecodeError:
                                    continue
                        else:
                            if "data: [DONE]" in line_str:
                                yield line + b"\n\n"
                                done_sent = True
                                break
                            else:
                                try:
                                    chunk_data = line_str[6:]
                                    chunk = json.loads(chunk_data)

                                    if "usage" in chunk:
                                        usage_data = chunk["usage"]

                                    yield line + b"\n\n"
                                except json.JSONDecodeError:
                                    continue

                if not done_sent:
                    yield b"data: [DONE]\n\n"

                if usage_data:
                    update_account_balance(account, usage_data)

            return Response(
                stream_with_context(generate()),
                content_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        except Exception as e:
            mark_account_failed(account)
            return jsonify({"error": {"message": str(e), "type": "request_error"}}), 500

    except Exception as e:
        return jsonify({"error": {"message": str(e), "type": "invalid_request"}}), 400


@app.route("/v1/models", methods=["GET"])
def list_models():
    return jsonify(
        {
            "object": "list",
            "data": [
                {"id": name, "object": "model", "owned_by": "autoclaw"}
                for name in MODEL_MAP.keys()
            ],
        }
    )


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    with pool_lock:
        healthy_count = sum(1 for acc in accounts_pool if acc["healthy"])
        total_balance = sum(acc["balance"] for acc in accounts_pool)

    return jsonify(
        {
            "status": "healthy" if healthy_count > 0 else "degraded",
            "accounts": {
                "total": len(accounts_pool),
                "healthy": healthy_count,
                "unhealthy": len(accounts_pool) - healthy_count,
            },
            "total_balance": total_balance,
        }
    )


@app.route("/", methods=["GET"])
def index():
    """Root endpoint"""
    return jsonify(
        {
            "service": "AutoClaw OpenAI Proxy",
            "version": "1.0.0",
            "endpoints": {
                "chat": "/v1/chat/completions",
                "models": "/v1/models",
                "health": "/health",
            },
        }
    )


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  AutoClaw OpenAI-Compatible Proxy")
    print("=" * 60)

    # Load accounts
    if not load_accounts():
        print("[ERROR] Failed to load accounts. Exiting.")
        exit(1)

    # Start background token refresh
    refresh_thread = threading.Thread(target=token_refresh_worker, daemon=True)
    refresh_thread.start()

    # Start server
    print("\n[INFO] Starting server on http://0.0.0.0:8070")
    print(
        "[INFO] OpenAI-compatible endpoint: http://localhost:8070/v1/chat/completions"
    )
    print("[INFO] Health check: http://localhost:8070/health\n")

    app.run(host="0.0.0.0", port=8070, threaded=True)
