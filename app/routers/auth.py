import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db, set_tenant_org
from app.ids import generate_id
from app.models import ApiKey, LoginAttempt, Membership, Organization, User
from app.models import Session as UserSession
from app.services.auth import (
    ROLE_PERMISSIONS,
    VALID_API_KEY_SCOPES,
    dummy_verify_password,
    generate_api_key,
    generate_csrf_token,
    generate_session_token,
    has_permission,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_api_key_secret,
    verify_password,
)

router = APIRouter(prefix="/v1/auth", tags=["Authentication & Access"])


# ==============================================================================
# SCHEMAS
# ==============================================================================


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=12)
    org_name: Optional[str] = "Personal Workspace"
    signup_code: Optional[str] = None


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str


class CreateApiKeyRequest(BaseModel):
    name: Optional[str] = None
    environment_class: str = Field("test", pattern="^(test|live)$")
    scopes: List[str]


class Principal:
    """Represents the authenticated caller, either a user session or an API key."""

    def __init__(
        self,
        user_id: Optional[str],
        org_id: str,
        role: Optional[str] = None,
        api_key_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        env_class: str = "test",
        is_api_key: bool = False,
    ):
        self.user_id = user_id
        self.org_id = org_id
        self.role = role
        self.api_key_id = api_key_id
        self.scopes = scopes or []
        self.env_class = env_class
        self.is_api_key = is_api_key

    def has_scope(self, scope: str) -> bool:
        if not self.is_api_key:
            # User role checks
            if not self.role:
                return False
            return has_permission(self.role, scope)
        return scope in self.scopes

    def require_scope(self, scope: str) -> None:
        if not self.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: '{scope}'",
            )


def require_principal(required_scope: Optional[str] = None):
    """FastAPI dependency yielding an authenticated Principal with an enforced scope."""

    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if required_scope:
            principal.require_scope(required_scope)
        return principal

    return dependency


# ==============================================================================
# LOGIN THROTTLING & HELPERS
# ==============================================================================


def check_login_throttling(db: Session, email: str, ip_address: str) -> None:
    """Enforces 5 failures per (email, IP) per 15 minutes window."""
    window_start = datetime.now(timezone.utc) - timedelta(minutes=15)
    stmt = select(func.count(LoginAttempt.id)).where(
        LoginAttempt.email == email.lower(),
        LoginAttempt.ip_address == ip_address,
        LoginAttempt.success == False,
        LoginAttempt.attempted_at >= window_start,
    )
    failed_count = db.scalar(stmt) or 0
    if failed_count >= 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again in 15 minutes.",
            headers={"Retry-After": "900"},
        )


def record_login_attempt(db: Session, email: str, ip_address: str, success: bool) -> None:
    attempt = LoginAttempt(
        email=email.lower(),
        ip_address=ip_address,
        success=success,
        attempted_at=datetime.now(timezone.utc),
    )
    db.add(attempt)
    db.commit()


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


# ==============================================================================
# AUTH DEPENDENCIES
# ==============================================================================


def get_current_principal(
    request: Request,
    authorization: Optional[str] = Header(None),
    paylap_session: Optional[str] = Cookie(None),
    x_csrf_token: Optional[str] = Header(None),
    paylap_csrf: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> Principal:
    """
    Resolves request credentials into an authenticated Principal.
    Supports API Key (Bearer pl_...), Bearer Session, and Cookie Session with Double-Submit CSRF.
    """
    now = datetime.now(timezone.utc)

    # 1. Bearer Token Auth (API Key or Bearer Session Token) -> CSRF Exempt
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token.startswith("pl_test_") or token.startswith("pl_live_"):
            # API Key authentication
            parts = token.split("_")
            if len(parts) != 4:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key format")
            env_class = parts[1]
            lookup_id = parts[2]
            secret = parts[3]

            key_stmt = select(ApiKey).where(ApiKey.lookup_id == lookup_id, ApiKey.revoked_at.is_(None))
            api_key = db.scalar(key_stmt)
            if not api_key or not verify_api_key_secret(secret, api_key.secret_hash):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")

            # Update last used timestamp
            api_key.last_used_at = now
            db.commit()

            principal = Principal(
                user_id=api_key.created_by,
                org_id=api_key.org_id,
                api_key_id=api_key.id,
                scopes=api_key.scopes,
                env_class=api_key.environment_class,
                is_api_key=True,
            )
            set_tenant_org(db, principal.org_id)
            return principal
        else:
            # Bearer Session Token
            token_h = hash_token(token)
            sess_stmt = select(UserSession).where(UserSession.token_hash == token_h)
            sess = db.scalar(sess_stmt)
            if not sess or sess.expires_at < now or (now - sess.last_active_at) > timedelta(hours=24):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")

            sess.last_active_at = now
            db.commit()

            # Find default/first membership
            mem = db.scalar(
                select(Membership).where(Membership.user_id == sess.user_id).order_by(Membership.created_at)
            )
            org_id = mem.org_id if mem else ""
            role = mem.role if mem else "viewer"

            principal = Principal(
                user_id=sess.user_id,
                org_id=org_id,
                role=role,
                is_api_key=False,
            )
            if org_id:
                set_tenant_org(db, org_id)
            return principal

    # 2. Cookie-based Session Authentication
    if paylap_session:
        # Validate CSRF for unsafe methods
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not x_csrf_token or not paylap_csrf or x_csrf_token != paylap_csrf:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token validation failed")

        token_h = hash_token(paylap_session)
        c_sess_stmt = select(UserSession).where(UserSession.token_hash == token_h)
        sess = db.scalar(c_sess_stmt)
        if not sess or sess.expires_at < now or (now - sess.last_active_at) > timedelta(hours=24):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")

        sess.last_active_at = now
        db.commit()

        # Find default/first membership
        mem = db.scalar(select(Membership).where(Membership.user_id == sess.user_id).order_by(Membership.created_at))
        org_id = mem.org_id if mem else ""
        role = mem.role if mem else "viewer"

        principal = Principal(
            user_id=sess.user_id,
            org_id=org_id,
            role=role,
            is_api_key=False,
        )
        if org_id:
            set_tenant_org(db, org_id)
        return principal

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


# ==============================================================================
# AUTH ROUTES
# ==============================================================================


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    # 1. Signup mode validation
    if settings.PAYLAP_SIGNUP_MODE == "closed":
        if not payload.signup_code or payload.signup_code != settings.PAYLAP_SIGNUP_CODE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Signup is closed. Valid invite code required."
            )

    # 2. Password strength
    pwd_err = validate_password_strength(payload.password)
    if pwd_err:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=pwd_err)

    # 3. Check existing user
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    # 4. Create User, Organization and Owner Membership
    now = datetime.now(timezone.utc)
    user = User(
        id=generate_id("usr"),
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        created_at=now,
        updated_at=now,
    )
    db.add(user)

    org_slug = f"org-{payload.email.split('@')[0]}-{secrets.token_hex(4)}"
    org = Organization(
        id=generate_id("org"),
        name=payload.org_name or "Personal Workspace",
        slug=org_slug,
        live_enabled=False,
        arbiter_enabled=True,
        created_at=now,
        updated_at=now,
    )
    db.add(org)

    membership = Membership(
        id=generate_id("mem"),
        org_id=org.id,
        user_id=user.id,
        role="owner",
        created_at=now,
        updated_at=now,
    )
    db.add(membership)

    # 5. Create Session
    raw_session, session_hash = generate_session_token()
    user_session = UserSession(
        id=generate_id("ses"),
        user_id=user.id,
        token_hash=session_hash,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
        expires_at=now + timedelta(days=14),
        last_active_at=now,
        created_at=now,
    )
    db.add(user_session)
    db.commit()

    # Set Cookies
    csrf_token = generate_csrf_token()
    is_prod = settings.PAYLAP_ENV == "production"
    response.set_cookie("paylap_session", raw_session, httponly=True, samesite="lax", secure=is_prod, path="/")
    response.set_cookie("paylap_csrf", csrf_token, httponly=False, samesite="lax", secure=is_prod, path="/")

    return {
        "user": {"id": user.id, "email": user.email},
        "organization": {"id": org.id, "name": org.name, "slug": org.slug, "role": "owner"},
        "csrf_token": csrf_token,
    }


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    email = payload.email.lower()

    # Throttling check
    check_login_throttling(db, email, ip)

    user = db.scalar(select(User).where(User.email == email))
    if not user:
        # Constant-time dummy check to prevent user enumeration
        dummy_verify_password(payload.password)
        record_login_attempt(db, email, ip, success=False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    is_valid, needs_rehash = verify_password(payload.password, user.password_hash)
    if not is_valid:
        record_login_attempt(db, email, ip, success=False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Rehash password if parameters upgraded
    if needs_rehash:
        user.password_hash = hash_password(payload.password)

    record_login_attempt(db, email, ip, success=True)

    # Create Session
    now = datetime.now(timezone.utc)
    raw_session, session_hash = generate_session_token()
    user_session = UserSession(
        id=generate_id("ses"),
        user_id=user.id,
        token_hash=session_hash,
        ip_address=ip,
        user_agent=request.headers.get("User-Agent"),
        expires_at=now + timedelta(days=14),
        last_active_at=now,
        created_at=now,
    )
    db.add(user_session)
    db.commit()

    csrf_token = generate_csrf_token()
    is_prod = settings.PAYLAP_ENV == "production"
    response.set_cookie("paylap_session", raw_session, httponly=True, samesite="lax", secure=is_prod, path="/")
    response.set_cookie("paylap_csrf", csrf_token, httponly=False, samesite="lax", secure=is_prod, path="/")

    # Get active organization
    mem = db.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at))
    org_data = None
    if mem:
        org = db.scalar(select(Organization).where(Organization.id == mem.org_id))
        if org:
            org_data = {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "role": mem.role,
                "live_enabled": org.live_enabled,
            }

    return {
        "user": {"id": user.id, "email": user.email},
        "organization": org_data,
        "csrf_token": csrf_token,
    }


@router.post("/logout")
def logout(response: Response, paylap_session: Optional[str] = Cookie(None), db: Session = Depends(get_db)):
    if paylap_session:
        token_h = hash_token(paylap_session)
        sess = db.scalar(select(UserSession).where(UserSession.token_hash == token_h))
        if sess:
            db.delete(sess)
            db.commit()

    response.delete_cookie("paylap_session", path="/")
    response.delete_cookie("paylap_csrf", path="/")
    return {"status": "logged_out"}


@router.get("/me")
def get_me(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    if principal.is_api_key:
        return {
            "type": "api_key",
            "key_id": principal.api_key_id,
            "org_id": principal.org_id,
            "scopes": principal.scopes,
            "environment_class": principal.env_class,
        }

    user = db.scalar(select(User).where(User.id == principal.user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    org_list = []
    for m in memberships:
        org = db.scalar(select(Organization).where(Organization.id == m.org_id))
        if org:
            org_list.append(
                {
                    "org_id": org.id,
                    "name": org.name,
                    "slug": org.slug,
                    "role": m.role,
                    "live_enabled": org.live_enabled,
                    "arbiter_enabled": org.arbiter_enabled,
                }
            )

    return {
        "type": "user",
        "user": {"id": user.id, "email": user.email},
        "active_org_id": principal.org_id,
        "active_role": principal.role,
        "permissions": list(ROLE_PERMISSIONS.get(principal.role or "viewer", set())),
        "organizations": org_list,
    }


# ==============================================================================
# API KEYS MANAGEMENT
# ==============================================================================


@router.post("/keys", status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: CreateApiKeyRequest,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    # Developer can create own keys; Admin/Owner can create keys
    if not principal.is_api_key:
        if principal.role not in ("developer", "admin", "owner"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role to create API keys")
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API keys cannot create other API keys")

    # Validate scopes
    for s in payload.scopes:
        if s not in VALID_API_KEY_SCOPES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid scope: '{s}'")

    # If creating a live key, check that org has live_enabled
    org = db.scalar(select(Organization).where(Organization.id == principal.org_id))
    if payload.environment_class == "live" and (not org or not org.live_enabled):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Live API keys can only be created for organizations with live_enabled=true",
        )

    full_key, lookup_id, secret_hash, prefix, last4 = generate_api_key(payload.environment_class)

    key_record = ApiKey(
        id=generate_id("key"),
        org_id=principal.org_id,
        lookup_id=lookup_id,
        secret_hash=secret_hash,
        prefix=prefix,
        last4=last4,
        scopes=payload.scopes,
        environment_class=payload.environment_class,
        created_by=principal.user_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(key_record)
    db.commit()

    # The full_key is displayed ONCE
    return {
        "id": key_record.id,
        "key": full_key,
        "prefix": prefix,
        "last4": last4,
        "scopes": key_record.scopes,
        "environment_class": key_record.environment_class,
        "created_at": key_record.created_at,
    }


@router.get("/keys")
def list_api_keys(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    stmt = select(ApiKey).where(ApiKey.org_id == principal.org_id, ApiKey.revoked_at.is_(None))
    # Developer sees only own keys; Admin/Owner sees all
    if not principal.is_api_key and principal.role == "developer":
        stmt = stmt.where(ApiKey.created_by == principal.user_id)

    keys = db.scalars(stmt).all()
    return [
        {
            "id": k.id,
            "prefix": k.prefix,
            "last4": k.last4,
            "scopes": k.scopes,
            "environment_class": k.environment_class,
            "created_by": k.created_by,
            "created_at": k.created_at,
            "last_used_at": k.last_used_at,
        }
        for k in keys
    ]


@router.delete("/keys/{key_id}")
def revoke_api_key(
    key_id: str,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    key_record = db.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == principal.org_id))
    if not key_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    # Developer can only revoke own keys; Admin/Owner can revoke any
    if not principal.is_api_key and principal.role == "developer":
        if key_record.created_by != principal.user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot revoke another user's API key")

    key_record.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "revoked", "id": key_id}
