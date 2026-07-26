from app.ai.crypto import decrypt_api_key, encrypt_api_key, mask_api_key


def test_encrypt_decrypt_roundtrip():
    ciphertext = encrypt_api_key("sk-super-secret-key")
    assert ciphertext != "sk-super-secret-key"
    assert decrypt_api_key(ciphertext) == "sk-super-secret-key"


def test_mask_api_key_hides_the_middle():
    masked = mask_api_key("sk-abcdefgh1234")
    assert masked.startswith("sk-")
    assert masked.endswith("1234")
    assert "abcdefgh" not in masked


def test_mask_api_key_short_value_fully_masked():
    assert mask_api_key("ab") == "**"
