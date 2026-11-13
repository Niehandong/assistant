"""模型凭据加解密（Fernet）与掩码提示。明文只在内存中短暂存在，不进日志、不进响应。"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings


class SecretDecryptError(Exception):
    """密文无法用当前 MODEL_SECRET_KEY 解密（密钥被更换或数据损坏）。"""


def _fernet(settings: Settings | None = None) -> Fernet:
    return Fernet((settings or get_settings()).MODEL_SECRET_KEY.encode())


def encrypt_secret(plain: str, settings: Settings | None = None) -> str:
    return _fernet(settings).encrypt(plain.encode()).decode()


def decrypt_secret(token: str, settings: Settings | None = None) -> str:
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretDecryptError("密钥无法解密") from exc


def make_key_hint(plain: str) -> str:
    """掩码展示，如 ``sk-****abcd``；过短的密钥只显示 ``****``，避免泄露。"""
    return f"{plain[:3]}****{plain[-4:]}" if len(plain) >= 12 else "****"
