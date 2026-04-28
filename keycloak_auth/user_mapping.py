from datetime import datetime
from typing import Any, Dict, Optional
import logging


def build_full_name(first_name: Optional[str], last_name: Optional[str]) -> Optional[str]:
    parts = [part.strip() for part in [first_name or "", last_name or ""] if part and part.strip()]
    return " ".join(parts) or None


def guess_user_type_from_claims(claims: Dict[str, Any]) -> str:
    email = (claims.get("email") or claims.get("preferred_username") or "").lower()
    preferred_username = (claims.get("preferred_username") or "").lower()
    role_values = []
    realm_access = claims.get("realm_access") or {}
    role_values.extend(str(role).lower() for role in (realm_access.get("roles") or []))
    resource_access = claims.get("resource_access") or {}
    for client_access in resource_access.values():
        role_values.extend(str(role).lower() for role in ((client_access or {}).get("roles") or []))

    if "provider" in role_values or "provider" in email or "provider" in preferred_username:
        return "provider"
    return "consumer"


def _claim_attribute_value(claims: Dict[str, Any], *keys: str) -> Optional[Any]:
    attributes = claims.get("attributes") or {}
    value = None
    for key in keys:
        value = claims.get(key)
        if value is None:
            value = attributes.get(key)
        if value is not None:
            break
    if isinstance(value, list):
        if len(value) == 1:
            return value[0]
        return value
    return value


def _clean_optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _normalize_organization_claim(value: Any) -> Optional[Any]:
    if value is None:
        return None
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned or None
    cleaned = str(value).strip()
    return [cleaned] if cleaned else None


def _build_placeholder_user(claims: Dict[str, Any]) -> Dict[str, Any]:
    keycloak_sub = claims["sub"]
    email = claims.get("email") or claims.get("preferred_username") or f"{keycloak_sub}@missing.local"
    username = (claims.get("preferred_username") or "").strip() or email
    first_name = (claims.get("given_name") or "").strip() or "miss value"
    last_name = (claims.get("family_name") or "").strip() or "miss value"


    display_name = build_full_name(first_name, last_name) or claims.get("name") or email or "miss value"
    user_type = _clean_optional_string(_claim_attribute_value(claims, "user_type", "type")) or guess_user_type_from_claims(claims)
    organization = _normalize_organization_claim(_claim_attribute_value(claims, "organization")) or ["miss value"]
    incorporation = _clean_optional_string(_claim_attribute_value(claims, "incorporation")) or "miss value"
    address = _clean_optional_string(_claim_attribute_value(claims, "address")) or "miss value"
    vat_no = _clean_optional_string(_claim_attribute_value(claims, "VAT_No")) or "miss value"
    position_title = _clean_optional_string(_claim_attribute_value(claims, "positionTitle", "PositionTitle")) or "miss value"
    phone = _clean_optional_string(_claim_attribute_value(claims, "phone")) or "miss value"
    return {
        "keycloak_sub": keycloak_sub,
        "first_name": first_name,
        "last_name": last_name,
        "name": display_name,
        "username": username,
        "type": user_type,
        "username_email": email,
        "password": None,
        "organization": organization,
        "incorporation": incorporation,
        "address": address,
        "vat_no": vat_no,
        "position_title": position_title,
        "phone": phone,
    }


def _build_update_fields(user: Dict[str, Any], claims: Dict[str, Any]) -> Dict[str, Any]:
    update_fields: Dict[str, Any] = {}
    keycloak_sub = claims["sub"]
    email = claims.get("email") or claims.get("preferred_username")
    username = (claims.get("preferred_username") or "").strip() or None
    first_name = (claims.get("given_name") or user.get("first_name") or "").strip() or None
    last_name = (claims.get("family_name") or user.get("last_name") or "").strip() or None
    display_name = build_full_name(first_name, last_name) or claims.get("name") or claims.get("preferred_username")
    user_type = _clean_optional_string(_claim_attribute_value(claims, "user_type", "type")) or guess_user_type_from_claims(claims)
    organization = _normalize_organization_claim(_claim_attribute_value(claims, "organization"))
    incorporation = _clean_optional_string(_claim_attribute_value(claims, "incorporation"))
    address = _clean_optional_string(_claim_attribute_value(claims, "address"))
    vat_no = _clean_optional_string(_claim_attribute_value(claims, "VAT_No"))
    position_title = _clean_optional_string(_claim_attribute_value(claims, "positionTitle", "PositionTitle"))
    phone = _clean_optional_string(_claim_attribute_value(claims, "phone"))

    if user.get("keycloak_sub") != keycloak_sub:
        update_fields["keycloak_sub"] = keycloak_sub
    if email and user.get("username_email") != email:
        update_fields["username_email"] = email
    if username and user.get("username") != username:
        update_fields["username"] = username
    if first_name and user.get("first_name") != first_name:
        update_fields["first_name"] = first_name
    if last_name and user.get("last_name") != last_name:
        update_fields["last_name"] = last_name
    if display_name and user.get("name") != display_name:
        update_fields["name"] = display_name
    if user_type and user.get("type") != user_type:
        update_fields["type"] = user_type
    if organization and user.get("organization") != organization:
        update_fields["organization"] = organization
    if incorporation and user.get("incorporation") != incorporation:
        update_fields["incorporation"] = incorporation
    if address and user.get("address") != address:
        update_fields["address"] = address
    if vat_no and user.get("vat_no") != vat_no:
        update_fields["vat_no"] = vat_no
    if position_title and user.get("position_title") != position_title:
        update_fields["position_title"] = position_title
    if phone and user.get("phone") != phone:
        update_fields["phone"] = phone
    return update_fields


def resolve_or_create_local_user_sync(
    users_collection,
    claims: Dict[str, Any],
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:

    keycloak_sub = claims.get("sub")
    if not keycloak_sub:
        raise ValueError("Keycloak token missing subject")

    email = claims.get("email") or claims.get("preferred_username")
    username = (claims.get("preferred_username") or "").strip() or None
    if not email:
        raise ValueError("Keycloak token missing email")

    user = users_collection.find_one({"keycloak_sub": keycloak_sub})
    if user is None:
        user = users_collection.find_one({"username_email": email})
    if user is None and username:
        user = users_collection.find_one({"username": username})

    if user is None:
        placeholder_user = _build_placeholder_user(claims)
        if logger:
            logger.warning(
                "Keycloak user %s (%s) is not registered in MongoDB. Creating placeholder local user so access can continue.",
                keycloak_sub,
                email,
            )
        insert_result = users_collection.insert_one(placeholder_user)
        user = users_collection.find_one({"_id": insert_result.inserted_id})

    update_fields = _build_update_fields(user, claims)
    if update_fields:
        users_collection.update_one({"_id": user["_id"]}, {"$set": update_fields})
        user.update(update_fields)
    return user


async def resolve_or_create_local_user_async(
    users_collection,
    claims: Dict[str, Any],
    logger: Optional[logging.Logger] = None,
    *,
    include_audit_fields: bool = False,
) -> Dict[str, Any]:
    keycloak_sub = claims.get("sub")
    if not keycloak_sub:
        raise ValueError("Keycloak token missing subject")

    email = claims.get("email") or claims.get("preferred_username")
    username = (claims.get("preferred_username") or "").strip() or None
    if not email:
        raise ValueError("Keycloak token missing email")

    user = await users_collection.find_one({"keycloak_sub": keycloak_sub})
    if user is None:
        user = await users_collection.find_one({"username_email": email})
    if user is None and username:
        user = await users_collection.find_one({"username": username})

    now = datetime.utcnow()

    if user is None:
        placeholder_user = _build_placeholder_user(claims)
        if include_audit_fields:
            placeholder_user.update({
                "created_at": now,
                "updated_at": now,
                "last_login_at": now,
            })
        if logger:
            logger.warning(
                "Keycloak user %s (%s) is not registered in MongoDB. Creating placeholder local user so access can continue.",
                keycloak_sub,
                email,
            )
        insert_result = await users_collection.insert_one(placeholder_user)
        user = await users_collection.find_one({"_id": insert_result.inserted_id})

    update_fields = _build_update_fields(user, claims)
    if include_audit_fields:
        update_fields["updated_at"] = now
        update_fields["last_login_at"] = now
    if update_fields:
        await users_collection.update_one({"_id": user["_id"]}, {"$set": update_fields})
        user.update(update_fields)
    return user
