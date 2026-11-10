"""Smoke test with Blender's public Sintel trailer and isolated data."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SAMPLE = "https://download.blender.org/durian/trailer/sintel_trailer-480p.mp4"


def main():
    exe = Path(sys.argv[1]).resolve()
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        port = port_probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="vlweb-e2e-") as directory:
        root = Path(directory)
        env = dict(os.environ, VLWEB_DATA=directory, VLWEB_PORT=str(port))
        origin = f"http://127.0.0.1:{port}/api/v1"

        def request(path, method="GET", body=None, authenticated=True, headers=None):
            headers = dict(headers or {})
            if authenticated:
                headers["Authorization"] = "Bearer " + (root / "chave.txt").read_text().strip()
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(origin + path, data, headers, method=method)
            try:
                response = urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                payload = response.read()
                if response.headers.get_content_type() == "application/json":
                    payload = json.loads(payload)
                return response.status, response.headers, payload

        def start():
            process = subprocess.Popen([exe], env=env)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    if request("/info", authenticated=False)[0] == 200:
                        return process
                except urllib.error.URLError:
                    time.sleep(0.1)
            process.kill()
            process.wait()
            log = root / "erro-inicializacao.txt"
            raise RuntimeError(log.read_text(encoding="utf-8") if log.exists() else "Servidor não iniciou")

        def wait_for(job_id, expected, timeout=40):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                jobs = request("/jobs")[2]
                job = next(row for row in jobs if row["id"] == job_id)
                if job["status"] == expected:
                    return job
                if job["status"] == "failed":
                    raise AssertionError(job["error"])
                time.sleep(0.06)
            raise AssertionError(job)

        def add(quality):
            status, _, job = request("/jobs", "POST", {"url": SAMPLE, "quality": quality, "credit": "@João Vídeos"})
            assert status == 201, job
            return job["id"]

        process = start()
        try:
            assert request("/jobs", authenticated=False)[0] == 401
            assert request("/jobs", "POST", {"url": "http://2130706433/", "quality": "best"})[0] == 400
            assert request("/jobs", "POST", {"url": SAMPLE, "quality": "unknown"})[0] == 422
            key = (root / "chave.txt").read_text().strip()
            assert request("/session", "POST", {"key": key}, authenticated=False)[0] == 403
            assert request("/session", "POST", {"key": "invalid"}, authenticated=False, headers={"X-VideoLivre": "1"})[0] == 401
            status, headers, _ = request("/session", "POST", {"key": key}, authenticated=False, headers={"X-VideoLivre": "1"})
            assert status == 204
            cookie = headers["Set-Cookie"]
            assert all(attribute in cookie for attribute in ["HttpOnly", "Secure", "SameSite=Strict"])
            cookie = {"Cookie": cookie.split(";", 1)[0]}
            assert request("/jobs", authenticated=False, headers=cookie)[0] == 200
            assert request("/jobs", "DELETE", authenticated=False, headers=cookie)[0] == 403

            video = add("best")
            path = f"/jobs/{video}"
            wait_for(video, "running")
            assert request(path + "/cancel", "POST")[0] == 204
            wait_for(video, "cancelled")
            assert request(path + "/file")[0] == 404
            assert request(path + "/resume", "POST")[0] == 204
            job = wait_for(video, "completed")
            assert job["filename"].endswith(" [@João Vídeos].mp4"), job
            assert request(path + "/file", authenticated=False)[0] == 401
            status, headers, prefix = request(path + "/file", headers={"Range": "bytes=0-31"})
            assert status == 206 and len(prefix) == 32 and b"ftyp" in prefix
            assert urllib.parse.unquote(headers["Content-Disposition"]).endswith(job["filename"])

            audio = add("mp3")
            item = wait_for(audio, "completed")
            status, _, bytes_ = request(f"/jobs/{audio}/file")
            assert status == 200 and item["filename"].endswith(" [@João Vídeos].mp3")
            assert len(bytes_) > 10000
            subprocess.run([os.environ["VLWEB_FFMPEG"], "-v", "error", "-nostdin", "-i",
                            str(root / "downloads" / audio / item["filename"]), "-f", "null", "-"],
                           check=True)

            duplicate = add("best")
            assert wait_for(duplicate, "completed")["filename"] == job["filename"]
            assert (root / "downloads" / video / job["filename"]).is_file()
            assert (root / "downloads" / duplicate / job["filename"]).is_file()

            process.terminate()
            process.wait(timeout=10)
            process = start()
            assert request("/jobs", authenticated=False, headers=cookie)[0] == 401
            assert wait_for(video, "completed")["filename"] == job["filename"]
            assert request(path + "/file", headers={"Range": "bytes=0-31"})[2] == prefix
            assert request("/jobs", "DELETE")[0] == 204
            assert request("/jobs")[2] == []
            assert request(path + "/file")[0] == 404
            assert len(list((root / "downloads").glob("*/*"))) == 3
            print("Login, CSRF, fila, cancelamento, retomada, MP4, MP3, Range, colisão, reinício e histórico OK.")
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
