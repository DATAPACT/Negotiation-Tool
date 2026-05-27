import logging
from typing import Any, Dict, List, Optional

import jwt
import requests
from fastapi import HTTPException, status
from jwt import PyJWKClient

_JWKS_CLIENTS: dict[str, PyJWKClient] = {}


def get_jwks_client(jwks_url: str) -> PyJWKClient:
    client = _JWKS_CLIENTS.get(jwks_url)
    if client is None:
        client = PyJWKClient(jwks_url, cache_keys=True)
        _JWKS_CLIENTS[jwks_url] = client
    return client


def decode_keycloak_token(
    token: str,
    *,
    issuer: str,
    jwks_url: str,
    audience: Optional[str] = None,
    algorithms: Optional[List[str]] = None,
    logger: Optional[logging.Logger] = None,
    verify_aud: bool = True,
) -> Dict[str, Any]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not issuer:
        raise HTTPException(status_code=500, detail="KEYCLOAK_ISSUER is not configured")
    if not jwks_url:
        raise HTTPException(status_code=500, detail="KEYCLOAK_JWKS_URL is not configured")

    try:
        signing_key = get_jwks_client(jwks_url).get_signing_key_from_jwt(token)
        decode_kwargs: Dict[str, Any] = {
            "key": signing_key.key,
            "algorithms": algorithms or ["RS256"],
            "issuer": issuer.rstrip("/"),
        }
        if audience and verify_aud:
            decode_kwargs["audience"] = audience
        else:
            decode_kwargs["options"] = {"verify_aud": False}
        return jwt.decode(token, **decode_kwargs)
    except HTTPException:
        raise
    except Exception as exc:
        if logger:
            logger.error("Keycloak token verification failed: %s", exc)
        raise credentials_exception


def collect_keycloak_roles(claims: Dict[str, Any]) -> List[str]:
    roles = set()
    realm_access = claims.get("realm_access") or {}
    for role in realm_access.get("roles") or []:
        if role:
            roles.add(str(role))

    resource_access = claims.get("resource_access") or {}
    for client_access in resource_access.values():
        for role in (client_access or {}).get("roles") or []:
            if role:
                roles.add(str(role))

    return sorted(roles)


def collect_keycloak_groups(claims: Dict[str, Any]) -> List[str]:
    groups = claims.get("groups") or []
    if isinstance(groups, list):
        return sorted(str(group) for group in groups if group)
    return []


def merge_keycloak_userinfo(claims: Dict[str, Any], userinfo: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(claims)
    attributes = dict((claims.get("attributes") or {}))

    for key, value in userinfo.items():
        if key == "attributes" and isinstance(value, dict):
            attributes.update(value)
        elif value is not None:
            merged[key] = value

    if attributes:
        merged["attributes"] = attributes
    return merged


def enrich_keycloak_claims(
    token: str,
    claims: Dict[str, Any],
    *,
    issuer: str,
    logger: Optional[logging.Logger] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    if not issuer:
        return claims

    try:
        response = requests.get(
            f"{issuer.rstrip('/')}/protocol/openid-connect/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        response.raise_for_status()
        userinfo = response.json()
        if isinstance(userinfo, dict):
            return merge_keycloak_userinfo(claims, userinfo)
    except requests.RequestException as exc:
        if logger:
            logger.warning("Keycloak userinfo lookup failed: %s", exc)
    except ValueError as exc:
        if logger:
            logger.warning("Keycloak userinfo payload invalid: %s", exc)

    return claims


def decode_and_enrich_keycloak_claims(
    token: str,
    *,
    issuer: str,
    jwks_url: str,
    audience: Optional[str] = None,
    algorithms: Optional[List[str]] = None,
    logger: Optional[logging.Logger] = None,
    verify_aud: bool = True,
    timeout: int = 10,
) -> Dict[str, Any]:
    claims = decode_keycloak_token(
        token,
        issuer=issuer,
        jwks_url=jwks_url,
        audience=audience,
        algorithms=algorithms,
        logger=logger,
        verify_aud=verify_aud,
    )
    return enrich_keycloak_claims(
        token,
        claims,
        issuer=issuer,
        logger=logger,
        timeout=timeout,
    )
