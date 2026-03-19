#!/usr/bin/env python3
"""Mint a Google OAuth access token for delegated Google Workspace access."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


TOKEN_URI = "https://oauth2.googleapis.com/token"
IAM_SIGNJWT_URI = "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{service_account}:signJwt"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def load_service_account(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"type", "client_email", "private_key"}
    missing = sorted(required - set(payload.keys()))
    if missing:
        raise ValueError(f"service account JSON missing keys: {', '.join(missing)}")
    if payload["type"] != "service_account":
        raise ValueError("credentials file is not a service account JSON")
    return payload


def make_claims(issuer: str, subject: str, scopes: str, audience: str) -> dict:
    now = int(time.time())
    return {
        "iss": issuer,
        "sub": subject,
        "scope": scopes,
        "aud": audience,
        "iat": now,
        "exp": now + 3600,
    }


def parse_scopes(raw: str) -> str:
    pieces = [part.strip() for chunk in raw.split(",") for part in chunk.split()]
    scopes = [scope for scope in pieces if scope]
    if not scopes:
        raise ValueError("at least one OAuth scope is required")
    return " ".join(dict.fromkeys(scopes))


def sign_rs256(message: bytes, private_key_pem: str) -> bytes:
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
        handle.write(private_key_pem)
        key_path = handle.name
    try:
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=message,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout
    finally:
        try:
            os.remove(key_path)
        except FileNotFoundError:
            pass


def mint_access_token_with_key(service_account: dict, subject: str, scopes: str) -> dict:
    header = {"alg": "RS256", "typ": "JWT"}
    claims = make_claims(
        issuer=service_account["client_email"],
        subject=subject,
        scopes=scopes,
        audience=service_account.get("token_uri", TOKEN_URI),
    )
    signing_input = f"{b64url(json.dumps(header, separators=(',', ':')).encode())}.{b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    signature = sign_rs256(signing_input.encode("ascii"), service_account["private_key"])
    assertion = f"{signing_input}.{b64url(signature)}"
    return exchange_jwt_assertion(assertion, service_account.get("token_uri", TOKEN_URI))


def sign_jwt_via_iam_credentials(
    service_account_email: str,
    subject: str,
    scopes: str,
    operator_access_token: str,
) -> str:
    claims = make_claims(
        issuer=service_account_email,
        subject=subject,
        scopes=scopes,
        audience=TOKEN_URI,
    )
    payload = json.dumps({"payload": json.dumps(claims, separators=(",", ":"))}).encode("utf-8")
    request = urllib.request.Request(
        IAM_SIGNJWT_URI.format(service_account=urllib.parse.quote(service_account_email, safe="")),
        data=payload,
        headers={
            "Authorization": f"Bearer {operator_access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"IAM signJwt failed: HTTP {exc.code}: {detail}") from exc
    signed_jwt = body.get("signedJwt")
    if not signed_jwt:
        raise RuntimeError(f"IAM Credentials response missing signedJwt: {body}")
    return signed_jwt


def exchange_jwt_assertion(assertion: str, token_uri: str = TOKEN_URI) -> dict:
    body = urllib.parse.urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        token_uri,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"token exchange failed: HTTP {exc.code}: {detail}") from exc
    if "access_token" not in payload:
        raise RuntimeError(f"token endpoint response missing access_token: {payload}")
    return payload


def mint_access_token_via_iam_credentials(
    service_account_email: str,
    subject: str,
    scopes: str,
    operator_access_token: str,
) -> dict:
    signed_jwt = sign_jwt_via_iam_credentials(
        service_account_email=service_account_email,
        subject=subject,
        scopes=scopes,
        operator_access_token=operator_access_token,
    )
    return exchange_jwt_assertion(signed_jwt, TOKEN_URI)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-account-file")
    parser.add_argument("--service-account-email")
    parser.add_argument("--operator-access-token")
    parser.add_argument("--subject", required=True, help="Workspace user email to impersonate")
    parser.add_argument("--scopes", required=True, help="Comma or space separated OAuth scopes")
    parser.add_argument("--print-json", action="store_true", help="Print the full token payload as JSON")
    args = parser.parse_args()

    try:
        scopes = parse_scopes(args.scopes)
        if args.service_account_file:
            service_account = load_service_account(Path(args.service_account_file).expanduser())
            payload = mint_access_token_with_key(service_account, args.subject, scopes)
        elif args.service_account_email and args.operator_access_token:
            payload = mint_access_token_via_iam_credentials(
                service_account_email=args.service_account_email,
                subject=args.subject,
                scopes=scopes,
                operator_access_token=args.operator_access_token,
            )
        else:
            raise ValueError(
                "provide either --service-account-file, or --service-account-email with --operator-access-token"
            )
    except Exception as exc:
        print(f"Failed to mint delegated token: {exc}", file=sys.stderr)
        return 1

    if args.print_json:
        print(json.dumps(payload, indent=2))
    else:
        print(payload["access_token"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
