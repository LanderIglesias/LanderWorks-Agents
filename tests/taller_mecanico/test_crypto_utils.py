import sqlite3

import pytest
from cryptography.fernet import InvalidToken

from backend.agents.taller_mecanico import crypto_utils
from backend.agents.taller_mecanico import db as tm_db

# `crypto_env` (autouse) vive en conftest.py -- compartida con el resto de
# tests de taller_mecanico. Los tests de ausencia de clave la borran ellos
# mismos con monkeypatch.delenv, después de que la fixture ya la puso.


class TestEncryptDecrypt:
    def test_roundtrip_is_reversible(self):
        token = crypto_utils.encrypt("Ana García")
        assert crypto_utils.decrypt(token) == "Ana García"

    def test_encrypted_value_is_not_plaintext(self):
        token = crypto_utils.encrypt("600111222")
        assert "600111222" not in token

    def test_same_plaintext_encrypts_differently_each_time(self):
        # Fernet no es determinista (IV aleatorio) — a propósito, por eso
        # telefono_hash existe por separado para poder buscar por igualdad.
        token_a = crypto_utils.encrypt("600111222")
        token_b = crypto_utils.encrypt("600111222")
        assert token_a != token_b
        assert crypto_utils.decrypt(token_a) == crypto_utils.decrypt(token_b) == "600111222"

    def test_decrypt_rejects_tampered_token(self):
        token = crypto_utils.encrypt("600111222")
        tampered = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]
        with pytest.raises(InvalidToken):
            crypto_utils.decrypt(tampered)

    def test_decrypt_non_ascii_input_raises_invalid_token_not_unicode_error(self):
        with pytest.raises(InvalidToken):
            crypto_utils.decrypt("no-es-un-token-válido-ñ")

    def test_missing_fernet_key_raises_config_error(self, monkeypatch):
        monkeypatch.delenv("TALLER_MECANICO_FERNET_KEY", raising=False)
        with pytest.raises(crypto_utils.CryptoConfigError):
            crypto_utils.encrypt("x")

    def test_encrypt_and_decrypt_use_independent_key_from_hash(self, monkeypatch):
        # Cambiar la clave HMAC no debe afectar a un token Fernet ya emitido.
        token = crypto_utils.encrypt("600111222")
        monkeypatch.setenv("TALLER_MECANICO_HMAC_KEY", "otra-clave-distinta")
        assert crypto_utils.decrypt(token) == "600111222"


class TestHashForLookup:
    def test_deterministic_same_input_same_hash(self):
        h1 = crypto_utils.hash_for_lookup("600111222")
        h2 = crypto_utils.hash_for_lookup("600111222")
        assert h1 == h2

    def test_distinct_inputs_produce_distinct_hashes(self):
        h1 = crypto_utils.hash_for_lookup("600111222")
        h2 = crypto_utils.hash_for_lookup("600111223")
        assert h1 != h2

    def test_hash_is_not_the_plaintext(self):
        h = crypto_utils.hash_for_lookup("600111222")
        assert h != "600111222"
        assert "600111222" not in h

    def test_missing_hmac_key_raises_config_error(self, monkeypatch):
        monkeypatch.delenv("TALLER_MECANICO_HMAC_KEY", raising=False)
        with pytest.raises(crypto_utils.CryptoConfigError):
            crypto_utils.hash_for_lookup("600111222")

    def test_different_hmac_key_changes_the_hash(self, monkeypatch):
        h1 = crypto_utils.hash_for_lookup("600111222")
        monkeypatch.setenv("TALLER_MECANICO_HMAC_KEY", "otra-clave-completamente-distinta")
        h2 = crypto_utils.hash_for_lookup("600111222")
        assert h1 != h2


class TestUniqueEnforcementViaHash:
    """El UNIQUE real vive en telefono_hash (determinista), no en
    telefono_encrypted (Fernet, no determinista) — ver db.py."""

    @pytest.fixture
    def conn(self, tmp_path, monkeypatch):
        db_path = tmp_path / "taller_mecanico.db"
        monkeypatch.setattr(tm_db, "DB_PATH", db_path)
        connection = tm_db.get_conn()
        yield connection
        connection.close()

    def test_duplicate_phone_rejected_via_hash(self, conn):
        telefono = "600111222"
        conn.execute(
            "INSERT INTO clientes (nombre_encrypted, telefono_encrypted, telefono_hash) VALUES (?, ?, ?)",
            (
                crypto_utils.encrypt("Ana"),
                crypto_utils.encrypt(telefono),
                crypto_utils.hash_for_lookup(telefono),
            ),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO clientes (nombre_encrypted, telefono_encrypted, telefono_hash) VALUES (?, ?, ?)",
                (
                    crypto_utils.encrypt("Otra Ana"),
                    crypto_utils.encrypt(telefono),  # ciphertext distinto, mismo teléfono real
                    crypto_utils.hash_for_lookup(telefono),
                ),
            )

    def test_different_phones_both_accepted(self, conn):
        for nombre, telefono in [("Ana", "600111222"), ("Bea", "600111223")]:
            conn.execute(
                "INSERT INTO clientes (nombre_encrypted, telefono_encrypted, telefono_hash) VALUES (?, ?, ?)",
                (
                    crypto_utils.encrypt(nombre),
                    crypto_utils.encrypt(telefono),
                    crypto_utils.hash_for_lookup(telefono),
                ),
            )
            conn.commit()

        count = conn.execute("SELECT COUNT(*) AS n FROM clientes").fetchone()["n"]
        assert count == 2

    def test_stored_row_decrypts_back_to_original_pii(self, conn):
        conn.execute(
            "INSERT INTO clientes (nombre_encrypted, telefono_encrypted, telefono_hash, email_encrypted, direccion_encrypted) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                crypto_utils.encrypt("Ana García"),
                crypto_utils.encrypt("600111222"),
                crypto_utils.hash_for_lookup("600111222"),
                crypto_utils.encrypt("ana@example.com"),
                crypto_utils.encrypt("Calle Falsa 123"),
            ),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM clientes").fetchone()
        assert crypto_utils.decrypt(row["nombre_encrypted"]) == "Ana García"
        assert crypto_utils.decrypt(row["telefono_encrypted"]) == "600111222"
        assert crypto_utils.decrypt(row["email_encrypted"]) == "ana@example.com"
        assert crypto_utils.decrypt(row["direccion_encrypted"]) == "Calle Falsa 123"
