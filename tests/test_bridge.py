import ssl

from halfreversal.bridge import websocket_ssl_context, websocket_url


def test_websocket_url_uses_secure_transport_for_https() -> None:
    assert (
        websocket_url("https://half-day-reversal-production.up.railway.app/")
        == "wss://half-day-reversal-production.up.railway.app/bridge/ws"
    )


def test_websocket_ssl_context_uses_a_trusted_ca_bundle() -> None:
    context = websocket_ssl_context("wss://example.com/bridge/ws")

    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()["x509_ca"] > 0


def test_plain_websocket_does_not_create_a_tls_context() -> None:
    assert websocket_ssl_context("ws://127.0.0.1:8000/bridge/ws") is None
