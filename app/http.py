"""Общий SSL-контекст: системные сертификаты + сертификат Минцифры (нужен для API MAX)."""
import ssl

import certifi

from .config import CA_BUNDLE


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    if CA_BUNDLE.exists():
        ctx.load_verify_locations(CA_BUNDLE)
    return ctx
