# -*- coding: utf-8 -*-
"""极简认证：PBKDF2 密码哈希 + 随机 token 会话。标准库实现，无额外依赖。"""
import hashlib
import os
import secrets
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import db

_security = HTTPBearer(auto_error=False)
TOKEN_TTL = 30 * 24 * 3600  # token 有效期 30 天


def hash_password(password: str, salt: str) -> str:
    """PBKDF2-HMAC-SHA256，20 万轮。"""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                               salt.encode("utf-8"), 200_000).hex()


def new_salt() -> str:
    return secrets.token_hex(16)


def create_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.create_session(token, user_id, int(time.time()) + TOKEN_TTL)
    return token


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(_security)):
    """FastAPI 依赖：从 Authorization: Bearer <token> 解析当前用户。"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    sess = db.get_session(credentials.credentials)
    if not sess or sess["expires_at"] < time.time():
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = db.get_user_by_id(sess["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user
