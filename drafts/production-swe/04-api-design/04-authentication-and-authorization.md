# 04 — Authentication and Authorization

## The Distinction That Matters

**Authentication** answers: *who is making this request?*
**Authorization** answers: *is this identity allowed to perform this action?*

These are separate concerns, solved by separate mechanisms, that frequently get conflated. An API can authenticate a request successfully (it knows who the caller is) and still reject it (the caller doesn't have permission). The HTTP status codes make this explicit: `401 Unauthorized` means authentication failed; `403 Forbidden` means authorization failed.

Both must be handled at the API boundary. Neither belongs in business logic.

---

## 1. API Key Authentication

API keys are the simplest authentication mechanism appropriate for service-to-service communication. They are opaque tokens — the server validates them against a store; the token itself carries no information.

**Use API keys when:**
- The client is a machine (another service, a script)
- Simple revocation is required (disable the key in the store)
- Fine-grained per-client rate limiting is needed

**Install:**
```bash
uv add slowapi  # rate limiting per API key
```

### Key Storage

API keys are secrets. Store them hashed:

```python
# src/feature_pipeline/domain/api_keys.py
import hashlib
import secrets
from dataclasses import dataclass

@dataclass(frozen=True)
class ApiKey:
    key_id: str      # public identifier (prefix of the key, shown to users)
    key_hash: str    # SHA-256 hash of the full key (stored in DB)
    name: str        # human-readable label
    scopes: frozenset[str]

def generate_api_key() -> tuple[str, str]:
    """Generate a new API key.

    Returns:
        A tuple of (full_key, key_id). The full_key is shown to the user once
        and never stored. The key_id is the prefix used for lookup.
    """
    raw = secrets.token_urlsafe(32)
    key_id = raw[:8]  # first 8 chars as public ID
    return raw, key_id

def hash_key(raw_key: str) -> str:
    """Hash an API key for storage. Use HMAC in production (Chapter 07)."""
    return hashlib.sha256(raw_key.encode()).hexdigest()
```

### FastAPI Dependency

```python
# src/feature_pipeline/api/deps.py
from typing import Annotated
from fastapi import Depends, Header, HTTPException, status
from feature_pipeline.domain.api_keys import ApiKey, hash_key
from feature_pipeline.infrastructure.key_repository import ApiKeyRepository
import structlog

logger = structlog.get_logger()

async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    key_repo: ApiKeyRepository = Depends(get_key_repository),
) -> ApiKey:
    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "MISSING_API_KEY", "message": "X-API-Key header is required."},
        )

    # Lookup by hash — never log the raw key
    key_hash = hash_key(x_api_key)
    api_key = await key_repo.get_by_hash(key_hash)

    if api_key is None:
        logger.warning("auth.invalid_api_key", key_prefix=x_api_key[:8])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_API_KEY", "message": "API key is invalid or revoked."},
        )

    return api_key

AuthedKey = Annotated[ApiKey, Depends(require_api_key)]
```

**Never log the full API key.** Log the prefix (`key_prefix=x_api_key[:8]`) to enable debugging without exposing the credential.

### Per-Key Rate Limiting

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

def get_key_identifier(request: Request) -> str:
    """Rate limit by API key, falling back to IP."""
    return request.headers.get("X-API-Key", get_remote_address(request))

limiter = Limiter(key_func=get_key_identifier)

@router.post("/features/")
@limiter.limit("100/minute")
async def create_feature(
    request: Request,  # required by slowapi
    body: FeatureCreateRequest,
    api_key: AuthedKey,
    service: FeatureServiceDep,
) -> FeatureResponse:
    ...
```

---

## 2. JWT Authentication

JWTs (JSON Web Tokens) are self-contained tokens: the server encodes claims (user ID, roles, expiry) into the token and signs it. Validation requires only the signing key — no database lookup per request.

**Use JWTs when:**
- The client is a user (human) or a system with a short-lived identity
- Stateless authentication is required (no session store)
- Claims (roles, permissions) need to travel with the token

**Install:**
```bash
uv add python-jose[cryptography]
# or the newer/faster alternative:
uv add python-jwt  # PyJWT
```

### JWT Structure

```
header.payload.signature

header:    {"alg": "HS256", "typ": "JWT"}
payload:   {"sub": "svc-model-serving", "iat": 1700000000, "exp": 1700003600,
             "scopes": ["features:read", "features:write"]}
signature: HMAC-SHA256(base64(header) + "." + base64(payload), secret)
```

The payload is Base64-encoded, not encrypted. Anyone can decode it. **Never put secrets in JWT payloads.**

### FastAPI Dependency

```python
# src/feature_pipeline/api/deps.py
from datetime import datetime, timezone
from typing import Annotated
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

security = HTTPBearer()

class TokenClaims(BaseModel):
    sub: str            # subject — who issued the token
    exp: int            # expiry timestamp
    scopes: list[str]   # permissions granted

def decode_token(token: str, secret: str, algorithm: str = "HS256") -> TokenClaims:
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        return TokenClaims(**payload)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": "JWT has expired."},
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": f"JWT is invalid: {exc}"},
        )

async def require_jwt(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    settings: SettingsDep,
) -> TokenClaims:
    return decode_token(credentials.credentials, settings.jwt_secret)

JWTClaims = Annotated[TokenClaims, Depends(require_jwt)]
```

### Secret Rotation

JWT secret rotation requires a dual-key period: both the old and new secrets are valid simultaneously until all outstanding tokens (issued with the old secret) have expired.

```python
def decode_token_with_rotation(
    token: str,
    current_secret: str,
    previous_secret: str | None,
    algorithm: str = "HS256",
) -> TokenClaims:
    """Try current secret first, fall back to previous during rotation."""
    secrets_to_try = [current_secret]
    if previous_secret:
        secrets_to_try.append(previous_secret)

    last_exc: Exception | None = None
    for secret in secrets_to_try:
        try:
            payload = jwt.decode(token, secret, algorithms=[algorithm])
            return TokenClaims(**payload)
        except InvalidTokenError as exc:
            last_exc = exc

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "INVALID_TOKEN", "message": str(last_exc)},
    )
```

Rotation procedure:
1. Generate new secret, set `JWT_SECRET_PREVIOUS = old_secret`, `JWT_SECRET = new_secret`
2. Deploy — both secrets are now accepted
3. Wait for the token TTL to expire (all old tokens expire)
4. Remove `JWT_SECRET_PREVIOUS`

---

## 3. OAuth2 Flows

OAuth2 is a framework for delegated authorization. It is the correct choice when a user (or system) is authorizing an application to act on their behalf.

### Password Flow (Internal Tools Only)

The OAuth2 password flow accepts username + password directly. **Never use this for public-facing APIs or third-party integrations.** It is appropriate only for internal tooling where the client and server are owned by the same organization.

```python
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/token")

@router.post("/auth/token")
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    settings: SettingsDep,
) -> dict[str, str]:
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid username or password."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(sub=user.id, scopes=user.scopes)
    return {"access_token": access_token, "token_type": "bearer"}
```

### Authorization Code Flow (User-Facing)

For user-facing applications where the end-user delegates access. The user is redirected to an identity provider (Google, Okta, Auth0) to authenticate; the application receives an authorization code it exchanges for a token.

FastAPI does not implement the full OAuth2 authorization server. Use an identity provider (Okta, Auth0, Google IAP, Keycloak) and validate their JWTs in FastAPI:

```python
from jwt import PyJWKClient

# Identity provider's JWKS endpoint — public keys for validation
JWKS_URL = "https://accounts.google.com/.well-known/openid-configuration"
jwks_client = PyJWKClient(JWKS_URL)

async def require_google_jwt(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    settings: SettingsDep,
) -> dict:
    signing_key = jwks_client.get_signing_key_from_jwt(credentials.credentials)
    payload = jwt.decode(
        credentials.credentials,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.google_client_id,
    )
    return payload
```

---

## 4. Role-Based Access Control (RBAC)

After authentication establishes *who* the caller is, authorization determines *what they can do*.

### Scope-Based Authorization

```python
# src/feature_pipeline/api/deps.py
from functools import partial

def require_scope(required_scope: str):
    """Dependency factory for scope-based authorization."""
    async def _check_scope(claims: JWTClaims) -> TokenClaims:
        if required_scope not in claims.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INSUFFICIENT_SCOPE",
                    "message": f"Scope '{required_scope}' is required.",
                },
            )
        return claims
    return Depends(_check_scope)

# Usage in routes:
@router.get("/features/")
async def list_features(
    claims: Annotated[TokenClaims, require_scope("features:read")],
    service: FeatureServiceDep,
) -> FeatureListResponse: ...

@router.post("/features/")
async def create_feature(
    claims: Annotated[TokenClaims, require_scope("features:write")],
    service: FeatureServiceDep,
    body: FeatureCreateRequest,
) -> FeatureResponse: ...

@router.delete("/features/{feature_id}")
async def delete_feature(
    feature_id: str,
    claims: Annotated[TokenClaims, require_scope("features:admin")],
    service: FeatureServiceDep,
) -> None: ...
```

### Resource-Level Authorization

Some operations require checking ownership or tenancy, not just scope:

```python
async def require_pipeline_access(
    pipeline_id: str,
    claims: JWTClaims,
    service: PipelineServiceDep,
) -> None:
    """Verify the caller has access to the specific pipeline."""
    pipeline = await service.get(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail={"code": "PIPELINE_NOT_FOUND"})

    if pipeline.owner_id != claims.sub and "pipelines:admin" not in claims.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PIPELINE_ACCESS_DENIED"},
        )
```

---

## 5. Security Anti-Patterns

These are unconditional. None have defensible exceptions.

### Never Store Passwords in Plaintext

```python
# Bad: comparing raw passwords
if user.password == form_data.password:  # never

# Good: use bcrypt or argon2
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)
```

### Never Log Auth Tokens

```python
# Bad: request logging middleware that logs all headers
logger.info("request", headers=dict(request.headers))  # leaks Authorization header

# Good: explicitly exclude sensitive headers
SENSITIVE_HEADERS = {"authorization", "x-api-key", "cookie"}
safe_headers = {
    k: v for k, v in request.headers.items()
    if k.lower() not in SENSITIVE_HEADERS
}
logger.info("request", headers=safe_headers)
```

### Never Return Stack Traces on 401/403

```python
# Bad: default FastAPI exception handler exposes internal paths
# fastapi.exceptions.HTTPException: 403

# Good: custom exception handler returns only a safe envelope
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.detail.get("code", "HTTP_ERROR") if isinstance(exc.detail, dict) else "HTTP_ERROR",
                "message": exc.detail.get("message", str(exc.detail)) if isinstance(exc.detail, dict) else str(exc.detail),
                "request_id": request.headers.get("X-Request-ID"),
            }
        },
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_exception", exc_info=exc)  # log internally
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "request_id": request.headers.get("X-Request-ID"),
            }
        },
    )
```

### Never Use the Same Secret for Multiple Purposes

```python
# Bad: one secret for everything
JWT_SECRET = "my-secret-key"
COOKIE_SECRET = JWT_SECRET  # reusing JWT secret for cookie signing

# Good: purpose-specific secrets
JWT_SECRET = settings.jwt_secret
COOKIE_SECRET = settings.cookie_secret
API_KEY_SALT = settings.api_key_salt
```

---

## Summary

| Mechanism | Use when |
|-----------|---------|
| API key | Service-to-service; simple revocation needed |
| JWT | User identity; stateless validation; scopes in token |
| OAuth2 password flow | Internal tools only; client and server in same trust boundary |
| OAuth2 authorization code | User-facing apps; third-party identity provider |

| Rule | Detail |
|------|--------|
| `401` vs `403` | `401` = not authenticated; `403` = authenticated but not authorized |
| Key storage | Hash with SHA-256 (minimum); HMAC with a salt (production) |
| Token logging | Never log full tokens; log key prefix only |
| Stack traces | Custom exception handlers; no implementation details in error responses |
| Secret reuse | One secret per purpose |
| Password storage | Argon2 or bcrypt; never plaintext, never MD5/SHA1 |

> **Authorization belongs at the boundary, not inside the domain.** Business logic should never check `if user.is_admin`: it should receive pre-authorized inputs and assume they are valid. The dependency layer is the authorization layer.
