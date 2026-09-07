"""Exercise real Keycloak Code/PKCE login over verified TLS on the disposable VM."""

import base64
import hashlib
import json
import secrets
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests

PRIVATE = Path(__file__).resolve().parents[1] / ".private"
ISSUER = "https://localhost/realms/company"
CALLBACK = "https://localhost/smoke/callback"


class LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.inside = False
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "kc-form-login":
            self.action = attrs.get("action")
            self.inside = True
        elif tag == "input" and self.inside and attrs.get("name"):
            self.fields[attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.inside = False


def verify_login():
    with requests.Session() as client:
        client.verify = str(PRIVATE / "smoke-ca.crt")
        response = client.get(ISSUER + "/.well-known/openid-configuration", timeout=10)
        response.raise_for_status()
        metadata = response.json()
        assert metadata["issuer"] == ISSUER
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        state = secrets.token_urlsafe(32)
        response = client.get(
            metadata["authorization_endpoint"],
            params={
                "client_id": "identity-smoke",
                "response_type": "code",
                "redirect_uri": CALLBACK,
                "scope": "openid profile email",
                "state": state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
            },
            timeout=10,
        )
        response.raise_for_status()
        form = LoginForm()
        form.feed(response.text)
        assert form.action, "Expected the Keycloak login form"
        action = urljoin(response.url, form.action)
        assert urlparse(action).netloc == "localhost"
        password = (PRIVATE / "smoke-user-password").read_text().strip()
        response = client.post(
            action,
            data={**form.fields, "username": "smoke-user", "password": password},
            allow_redirects=False,
            timeout=10,
        )
        assert response.status_code in (302, 303), "Keycloak did not complete login"
        callback = urlparse(response.headers["Location"])
        assert (callback.scheme, callback.netloc, callback.path) == (
            "https",
            "localhost",
            "/smoke/callback",
        )
        query = parse_qs(callback.query)
        assert query.get("state") == [state]
        response = client.post(
            metadata["token_endpoint"],
            data={
                "client_id": "identity-smoke",
                "grant_type": "authorization_code",
                "redirect_uri": CALLBACK,
                "code": query["code"][0],
                "code_verifier": verifier,
            },
            timeout=10,
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        assert claims["iss"] == ISSUER
        audience = claims["aud"]
        assert "identity-smoke-api" in ([audience] if isinstance(audience, str) else audience)
        response = client.get(
            metadata["userinfo_endpoint"], headers={"Authorization": "Bearer " + token}, timeout=10
        )
        response.raise_for_status()
        assert response.json()["sub"] == claims["sub"]
        response = client.post(
            metadata["token_endpoint"],
            data={
                "client_id": "identity-smoke",
                "grant_type": "password",
                "username": "smoke-user",
                "password": password,
            },
            timeout=10,
        )
        assert response.status_code == 400
        assert response.json()["error"] == "unauthorized_client"
    print("TLS discovery, Code/PKCE, audience, userinfo and disabled password grant: passed")


if __name__ == "__main__":
    try:
        verify_login()
    except Exception as exc:
        # Do not expose tokens, codes or credential-bearing response bodies in CI.
        raise SystemExit(f"Identity login smoke failed: {type(exc).__name__}") from None
