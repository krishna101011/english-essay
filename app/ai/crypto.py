from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import ENCRYPTION_KEY


@lru_cache
def _fernet() -> Fernet:
    if not ENCRYPTION_KEY:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(ENCRYPTION_KEY.encode())


def encrypt_api_key(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def mask_api_key(plaintext: str) -> str:
    if len(plaintext) <= 4:
        return "*" * len(plaintext)
    return f"{plaintext[:3]}...{plaintext[-4:]}"
