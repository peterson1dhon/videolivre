import io
import socket
import sys
import unittest
import urllib.request
from email.message import Message
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker import PublicRequest, network_boundary, public_ip, select_formats


class WorkerTests(unittest.TestCase):
    def test_public_ip_boundary(self):
        for address in ("127.0.0.1", "169.254.169.254", "10.1.2.3", "192.168.1.1",
                        "100.100.100.100", "192.88.99.1", "224.1.2.3", "::1", "fd00::1",
                        "::ffff:8.8.8.8", "64:ff9b::7f00:1", "2002:7f00:1::1", "fe80::1%2"):
            self.assertFalse(public_ip(address), address)
        self.assertTrue(public_ip("8.8.8.8"))
        self.assertTrue(public_ip("2606:4700:4700::1111"))

    def test_transport_resolves_and_checks_address_at_connect(self):
        local = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
        with patch.object(socket, "getaddrinfo", return_value=local):
            with self.assertRaisesRegex(PermissionError, "VL_DESTINO_BLOQUEADO"):
                socket.create_connection(("dominio-publico.example", 80), timeout=1)

    def test_redirect_rechecks_request(self):
        class FakeInitialResponse(urllib.request.BaseHandler):
            handler_order = 100

            def http_open(self, request):
                if request.host == "origem.example":
                    headers = Message()
                    headers["Location"] = "http://127.0.0.1/segredo"
                    return self.parent.error("http", request, io.BytesIO(), 302, "Found", headers)
                raise AssertionError("O destino interno chegou ao transporte")

        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), PublicRequest(), FakeInitialResponse())
        with self.assertRaisesRegex(PermissionError, "VL_DESTINO_BLOQUEADO"):
            opener.open("http://origem.example/")

    def test_quality_filters_and_never_selects_external_downloaders_or_drm(self):
        a = {"protocol": "https", "ext": "m4a", "vcodec": "none", "acodec": "aac"}
        v = {"protocol": "https", "ext": "mp4", "vcodec": "h264", "acodec": "none", "height": 720}
        denied = [dict(v, protocol="rtmp", height=480), dict(v, has_drm=True, height=480)]
        context = {"formats": [a, v, *denied]}
        self.assertEqual(list(select_formats(context, "480")), [])
        self.assertEqual([f["format_id"] for f in select_formats(context, "720")], ["video", "audio"])
        self.assertEqual([f["format_id"] for f in select_formats(context, "mp3")], ["source"])


if __name__ == "__main__":
    sys.addaudithook(network_boundary)
    unittest.main()
