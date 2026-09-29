"""Run while the backend is running to verify the assignment's API rules."""
import sys
import time
import uuid

import requests


BASE_URL = "http://127.0.0.1:8000"


def expect(response, code, label):
    if response.status_code != code:
        print(f"FAIL {label}: expected {code}, got {response.status_code}: {response.text}")
        sys.exit(1)
    print(f"PASS {label} ({code})")
    return response.json() if response.content else None


suffix = uuid.uuid4().hex[:8]
expect(requests.get(f"{BASE_URL}/healthz", timeout=5), 200, "health check")

users = []
for number in (1, 2):
    payload = {
        "username": f"test{number}_{suffix}",
        "email": f"test{number}_{suffix}@example.com",
        "password": "Testing2026!",
    }
    user = expect(
        requests.post(f"{BASE_URL}/api/auth/register", json=payload, timeout=10),
        201,
        f"register user {number}",
    )
    assert "password_hash" not in user and "password" not in user
    login = expect(
        requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": payload["username"], "password": payload["password"]},
            timeout=10,
        ),
        200,
        f"login user {number}",
    )
    users.append({"user": user, "token": login["access_token"]})

headers1 = {"Authorization": f"Bearer {users[0]['token']}"}
headers2 = {"Authorization": f"Bearer {users[1]['token']}"}
expect(requests.get(f"{BASE_URL}/api/auth/me", headers=headers1, timeout=5), 200, "me")
expect(requests.get(f"{BASE_URL}/api/auth/me", timeout=5), 401, "missing token")
expect(
    requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": "Bearer bad"}, timeout=5),
    401,
    "bad token",
)
expect(
    requests.get(f"{BASE_URL}/api/users/{users[0]['user']['id']}", headers=headers1, timeout=5),
    200,
    "read own user",
)

other_id = users[1]["user"]["id"]
expect(requests.get(f"{BASE_URL}/api/users/{other_id}", headers=headers1, timeout=5), 403, "block cross-account GET")
expect(requests.patch(f"{BASE_URL}/api/users/{other_id}", headers=headers1, json={"email": "blocked@example.com"}, timeout=5), 403, "block cross-account PATCH")
expect(requests.delete(f"{BASE_URL}/api/users/{other_id}", headers=headers1, timeout=5), 403, "block cross-account DELETE")

updated = expect(
    requests.patch(
        f"{BASE_URL}/api/users/{users[0]['user']['id']}",
        headers=headers1,
        json={"email": f"updated_{suffix}@example.com", "password": "Updated2026!"},
        timeout=10,
    ),
    200,
    "update own account",
)
assert "password_hash" not in updated and "password" not in updated
expect(requests.delete(f"{BASE_URL}/api/users/{users[0]['user']['id']}", headers=headers1, timeout=5), 200, "delete own account")
expect(requests.get(f"{BASE_URL}/api/auth/me", headers=headers1, timeout=5), 401, "deleted account token rejected")

# Clean up the second temporary account.
expect(requests.delete(f"{BASE_URL}/api/users/{other_id}", headers=headers2, timeout=5), 200, "cleanup")
print("\nAll assignment API checks passed.")

