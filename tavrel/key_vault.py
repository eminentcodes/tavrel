"""Encrypt generated agent keys; wallet secrets never reach HTTP responses."""
import base64
import ctypes
import os
from pathlib import Path
from threading import Lock

from cryptography.fernet import Fernet, InvalidToken
from .engine import PolicyError


def profile_protect(value, decrypt=False):
    """Windows DPAPI binds the vault key to the current Windows user profile."""
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    source = Blob(len(value), buffer)
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise PolicyError('wallet_vault_unavailable', 'This Windows account could not unlock the agent wallet vault.', 503)
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(output.data)


class KeyVault:
    def __init__(self, directory):
        self.path = Path(directory) / 'wallet-vault.key'
        self.lock = Lock()

    def cipher(self):
        supplied = os.environ.get('TAVREL_WALLET_VAULT_KEY')
        if supplied:
            try:
                return Fernet(supplied.encode('ascii'))
            except (ValueError, UnicodeEncodeError):
                raise PolicyError('wallet_vault_unavailable', 'TAVREL_WALLET_VAULT_KEY must be a valid Fernet key.', 503) from None
        if os.name != 'nt':
            raise PolicyError('wallet_vault_unavailable', 'Set TAVREL_WALLET_VAULT_KEY in the server environment before creating an agent wallet.', 503)
        with self.lock:
            if self.path.exists():
                key = profile_protect(self.path.read_bytes(), decrypt=True)
            else:
                key = Fernet.generate_key()
                self.path.parent.mkdir(parents=True, exist_ok=True)
                protected = profile_protect(key)
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'wb') as handle:
                    handle.write(protected)
        return Fernet(key)

    def encrypt(self, seed):
        return self.cipher().encrypt(seed).decode('ascii')

    def decrypt(self, value):
        try:
            return self.cipher().decrypt(value.encode('ascii'))
        except (InvalidToken, ValueError):
            raise PolicyError('wallet_vault_unavailable', 'The agent wallet vault could not be decrypted. Keep the original vault key and account profile.', 503) from None
