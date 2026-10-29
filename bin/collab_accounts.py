"""Shared projects: verifying an Orbit account token OFFLINE. See docs/collab/ACCOUNTS.md and DESIGN.md section 7.

A host never calls the account service to check who someone is. The service signs a short-lived token (EdDSA / Ed25519 JWT, 15 minutes,
claims sub, name, optional avatar, iat, exp, iss, aud "orbit", jti) and publishes its public keys at /.well-known/jwks.json; the host keeps
a copy of those keys and checks the signature and the claims itself. `verify_token` is that check. `JwksCache` is the copy of the keys.

The check is deliberately narrow: ONE algorithm (EdDSA), whatever the token's header says; no key is ever taken from the token (jwk / jku
headers are ignored); the key is chosen by `kid` from the published set only. Everything that touches the world (the clock, the network) is
passed in, so every rule here is tested without either.
"""
import base64
import json
import re
import threading
import time
import urllib.parse
import urllib.request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MAX_TOKEN_BYTES = 8192
ACCESS_TTL = 15 * 60
_B64U = re.compile(r"[A-Za-z0-9_-]*")


class AccountTokenError(Exception):
    """A token that must not be trusted. `reason` is one short word: oversize, malformed, bad_alg, unsupported_header, unknown_kid,
    bad_signature, expired, not_yet_valid, bad_aud, bad_iss, missing_claim, bad_jwks, jwks_unavailable."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _b64u(s):
    """Strict base64url: the URL-safe alphabet only, no padding, no whitespace. Anything else is malformed."""
    if not isinstance(s, str) or not _B64U.fullmatch(s) or len(s) % 4 == 1:
        raise AccountTokenError("malformed")
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except Exception:
        raise AccountTokenError("malformed")


def _json_object(raw):
    def refuse(_):  # NaN / Infinity are not JSON; a claim must not be able to smuggle one in
        raise ValueError
    try:
        v = json.loads(raw.decode("utf-8"), parse_constant=refuse)
    except Exception:
        raise AccountTokenError("malformed")
    if not isinstance(v, dict):
        raise AccountTokenError("malformed")
    return v


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float("inf"), float("-inf"))


def parse_jwks(jwks):
    """{kid: Ed25519 public key} from a JWKS document (dict, or JSON text). Keys of another type are skipped; a repeated kid or a
    malformed Ed25519 key makes the whole document `bad_jwks`, because nothing in it can then be trusted to mean what it says."""
    if isinstance(jwks, (str, bytes)):
        try:
            jwks = json.loads(jwks)
        except Exception:
            raise AccountTokenError("bad_jwks")
    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        raise AccountTokenError("bad_jwks")
    out = {}
    for k in jwks["keys"]:
        if not isinstance(k, dict) or k.get("kty") != "OKP" or k.get("crv") != "Ed25519":
            continue
        if k.get("use", "sig") != "sig" or k.get("alg", "EdDSA") != "EdDSA":
            continue
        kid = k.get("kid")
        if not isinstance(kid, str) or not kid or kid in out:
            raise AccountTokenError("bad_jwks")
        try:
            out[kid] = Ed25519PublicKey.from_public_bytes(_b64u(k.get("x")))
        except (AccountTokenError, ValueError):
            raise AccountTokenError("bad_jwks")
    return out


def verify_token(token, jwks, now=None, aud="orbit", iss=None, skew=30):
    """Verify an account token against a JWKS and return its claims, or raise AccountTokenError(reason).

    `jwks` is the published key set ({"keys": [...]}). `iss`, when given, must equal the token's issuer: pass it, so a token from another
    deployment of the service is not accepted. `skew` seconds of clock difference are tolerated on exp / iat / nbf.
    """
    if not isinstance(token, str):
        raise AccountTokenError("malformed")
    if len(token) > MAX_TOKEN_BYTES:
        raise AccountTokenError("oversize")
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise AccountTokenError("malformed")
    header, claims, sig = _json_object(_b64u(parts[0])), _json_object(_b64u(parts[1])), _b64u(parts[2])

    if header.get("alg") != "EdDSA":  # none, HS256 (HMAC keyed with the public key), RS256 ...: never
        raise AccountTokenError("bad_alg")
    if "crit" in header:  # extensions we do not implement must be refused, not ignored
        raise AccountTokenError("unsupported_header")
    kid = header.get("kid")
    if not isinstance(kid, str):
        raise AccountTokenError("unknown_kid")
    key = parse_jwks(jwks).get(kid)  # a jwk / jku header in the token is never consulted
    if key is None:
        raise AccountTokenError("unknown_kid")
    try:
        key.verify(sig, (parts[0] + "." + parts[1]).encode("ascii"))
    except InvalidSignature:
        raise AccountTokenError("bad_signature")

    now = time.time() if now is None else now
    exp, iat = claims.get("exp"), claims.get("iat")
    if not _is_num(exp) or not _is_num(iat):
        raise AccountTokenError("missing_claim")
    if now > exp + skew:
        raise AccountTokenError("expired")
    if iat > now + skew or ("nbf" in claims and (not _is_num(claims["nbf"]) or claims["nbf"] > now + skew)):
        raise AccountTokenError("not_yet_valid")
    have = claims.get("aud")
    if aud is not None and aud not in (have if isinstance(have, list) else [have]):
        raise AccountTokenError("bad_aud")
    if iss is not None and claims.get("iss") != iss:
        raise AccountTokenError("bad_iss")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise AccountTokenError("missing_claim")
    return claims


class JwksCache:
    """The host's copy of the service's public keys.

    fetch        callable returning the JWKS (dict or JSON text); injected, so the cache never decides how to reach the network
    ttl          seconds a fetched set is used before it is fetched again
    keep_previous  seconds a key stays usable after the service stops publishing it (default: a token's lifetime plus slack), so a
                 token signed just before a rotation is still checked; `drop_previous()` ends that at once if a key is compromised
    min_refresh  an unknown `kid` forces one refetch, but never more often than this (a stream of junk tokens cannot make the host hammer
                 the service)
    max_stale    if the service cannot be reached, the last good set is used for at most this long; after that, tokens are refused
    """

    def __init__(self, fetch, ttl=3600, keep_previous=ACCESS_TTL + 300, min_refresh=60, max_stale=86400, now=time.time):
        self._fetch, self.ttl, self.keep_previous = fetch, ttl, keep_previous
        self.min_refresh, self.max_stale, self._now = min_refresh, max_stale, now
        self._lock = threading.Lock()
        self._current = {}        # kid -> jwk dict, as last published
        self._previous = {}       # kid -> (jwk dict, time the service stopped publishing it)
        self._fetched = None      # time of the last successful fetch
        self._attempted = None    # time of the last attempt, successful or not

    # -- the key set -------------------------------------------------------------------------------------------------------------------
    def _refresh_locked(self, now):
        self._attempted = now
        doc = self._fetch()
        parse_jwks(doc)  # validates the whole document before anything is replaced; a bad answer changes nothing
        if isinstance(doc, (str, bytes)):
            doc = json.loads(doc)
        new = {k["kid"]: k for k in doc["keys"] if isinstance(k, dict) and isinstance(k.get("kid"), str)}
        for kid, jwk in self._current.items():
            if kid not in new:
                self._previous[kid] = (jwk, now)
        for kid in new:
            self._previous.pop(kid, None)  # published again: it is current, not previous
        self._current, self._fetched = new, now

    def _expire_previous(self, now):
        self._previous = {k: v for k, v in self._previous.items() if now - v[1] <= self.keep_previous}

    def jwks(self, now=None):
        """The keys to verify with right now: current plus still-retained previous ones."""
        now = self._now() if now is None else now
        with self._lock:
            if self._fetched is None or now - self._fetched >= self.ttl:
                recently = self._attempted is not None and now - self._attempted < self.min_refresh
                if not recently:  # a service that is down is asked again at most once per min_refresh, not on every token
                    try:
                        self._refresh_locked(now)
                    except Exception:
                        pass
                if self._fetched is None or now - self._fetched > self.max_stale:
                    raise AccountTokenError("jwks_unavailable")
                # otherwise: keep serving the last good set for a while
            self._expire_previous(now)
            return {"keys": list(self._current.values()) + [j for j, _ in self._previous.values()]}

    def refresh(self, now=None, force=False):
        """Fetch now. Returns True if the key set was replaced. Unless `force`, nothing is fetched if a fetch was tried less than
        min_refresh seconds ago."""
        now = self._now() if now is None else now
        with self._lock:
            if not force and self._attempted is not None and now - self._attempted < self.min_refresh:
                return False
            try:
                self._refresh_locked(now)
            except Exception:
                self._attempted = now
                return False
            return True

    def drop_previous(self):
        """Stop trusting every key the service has retired (use when one of them is known to be compromised)."""
        with self._lock:
            self._previous = {}

    # -- verification ------------------------------------------------------------------------------------------------------------------
    def verify(self, token, now=None, **kw):
        """verify_token against the cached keys; an unknown kid triggers one (rate-limited) refetch and a second look."""
        now = self._now() if now is None else now
        try:
            return verify_token(token, self.jwks(now), now=now, **kw)
        except AccountTokenError as e:
            if e.reason != "unknown_kid" or not self.refresh(now=now):
                raise
        return verify_token(token, self.jwks(now), now=now, **kw)


def https_fetcher(url, timeout=5, max_bytes=65536):
    """A `fetch` for JwksCache that reads the JWKS over HTTPS (plain http only for a loopback address, for local development).
    No redirects are followed to another scheme; the answer is capped in size. Only used when a host is configured with a service URL."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" and not (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1")):
        raise ValueError("the JWKS URL must be https")

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(_NoRedirect)

    def fetch():
        with opener.open(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=timeout) as r:
            raw = r.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("JWKS too large")
        return json.loads(raw.decode("utf-8"))

    return fetch


class AccountChecker:
    """What a host uses to check an account token: the service's public keys (fetched when first needed, kept by a JwksCache) and the issuer.
    `verify(token)` returns the claims or raises; nothing is trusted that the keys do not vouch for."""

    def __init__(self, service, fetch=None, now=time.time):
        self.service = service.rstrip("/")
        self._fetch = fetch or (lambda: https_fetcher(self.service + "/.well-known/jwks.json")())
        self._cache, self._now, self._lock = None, now, threading.Lock()

    def verify(self, token, audiences=None):
        """`audiences`: the audience strings this host answers to (a join proof is made for ONE host); None = an ordinary access token."""
        with self._lock:
            if self._cache is None: self._cache = JwksCache(self._fetch, now=self._now)
            cache = self._cache
        if not audiences: return cache.verify(token, now=self._now(), iss=self.service)
        last = AccountTokenError("bad_aud")
        for aud in audiences:
            try: return cache.verify(token, now=self._now(), iss=self.service, aud=aud)
            except AccountTokenError as e:
                if e.reason != "bad_aud": raise
                last = e
        raise last


# -- people and projects, by name -------------------------------------------------------------------------------------------------------------
ACCOUNT_ID_RE = re.compile(r"^acc_[A-Za-z0-9_-]{16}$")           # what the service makes: "acc_" and 16 URL-safe characters (96 random bits)
PROJECT_ID_RE = re.compile(r"^p_[0-9a-f]{12}$")


def clean_account_id(text):
    """An Orbit account id typed or pasted by a host -> the id, or ValueError. Surrounding spaces and a leading "orbit:" are tolerated; nothing else."""
    s = text.strip() if isinstance(text, str) else ""
    if s[:6].lower() == "orbit:": s = s[6:].strip()
    if not ACCOUNT_ID_RE.fullmatch(s): raise ValueError("that is not an Orbit account id (it looks like acc_ followed by 16 letters and digits)")
    return s


def relay_audience(service, pid):
    """The audience of a join proof for a project published through the Orbit service: that project's page on the service. A proof made for it is good for that one project."""
    if not isinstance(pid, str) or not PROJECT_ID_RE.fullmatch(pid): raise ValueError("not a project id")
    return f"orbit-join:{service.rstrip('/')}/r/{pid}"


class ProofLedger:
    """Join proofs are single use. A proof is a two-minute token; whoever sees one (a relay, a proxy log, a screen share) must not be able to use it a second time,
    so the host remembers each proof's `jti` until the proof would have expired anyway. `reserve` takes the proof (False if it was seen or the ledger is full),
    `release` gives it back when nothing was issued for it (the join failed), so an honest retry within its two minutes still works. In memory: a restart forgets,
    which leaves only the proof's own two-minute life."""

    def __init__(self, now=time.time, cap=20000, skew=30):
        self._now, self._cap, self._skew = now, cap, skew
        self._seen, self._lock = {}, threading.Lock()

    def reserve(self, jti, exp):
        if not isinstance(jti, str) or not 0 < len(jti) <= 200 or not _is_num(exp): return False
        now = self._now()
        with self._lock:
            if len(self._seen) >= self._cap:
                self._seen = {k: v for k, v in self._seen.items() if v + self._skew >= now}
                if len(self._seen) >= self._cap: return False        # full of live proofs: refuse rather than forget one
            if jti in self._seen and self._seen[jti] + self._skew >= now: return False
            self._seen[jti] = exp
            return True

    def release(self, jti):
        with self._lock: self._seen.pop(jti, None)
