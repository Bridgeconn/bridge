"""Spike for #506: can Bridge's AI requests run on a ChatGPT plan?

OpenAI's "Sign in with ChatGPT" lets an open-source app that runs locally spend
a Plus or Pro subscriber's plan allowance through the Responses API. Bridge
already speaks that API, but two things are not stated on OpenAI's pages and
decide whether the feature is worth building:

1. whether strict structured output (`text.format` `json_schema`) is accepted
   under plan usage, with Bridge's own review schema;
2. which models a signed-in account is offered.

This script answers both without touching the app:

    engine\\.venv\\Scripts\\python.exe scripts\\spike_chatgpt_signin.py

It opens the browser on OpenAI's sign-in page, waits for the redirect to
127.0.0.1, then lists the models, sends three test requests (plain text, a
small strict schema, and a request shaped like Bridge's tN/tW review), refreshes
the token once, signs out again, and writes a report.

    --replay <file>   also send a real request body captured with
                      `scripts/capture_ai_requests.py --dump` (it contains the
                      project's Scripture; the built-in tests send only one
                      public verse)
    --model <slug>    use this model instead of the first one offered
    --self-test       run the whole flow against a fake provider on this
                      computer: no browser, no account, nothing sent anywhere

What it keeps: `~/.bridge-chatgpt-signin-spike.json` holds the host id and the
client id OpenAI issued for this computer (neither is a secret). Tokens are
held in memory only and the refresh token is revoked before the script exits.
The report holds no token and no full email address.

Throwaway by design. It does NOT verify the ID token's signature, which the
real feature must do before trusting an identity; here the ID token is read
only to print a masked email and the names of its claims.
"""
from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import hmac
import json
import secrets
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit

REPO = Path(__file__).resolve().parents[1]

SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
RESOURCE = "https://api.openai.com/v1"
REDIRECT_PATH = "/auth/callback"
DEFAULT_PORT = 1455
AGENT_NAME = "Bridge"
USER_AGENT = "bridge-signin-spike"
REGISTRATION_CLIENT = "dynamic_agent_client"
# A parameter the request cannot do without: never dropped by the retry below.
ESSENTIAL_FIELDS = {"model", "input", "instructions", "stream", "store"}


@dataclass
class Provider:
    authorize_url: str = "https://auth.openai.com/api/accounts/authorize"
    token_url: str = "https://auth.openai.com/api/accounts/oauth/token"
    discovery_url: str = "https://auth.openai.com/.well-known/openid-configuration"
    api_base: str = "https://api.openai.com/v1"


class SpikeError(RuntimeError):
    pass


# -- small helpers ---------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def new_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    return verifier, _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def mask_email(email: str) -> str:
    name, _, domain = str(email).partition("@")
    return f"{name[:1]}***@{domain}" if domain else ""


def unverified_claims(id_token: str) -> dict[str, Any]:
    """The ID token's payload, NOT verified. Display only."""
    try:
        payload = id_token.split(".")[1]
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(decoded)
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}


def http(method: str, url: str, *, headers: dict[str, str] | None = None,
         form: dict[str, str] | None = None, timeout: float = 60.0,
         with_headers: bool = False) -> Any:
    all_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    data = None
    if form is not None:
        data = urlencode(form).encode("ascii")
        all_headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = (response.status, response.read(), dict(response.headers))
    except urllib.error.HTTPError as error:
        result = (error.code, error.read(), dict(error.headers))
    return result if with_headers else result[:2]


def as_json(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def error_summary(value: Any) -> dict[str, Any] | None:
    """`{code, param, message}` from an error body, a failed event or a `detail` body."""
    if not isinstance(value, dict):
        return None
    error = value.get("error")
    if isinstance(value.get("response"), dict) and isinstance(value["response"].get("error"), dict):
        error = value["response"]["error"]
    if isinstance(error, dict):
        return {"code": error.get("code"), "param": error.get("param"),
                "type": error.get("type"), "message": str(error.get("message") or "")[:400]}
    if isinstance(error, str):
        return {"code": error, "param": None, "type": None,
                "message": str(value.get("error_description") or "")[:400]}
    if "detail" in value:
        return {"code": None, "param": None, "type": "detail", "message": str(value["detail"])[:400]}
    return None


# -- sign-in ---------------------------------------------------------------

class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 -- http.server's name
        parsed = urlsplit(self.path)
        if parsed.path != REDIRECT_PATH:
            self.send_error(404)
            return
        server: Any = self.server
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        server.hits += 1
        if server.got.is_set() or not hmac.compare_digest(params.get("state", ""), server.state):
            # A stray or repeated request must not replace the real answer.
            self.send_error(400, "Invalid sign-in state")
            return
        server.result = params
        page = ("<html><body style='font-family:sans-serif'><h3>Bridge sign-in test</h3>"
                "<p>You can close this tab and go back to the terminal.</p></body></html>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)
        server.got.set()

    def log_message(self, *args: Any) -> None:  # the query carries the code: never log it
        pass


def load_registration(path: Path) -> dict[str, str]:
    try:
        value = json.loads(path.read_text("utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_registration(path: Path, registration: dict[str, str]) -> None:
    path.write_text(json.dumps(registration, indent=2), encoding="utf-8")


def sign_in(provider: Provider, registration_path: Path, port: int,
            open_browser: Callable[[str], Any], timeout: float, *,
            send_host_id: bool = False, new_registration: bool = False) -> dict[str, Any]:
    registration = load_registration(registration_path)
    if new_registration:
        registration.pop("client_id", None)
    new_registration = not registration.get("client_id")
    if not registration.get("ext_agent_host_id"):
        registration["ext_agent_host_id"] = f"urn:uuid:{uuid.uuid4()}"
        # OpenAI: the host id is persisted before the first sign-in.
        save_registration(registration_path, registration)

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), _CallbackHandler)
    except OSError as error:
        raise SpikeError(f"Port {port} on 127.0.0.1 is not free ({error}). Close what holds it "
                         f"or pass --port.") from error
    state, nonce = _b64url(secrets.token_bytes(32)), _b64url(secrets.token_bytes(32))
    server.result = {}  # type: ignore[attr-defined]
    server.hits = 0  # type: ignore[attr-defined]
    server.state = state  # type: ignore[attr-defined]
    server.got = threading.Event()  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    redirect_uri = f"http://127.0.0.1:{server.server_address[1]}{REDIRECT_PATH}"

    verifier, challenge = new_pkce()
    params = {
        "client_id": REGISTRATION_CLIENT if new_registration else registration["client_id"],
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    # OpenAI's reference client (sign-in-with-chatgpt-devkit, oauth.ts) sends the
    # host id only when told the deployment supports it, and defaults to not
    # sending it. The first run of this script sent it and the code exchange
    # was refused with invalid_grant.
    if send_host_id:
        params["ext_agent_host_id"] = registration["ext_agent_host_id"]
    if new_registration:
        params["agent_name_hint"] = AGENT_NAME
    url = f"{provider.authorize_url}?{urlencode(params)}"
    try:
        print("Opening the browser for sign-in. If it does not open, paste this address into it:\n")
        print(f"  {url}\n")
        open_browser(url)
        if not server.got.wait(timeout):  # type: ignore[attr-defined]
            raise SpikeError(f"No sign-in arrived within {int(timeout)} seconds.")
        callback: dict[str, str] = server.result  # type: ignore[attr-defined]
        callback_hits: int = server.hits  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        server.server_close()

    if callback.get("error"):
        raise SpikeError(f"Sign-in was refused: {callback['error']} "
                         f"{callback.get('error_description', '')}".strip())
    code = callback.get("code", "")
    if not code:
        raise SpikeError("The sign-in answer carried no code.")
    issued = callback.get("client_id", "")
    if new_registration:
        if not issued or issued == REGISTRATION_CLIENT:
            raise SpikeError("Registration is incomplete: no client id was issued.")
        registration["client_id"] = issued
        save_registration(registration_path, registration)
    elif issued and issued != registration["client_id"]:
        raise SpikeError("The sign-in answer named a different client id; refusing it.")

    status, body, headers = http("POST", provider.token_url, with_headers=True, form={
        "grant_type": "authorization_code",
        "client_id": registration["client_id"],
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "resource": RESOURCE,
    })
    tokens = as_json(body)
    if status != 200 or not tokens.get("access_token"):
        # An error body carries no credential; show all of it.
        request_id = next((v for k, v in headers.items() if k.lower() == "x-request-id"), "")
        raise SpikeError(
            f"The code exchange failed (HTTP {status}).\n"
            f"  error body: {body.decode('utf-8', 'replace')[:800]}\n"
            f"  request id: {request_id or '(none)'}\n"
            f"  new registration: {new_registration}; host id sent: {send_host_id}; "
            f"callback requests: {callback_hits}; callback fields: {sorted(callback)}; "
            f"code length: {len(code)}; redirect: {redirect_uri}\n"
            f"  scope the sign-in granted: {callback.get('scope', '(none)')}; issuer: {callback.get('iss', '(none)')}")
    granted = str(callback.get("scope") or tokens.get("scope") or "").split()
    return {
        "tokens": tokens,
        "clientId": registration["client_id"],
        "newRegistration": new_registration,
        "hostIdSent": send_host_id,
        "grantedScopes": sorted(granted),
        "redirectUri": redirect_uri,
    }


def refresh(provider: Provider, client_id: str, refresh_token: str) -> tuple[int, dict[str, Any]]:
    status, body = http("POST", provider.token_url, form={
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
        "resource": RESOURCE,
    })
    return status, as_json(body)


def revoke(provider: Provider, client_id: str, refresh_token: str) -> dict[str, Any]:
    status, body = http("GET", provider.discovery_url)
    endpoint = str(as_json(body).get("revocation_endpoint") or "")
    if status != 200 or not endpoint:
        return {"revoked": False, "why": f"no revocation endpoint (discovery HTTP {status})"}
    status, _ = http("POST", endpoint, form={
        "token": refresh_token, "token_type_hint": "refresh_token", "client_id": client_id,
    })
    return {"revoked": status == 200, "httpStatus": status}


# -- inference -------------------------------------------------------------

def list_models(provider: Provider, access_token: str) -> dict[str, Any]:
    status, body = http("GET", f"{provider.api_base}/models",
                        headers={"Authorization": f"Bearer {access_token}"})
    data = as_json(body)
    rows = data.get("models") if isinstance(data.get("models"), list) else data.get("data")
    rows = rows if isinstance(rows, list) else []
    listed = [
        {"slug": str(row.get("slug") or row.get("id") or ""), "displayName": str(row.get("display_name") or "")}
        for row in rows
        if isinstance(row, dict) and row.get("visibility", "list") == "list"
    ]
    return {
        "httpStatus": status,
        "topLevelKeys": sorted(data),
        "rowKeys": sorted(rows[0]) if rows and isinstance(rows[0], dict) else [],
        "total": len(rows),
        "listed": [row for row in listed if row["slug"]],
        "error": None if status == 200 else error_summary(data),
    }


def stream_response(provider: Provider, access_token: str, payload: dict[str, Any],
                    timeout: float = 240.0) -> dict[str, Any]:
    out: dict[str, Any] = {"httpStatus": None, "events": collections.Counter(), "text": "",
                           "completed": None, "failed": None, "error": None, "streamed": True}

    def handle(data: str) -> None:
        if data.strip() == "[DONE]":
            return
        try:
            event = json.loads(data)
        except Exception:
            out["events"]["<unparsed>"] += 1
            return
        kind = str(event.get("type") or "<no type>")
        out["events"][kind] += 1
        if kind == "response.output_text.delta":
            out["text"] += str(event.get("delta") or "")
        elif kind == "response.completed":
            out["completed"] = event.get("response") if isinstance(event.get("response"), dict) else event
        elif kind in ("response.failed", "response.incomplete", "error"):
            out["failed"] = kind
            out["error"] = error_summary(event) or {"code": None, "param": None, "type": kind, "message": ""}

    request = urllib.request.Request(
        f"{provider.api_base}/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json",
                 "Accept": "text/event-stream", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        out["httpStatus"] = error.code
        out["error"] = error_summary(as_json(error.read())) or {"code": None, "param": None,
                                                                 "type": None, "message": ""}
        return out
    with response:
        out["httpStatus"] = response.status
        if "text/event-stream" not in str(response.headers.get("Content-Type") or ""):
            # Not a stream after all: one JSON body.
            out["streamed"] = False
            body = as_json(response.read())
            out["completed"] = body or None
            return out
        data_lines: list[str] = []
        for raw in response:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                if data_lines:
                    handle("\n".join(data_lines))
                    data_lines = []
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            handle("\n".join(data_lines))
    return out


def completed_text(completed: Any) -> str:
    """The output text of a completed response object, as ai_client._extract_text reads it."""
    if not isinstance(completed, dict):
        return ""
    if isinstance(completed.get("output_text"), str):
        return completed["output_text"]
    parts: list[str] = []
    for item in completed.get("output") or []:
        for content in (item.get("content") or []) if isinstance(item, dict) else []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "".join(parts)


def run_test(provider: Provider, access_token: str, name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Send `payload`; when the provider names an unsupported parameter, drop
    that one field and send again, so the report says exactly what is refused."""
    attempts: list[dict[str, Any]] = []
    for _ in range(4):
        started = time.monotonic()
        result = stream_response(provider, access_token, payload)
        completed = result["completed"] if isinstance(result["completed"], dict) else {}
        text = result["text"] or completed_text(completed)
        try:
            parsed = json.loads(text) if text else None
        except Exception:
            parsed = None
        ok = result["httpStatus"] == 200 and result["completed"] is not None and not result["failed"]
        attempts.append({
            "test": name,
            "ok": ok,
            "sentFields": sorted(payload),
            "model": payload.get("model"),
            "httpStatus": result["httpStatus"],
            "streamed": result["streamed"],
            "eventTypes": dict(result["events"]),
            "completedSeen": result["completed"] is not None,
            "completedHasOutput": "output" in completed,
            "completedHasUsage": isinstance(completed.get("usage"), dict),
            "usage": completed.get("usage"),
            "error": result["error"],
            "outputChars": len(text),
            "outputPreview": text[:300],
            "outputIsJson": parsed is not None,
            "jsonTopLevelKeys": sorted(parsed) if isinstance(parsed, dict) else None,
            "seconds": round(time.monotonic() - started, 1),
        })
        param = str((result["error"] or {}).get("param") or "")
        field = param.split(".")[0].split("[")[0]
        if ok or not field or field not in payload or field in ESSENTIAL_FIELDS:
            break
        payload = {key: value for key, value in payload.items() if key != field}
    return attempts


# -- the test requests -----------------------------------------------------

def plain_payload(model: str) -> dict[str, Any]:
    return {"model": model, "store": False, "stream": True,
            "instructions": "Reply with the single word: ready.", "input": "Say ready."}


def small_schema_payload(model: str) -> dict[str, Any]:
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}},
              "required": ["answer", "confidence"]}
    return {"model": model, "store": False, "stream": True,
            "instructions": "Answer in the JSON shape you are given.",
            "input": "What is the capital of France?",
            "text": {"format": {"type": "json_schema", "name": "spike_small", "strict": True, "schema": schema}}}


def bridge_review_payload(model: str) -> dict[str, Any] | None:
    """A request with Bridge's real review instructions and answer schema, sent
    exactly as `ai_client._post_text` shapes it. The INPUT is a hand-made
    miniature (one public verse, one translationWords check), not what Bridge
    builds for a project: this proves the schema is accepted, not a verdict."""
    try:
        sys.path.insert(0, str(REPO / "engine"))
        from tc_ai_bridge.ai_client import review_check_schema, review_instructions, review_issue_schema
    except Exception as error:  # run with the engine's interpreter to get this test
        print(f"  (Bridge review test skipped: the engine could not be imported: {error})")
        return None
    language = SimpleNamespace(source_name="Greek", target_name="English",
                               qa_categories=["spelling", "punctuation", "grammar"], prompt_guidance="")
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "check_reviews": {"type": "array", "items": review_check_schema(), "minItems": 1, "maxItems": 1},
            "qa_issues": {"type": "array", "items": review_issue_schema()},
        },
        "required": ["summary", "check_reviews", "qa_issues"],
    }
    input_obj = {
        "reference": "Titus 1:1",
        "source_text": "Παῦλος δοῦλος Θεοῦ",
        "target_text": "Paul, a servant of God",
        "target_tokens": [{"id": "t1", "text": "Paul"}, {"id": "t2", "text": "a"}, {"id": "t3", "text": "servant"},
                          {"id": "t4", "text": "of"}, {"id": "t5", "text": "God"}],
        "checks": [{"tool": "translationWords", "group_id": "servant", "check_id": "tw-1",
                    "source_quote": "δοῦλος", "evidence_ids": ["e1"]}],
        "evidence": [{"id": "e1", "text": "servant, slave: a person who works for or is owned by another person."}],
        "expected_check_reviews": 1,
    }
    return {
        "model": model, "store": False, "stream": True,
        "instructions": review_instructions(language, 1),
        "input": json.dumps(input_obj, ensure_ascii=False),
        "text": {"format": {"type": "json_schema", "name": "tc_full_review", "strict": True, "schema": schema}},
        "reasoning": {"effort": "medium"},
        "prompt_cache_key": "bridge-signin-spike",
    }


def replay_payload(path: Path, model: str) -> dict[str, Any]:
    payload = json.loads(path.read_text("utf-8"))
    if not isinstance(payload, dict):
        raise SpikeError(f"{path} is not a request body.")
    return {**payload, "model": model, "store": False, "stream": True}


# -- the run ---------------------------------------------------------------

def run(provider: Provider, *, registration_path: Path, port: int, model: str, replay: Path | None,
        open_browser: Callable[[str], Any], timeout: float,
        send_host_id: bool = False, new_registration: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {"ranAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "tests": []}
    session = sign_in(provider, registration_path, port, open_browser, timeout,
                      send_host_id=send_host_id, new_registration=new_registration)
    tokens = session["tokens"]
    refresh_token = str(tokens.get("refresh_token") or "")
    try:
        claims = unverified_claims(str(tokens.get("id_token") or ""))
        report["signIn"] = {
            "newRegistration": session["newRegistration"],
            "hostIdSent": session["hostIdSent"],
            "clientIdPrefix": session["clientId"][:7],
            "grantedScopes": session["grantedScopes"],
            "planUseGranted": PLAN_SCOPE in session["grantedScopes"],
            "tokenResponseKeys": sorted(tokens),
            "expiresIn": tokens.get("expires_in"),
            "hasRefreshToken": bool(refresh_token),
            "email": mask_email(str(claims.get("email") or "")),
            "idTokenClaimNames": sorted(claims),
        }
        print(f"Signed in as {report['signIn']['email'] or '(no email claim)'}; "
              f"plan use granted: {report['signIn']['planUseGranted']}")
        access_token = str(tokens["access_token"])

        models = list_models(provider, access_token)
        report["models"] = models
        slugs = [row["slug"] for row in models["listed"]]
        print(f"Models offered ({len(slugs)}): {', '.join(slugs) or 'none'}")
        chosen = model or (slugs[0] if slugs else "")
        if not chosen:
            raise SpikeError(f"No model to test with (models HTTP {models['httpStatus']}: {models['error']}).")
        report["modelTested"] = chosen

        payloads: list[tuple[str, dict[str, Any] | None]] = [
            ("plain text", plain_payload(chosen)),
            ("small strict schema", small_schema_payload(chosen)),
            ("Bridge review schema", bridge_review_payload(chosen)),
        ]
        # The same request again: does the second one report cached input?
        payloads.append(("Bridge review schema, repeated", payloads[2][1]))
        if replay is not None:
            payloads.append((f"replayed request {replay.name}", replay_payload(replay, chosen)))
        for name, payload in payloads:
            if payload is None:
                continue
            print(f"Sending: {name} ...")
            attempts = run_test(provider, access_token, name, payload)
            report["tests"].extend(attempts)
            for attempt in attempts:
                verdict = "ok" if attempt["ok"] else f"FAILED {attempt['error']}"
                print(f"  HTTP {attempt['httpStatus']}, {attempt['seconds']}s, JSON: {attempt['outputIsJson']}, {verdict}")

        if refresh_token:
            status, refreshed = refresh(provider, session["clientId"], refresh_token)
            rotated = str(refreshed.get("refresh_token") or "")
            report["refresh"] = {"httpStatus": status, "gotAccessToken": bool(refreshed.get("access_token")),
                                 "refreshTokenRotated": bool(rotated) and rotated != refresh_token,
                                 "error": None if status == 200 else error_summary(refreshed)}
            refresh_token = rotated or refresh_token
    finally:
        if refresh_token:
            report["signOut"] = revoke(provider, session["clientId"], refresh_token)
            print(f"Signed out (refresh token revoked: {report['signOut'].get('revoked')}).")
    return report


# -- self-test: a fake provider on this computer ---------------------------

class _FakeProvider(BaseHTTPRequestHandler):
    """Just enough of the documented contract to exercise every step above."""
    challenge = ""
    host_ids: list[str | None] = []
    refresh_tokens: set[str] = set()
    revoked: list[str] = []

    def _send(self, status: int, body: bytes, content_type: str = "application/json",
              extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: Any) -> None:
        self._send(status, json.dumps(value).encode("utf-8"))

    def _form(self) -> dict[str, str]:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        if parsed.path == "/authorize":
            wanted = {"client_id": REGISTRATION_CLIENT, "agent_name_hint": AGENT_NAME, "response_type": "code",
                      "scope": SCOPE, "resource": RESOURCE, "code_challenge_method": "S256"}
            wrong = [k for k, v in wanted.items() if query.get(k) != v]
            host_id = query.get("ext_agent_host_id")
            if wrong or (host_id is not None and not host_id.startswith("urn:uuid:")):
                self._json(400, {"error": "invalid_request", "error_description": f"bad {wrong}"})
                return
            type(self).challenge = query["code_challenge"]
            type(self).host_ids.append(host_id)
            back = urlencode({"code": "fake-code", "state": query["state"], "client_id": "oaiapp_selftest",
                              "scope": SCOPE})
            self._send(302, b"", extra={"Location": f"{query['redirect_uri']}?{back}"})
        elif parsed.path == "/.well-known/openid-configuration":
            self._json(200, {"revocation_endpoint": f"{base}/revoke"})
        elif parsed.path == "/v1/models":
            if self.headers.get("Authorization") != "Bearer fake-access":
                self._json(401, {"detail": "bad token"})
                return
            self._json(200, {"models": [
                {"slug": "fake-large", "display_name": "Fake Large", "visibility": "list"},
                {"slug": "fake-hidden", "display_name": "Hidden", "visibility": "hide"},
            ]})
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/token":
            form = self._form()
            if form.get("grant_type") == "authorization_code":
                expected = _b64url(hashlib.sha256(form.get("code_verifier", "").encode("ascii")).digest())
                if (form.get("code") != "fake-code" or expected != type(self).challenge
                        or form.get("client_id") != "oaiapp_selftest" or form.get("resource") != RESOURCE):
                    self._json(400, {"error": "invalid_grant"})
                    return
            elif form.get("grant_type") == "refresh_token":
                if form.get("refresh_token") not in type(self).refresh_tokens or "scope" in form:
                    self._json(400, {"error": "invalid_grant"})
                    return
                type(self).refresh_tokens.discard(form["refresh_token"])
            else:
                self._json(400, {"error": "unsupported_grant_type"})
                return
            new_refresh = f"fake-refresh-{len(type(self).refresh_tokens)}-{secrets.token_hex(4)}"
            type(self).refresh_tokens.add(new_refresh)
            claims = _b64url(json.dumps({"email": "tester@example.com", "sub": "user-1"}).encode("utf-8"))
            self._json(200, {"access_token": "fake-access", "refresh_token": new_refresh,
                             "id_token": f"e30.{claims}.sig", "token_type": "Bearer", "expires_in": 3600})
        elif path == "/revoke":
            type(self).revoked.append(self._form().get("token", ""))
            self._send(200, b"")
        elif path == "/v1/responses":
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
            if body.get("stream") is not True or body.get("store") is not False:
                self._json(400, {"error": {"code": "subscription_sharing_unsupported_capability",
                                           "param": "stream", "message": "stream:true and store:false required"}})
                return
            if "prompt_cache_key" in body:  # exercises the drop-one-field retry
                self._json(400, {"error": {"code": "subscription_sharing_unsupported_capability",
                                           "param": "prompt_cache_key", "message": "unsupported"}})
                return
            text = '{"summary":"s","check_reviews":[],"qa_issues":[]}' if "text" in body else "ready"
            half = len(text) // 2
            events = [
                {"type": "response.created"},
                {"type": "response.output_text.delta", "delta": text[:half]},
                {"type": "response.output_text.delta", "delta": text[half:]},
                {"type": "response.completed", "response": {
                    "output": [{"content": [{"type": "output_text", "text": text}]}],
                    "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13,
                              "input_tokens_details": {"cached_tokens": 0}}}},
            ]
            stream = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode("utf-8")
            self._send(200, stream, content_type="text/event-stream")
        else:
            self.send_error(404)

    def log_message(self, *args: Any) -> None:
        pass


def self_test() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeProvider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    provider = Provider(authorize_url=f"{base}/authorize", token_url=f"{base}/token",
                        discovery_url=f"{base}/.well-known/openid-configuration", api_base=f"{base}/v1")

    def fake_browser(url: str) -> None:  # follows the redirect to the loopback callback
        threading.Thread(target=lambda: urllib.request.urlopen(url, timeout=10).read(), daemon=True).start()

    try:
        with tempfile.TemporaryDirectory() as work:
            registration_path = Path(work) / "registration.json"
            report = run(provider, registration_path=registration_path, port=0, model="", replay=None,
                         open_browser=fake_browser, timeout=10)
            registration = load_registration(registration_path)
    finally:
        server.shutdown()
        server.server_close()

    by_name: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for attempt in report["tests"]:
        by_name[attempt["test"]].append(attempt)
    review = by_name.get("Bridge review schema", [])
    checks = {
        "registered a client id": registration.get("client_id") == "oaiapp_selftest",
        "kept a host id": str(registration.get("ext_agent_host_id", "")).startswith("urn:uuid:"),
        "host id not sent unless asked": _FakeProvider.host_ids == [None],
        "plan scope granted": report["signIn"]["planUseGranted"],
        "email masked": report["signIn"]["email"] == "t***@example.com",
        "hidden model left out": [m["slug"] for m in report["models"]["listed"]] == ["fake-large"],
        "plain text completed": by_name["plain text"][-1]["ok"] and by_name["plain text"][-1]["outputPreview"] == "ready",
        "strict schema parsed": by_name["small strict schema"][-1]["outputIsJson"],
        "usage read from completed": by_name["plain text"][-1]["usage"]["input_tokens"] == 10,
        "refused field dropped and retried": (not review) or (
            len(review) == 2 and review[0]["error"]["param"] == "prompt_cache_key"
            and "prompt_cache_key" not in review[1]["sentFields"] and review[1]["ok"]),
        "refresh token rotated": report["refresh"]["refreshTokenRotated"],
        "signed out with the rotated token": report["signOut"]["revoked"] and len(_FakeProvider.revoked) == 1
                                             and _FakeProvider.revoked[0] in _FakeProvider.refresh_tokens,
        "no token in the report": "fake-access" not in json.dumps(report) and "fake-refresh" not in json.dumps(report),
    }
    for name, passed in checks.items():
        print(f"  {'ok  ' if passed else 'FAIL'} {name}")
    if not review:
        print("  note: the Bridge review test was skipped (engine not importable with this interpreter)")
    passed_all = all(checks.values())
    print("SELF-TEST PASSED" if passed_all else "SELF-TEST FAILED")
    return 0 if passed_all else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default="", help="Model slug to test (default: the first one offered).")
    parser.add_argument("--replay", default="", help="A request body from capture_ai_requests.py --dump.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Loopback port for the sign-in redirect.")
    parser.add_argument("--timeout", type=float, default=300.0, help="Seconds to wait for the sign-in.")
    parser.add_argument("--registration", default=str(Path.home() / ".bridge-chatgpt-signin-spike.json"),
                        help="Where the host id and issued client id are kept.")
    parser.add_argument("--report", default=str(Path(tempfile.gettempdir()) / "bridge-chatgpt-signin-spike-report.json"),
                        help="Where the report is written.")
    parser.add_argument("--send-host-id", action="store_true",
                        help="Send ext_agent_host_id on the authorization request (OpenAI's reference client "
                             "leaves it out by default).")
    parser.add_argument("--new-registration", action="store_true",
                        help="Ignore the saved client id and register this computer again.")
    parser.add_argument("--self-test", action="store_true", help="Run against a fake local provider.")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if args.self_test:
        return self_test()
    try:
        report = run(Provider(), registration_path=Path(args.registration), port=args.port, model=args.model,
                     replay=Path(args.replay) if args.replay else None,
                     open_browser=webbrowser.open, timeout=args.timeout,
                     send_host_id=args.send_host_id, new_registration=args.new_registration)
    except SpikeError as error:
        print(f"\nStopped: {error}")
        return 1
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport written to {args.report}")
    print("It holds no token and no full email address; send it back as it is.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
