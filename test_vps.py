#!/usr/bin/env python3
"""Test VPS proxy - all models with tool calling"""

import requests
import json
import os
import sys

BASE_URL = os.getenv("PROXY_URL", "http://localhost:8070")
if len(sys.argv) > 1:
    BASE_URL = sys.argv[1]

VPS_URL = f"{BASE_URL}/v1/chat/completions"

MODELS = [
    "glm-5.2",
    "glm-5-turbo",
    "deepseek-v4-pro",
    "deepseek-v4",
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather information",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"}
                },
                "required": ["location"],
            },
        },
    }
]


def test_model(model):
    print(f"\n{'=' * 60}")
    print(f"Testing: {model} on VPS")
    print("=" * 60)

    try:
        response = requests.post(
            VPS_URL,
            json={
                "model": model,
                "messages": [
                    {"role": "user", "content": "What's the weather in Tokyo?"}
                ],
                "tools": TOOLS,
                "stream": True,
            },
            stream=True,
            timeout=30,
        )

        if response.status_code != 200:
            print(f"❌ HTTP {response.status_code}")
            return False

        tool_calls_found = False

        for line in response.iter_lines():
            if not line:
                continue

            line = line.decode("utf-8")

            if line.startswith("data: "):
                data_str = line[6:]
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                    if "choices" in data and len(data["choices"]) > 0:
                        delta = data["choices"][0].get("delta", {})
                        if "tool_calls" in delta:
                            tool_calls_found = True
                            print(f"✅ Tool call detected: {delta['tool_calls']}")
                except:
                    pass

        if tool_calls_found:
            print(f"✅ SUCCESS - Tool calling works")
            return True
        else:
            print(f"❌ FAILED - No tool calls detected")
            return False

    except Exception as e:
        print(f"❌ Exception: {e}")
        return False


# Test health endpoint first
print("=" * 60)
print("VPS Proxy Health Check")
print("=" * 60)
try:
    health = requests.get(f"{BASE_URL}/health", timeout=10)
    print(json.dumps(health.json(), indent=2))
except Exception as e:
    print(f"❌ Health check failed: {e}")
    exit(1)

# Test all models
results = {}
for model in MODELS:
    results[model] = test_model(model)

# Summary
print("\n" + "=" * 60)
print("SUMMARY - VPS Deployment Test")
print("=" * 60)
for model, success in results.items():
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{model:20s} {status}")

all_pass = all(results.values())
print("\n" + "=" * 60)
if all_pass:
    print("✅ ALL TESTS PASSED - VPS proxy working perfectly!")
else:
    print("⚠️  SOME TESTS FAILED - Check results above")
print("=" * 60)
