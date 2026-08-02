"""Small encrypted local credential vault.

The vault stores one encrypted JSON blob.  A deployment can provide
``SYMBIOT_VAULT_KEY`` from an OS secret store; local development falls back to
a mode-600 machine-local key file.  Provider metadata and run state never
contain the decrypted values.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from cryptography.fernet import Fernet, InvalidToken

try:
    import keyring as _os_keyring
except ImportError:  # The encrypted file vault remains the web fallback.
    _os_keyring = None


class VaultError(RuntimeError):
    pass


class LocalKeyVault:
    service_name = "io.symbiot.mission-control"

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        master_key: str | bytes | None = None,
        key_path: str | Path | None = None,
    ) -> None:
        config_dir = Path(os.getenv("SYMBIOT_CONFIG_DIR", Path.home() / ".symbiot"))
        self.path = Path(path or config_dir / "vault.enc")
        self.key_path = Path(key_path or config_dir / "vault.key")
        self._master_key = master_key

    def _fernet(self) -> Fernet:
        raw = self._master_key or os.getenv("SYMBIOT_VAULT_KEY")
        if raw is None:
            try:
                if self.key_path.exists():
                    raw = self.key_path.read_bytes().strip()
                else:
                    self.key_path.parent.mkdir(parents=True, exist_ok=True)
                    self.key_path.write_bytes(Fernet.generate_key())
                    os.chmod(self.key_path, 0o600)
                    raw = self.key_path.read_bytes().strip()
            except OSError as exc:
                raise VaultError("unable to initialize the local encrypted vault") from exc
        if isinstance(raw, str):
            raw = raw.encode()
        try:
            return Fernet(raw)
        except (ValueError, TypeError) as exc:
            raise VaultError("SYMBIOT_VAULT_KEY is not a valid vault key") from exc

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            encrypted = self.path.read_bytes()
            payload = self._fernet().decrypt(encrypted)
            data = json.loads(payload.decode("utf-8"))
        except (OSError, InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VaultError("unable to decrypt the local provider vault") from exc
        if not isinstance(data, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
            raise VaultError("local provider vault has an invalid format")
        return dict(data)

    def _write(self, data: Mapping[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self._fernet().encrypt(json.dumps(dict(data), sort_keys=True).encode("utf-8"))
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(encrypted)
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def get(self, provider: str) -> str | None:
        if _os_keyring is not None:
            try:
                os_value = _os_keyring.get_password(self.service_name, provider)
                if os_value:
                    return os_value
            except Exception:
                pass
        return self._read().get(provider)

    def set(self, provider: str, api_key: str) -> None:
        data = self._read()
        data[provider] = api_key
        self._write(data)

    def delete(self, provider: str) -> None:
        data = self._read()
        if provider in data:
            del data[provider]
            self._write(data)

    def has(self, provider: str) -> bool:
        return self.get(provider) is not None
