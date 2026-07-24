import json
import urllib.request
import urllib.error

url = "https://api.mistral.ai/v1/chat/completions"
api_key = "Hs0rbI257TWjVuuHPUkSg9MToULOmjPp"
model = "mistral-large-latest"

payload = {
    "model": model,
    "messages": [{"role": "user", "content": "Hello"}],
    "temperature": 0.0,
    "max_tokens": 50
}

data_encoded = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(
    url,
    data=data_encoded,
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    method="POST",
)

try:
    resp = urllib.request.urlopen(req, timeout=10)
    print("SUCCESS!")
    print(resp.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    print(f"HTTP ERROR {e.code}")
    print(e.read().decode("utf-8"))
except Exception as e:
    print(f"OTHER ERROR: {e}")
