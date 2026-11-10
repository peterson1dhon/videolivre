"""Isolated entry point for the pinned yt-dlp, invoked with Python -I."""
import ipaddress
import json
import re
import socket
import sys
import time
from pathlib import Path
from urllib.request import BaseHandler
from urllib.parse import unquote, urlsplit

if __name__ == "__main__" and sys.flags.no_site:
    sys.path.append(sys.argv.pop())

from yt_dlp import YoutubeDL
from yt_dlp.networking._urllib import UrllibRH
from yt_dlp.plugins import directories as plugin_directories
from yt_dlp.postprocessor.common import PostProcessor


V6_GLOBAL = ipaddress.ip_network("2000::/3")
V4_SPECIAL = tuple(map(ipaddress.ip_network, ("192.0.0.0/24", "192.88.99.0/24")))
V6_SPECIAL = tuple(map(ipaddress.ip_network, ("2001::/23", "2001:db8::/32", "2002::/16", "3fff::/20")))
PROTOCOLS = {"http", "https", "m3u8_native", "http_dash_segments"}
EXTENSIONS = {"mp4", "m4a", "mov", "webm", "mkv", "mp3", "aac", "ts", "ogg", "opus", "flv"}


def public_ip(raw):
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if not addr.is_global or addr.is_multicast or "%" in raw:
        return False
    if addr.version == 4:
        return not any(addr in block for block in V4_SPECIAL)
    return addr in V6_GLOBAL and not any(addr in block for block in V6_SPECIAL)


def network_boundary(event, args):
    if event == "socket.connect":
        sock, target = args
        if (sock.family in (socket.AF_INET, socket.AF_INET6)
                and sock.type == socket.SOCK_STREAM and isinstance(target, tuple)
                and target[1] in (80, 443) and public_ip(target[0])
                and (len(target) == 2 or target[3] == 0)):
            return
        raise PermissionError("VL_DESTINO_BLOQUEADO")
    if event in {"socket.sendto", "socket.sendmsg", "socket.bind", "subprocess.Popen",
                 "os.system", "os.startfile", "os.startfile/2", "os.exec", "os.posix_spawn",
                 "os.spawn", "os.fork", "ctypes.dlopen", "ctypes.dlsym"}:
        raise PermissionError("VL_OPERACAO_BLOQUEADA")


class HttpOnlyRH(UrllibRH):
    _SUPPORTED_URL_SCHEMES = ("http", "https")

    def _create_instance(self, **kwargs):
        opener = super()._create_instance(**kwargs)
        opener.add_handler(PublicRequest())
        return opener


class PublicRequest(BaseHandler):
    # Request processors also run on the new request created by RedirectHandler.
    def http_request(self, request):
        try:
            url = urlsplit(request.full_url)
            host = (url.hostname or "").rstrip(".")
            port = url.port
            ip_literal = ":" in host or host.replace(".", "").isdigit()
            public_host = public_ip(host) if ip_literal else (
                "." in host and not host.endswith(
                    (".localhost", ".local", ".internal", ".test", ".invalid", ".home.arpa")))
            if (url.scheme in {"http", "https"} and public_host
                    and url.username is None and url.password is None and port in {None, 80, 443}):
                return request
        except ValueError:
            pass
        raise PermissionError("VL_DESTINO_BLOQUEADO")

    https_request = ftp_request = file_request = data_request = http_request


class Downloader(YoutubeDL):
    def build_request_director(self, handlers, preferences=None):
        return super().build_request_director([HttpOnlyRH])

    def process_ie_result(self, ie_result, download=True, extra_info=None):
        if ie_result.get("_type") in {"playlist", "multi_video"}:
            raise ValueError("VL_PLAYLIST")
        return super().process_ie_result(ie_result, download, extra_info or {})


class Output:
    def __init__(self):
        self.error_text = ""

    def debug(self, _message):
        pass

    def warning(self, _message):
        pass

    def error(self, message):
        self.error_text = message


def emit(kind, **values):
    print(json.dumps({"kind": kind, **values}, ensure_ascii=True), flush=True)


def creator(info):
    for key in ("uploader_id", "channel_id"):
        value = info.get(key)
        if isinstance(value, str) and value.startswith("@"):
            return value
    for key in ("uploader_url", "channel_url"):
        value = info.get(key)
        if isinstance(value, str):
            for segment in urlsplit(value).path.split("/"):
                handle = unquote(segment)
                if re.fullmatch(r"@[\w.-]{1,80}", handle):
                    return handle
    value = info.get("uploader_id")
    if (info.get("extractor_key") in {"TikTok", "Instagram", "Vimeo", "Twitter"}
            and isinstance(value, str) and re.fullmatch(r"[\w.-]{1,80}", value)
            and not value.isdecimal()):
        return value
    return None


class Metadata(PostProcessor):
    def run(self, info):
        emit("metadata", title=(info.get("title") or "")[:240],
             creator=(creator(info) or "")[:81], site_id=str(info.get("id") or "")[:240])
        return [], info


def select_formats(context, quality):
    formats = [f for f in context["formats"] if f.get("protocol") in PROTOCOLS
               and f.get("ext") in EXTENSIONS and not f.get("has_drm")]
    audio = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") != "none"]
    combined = [f for f in formats if f.get("vcodec") != "none" and f.get("acodec") != "none"]
    if quality == "mp3":
        choices = audio or combined
        if choices:
            yield dict(choices[-1], format_id="source")
        return
    for video in reversed(formats):
        if video.get("vcodec") == "none":
            continue
        if quality != "best" and not 0 < (video.get("height") or 0) <= int(quality):
            continue
        if video.get("acodec") != "none":
            yield dict(video, format_id="source")
            return
        if audio:
            yield dict(video, format_id="video")
            yield dict(audio[-1], format_id="audio")
            return


def download(url, quality, max_bytes):
    # Register before loading an extractor. urllib opens the checked numeric address
    # itself, so neither a redirect nor a second DNS lookup can change that address.
    sys.addaudithook(network_boundary)
    plugin_directories.value = []
    logger = Output()
    last = 0.0

    def progress(data):
        nonlocal last
        current = data.get("downloaded_bytes") or 0
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        if current >= max_bytes or (total and total >= max_bytes):
            raise ValueError("VL_TAMANHO")
        now = time.monotonic()
        if now - last >= 0.5:
            last = now
            percent = min(99, int(current * 100 / total)) if total else None
            emit("progress", percent=percent)

    params = {
        "quiet": True, "no_warnings": True, "noprogress": True, "logger": logger,
        "proxy": "", "socket_timeout": 15, "retries": 2, "fragment_retries": 2,
        "continuedl": True, "overwrites": False, "noplaylist": True, "playlistend": 1,
        "external_downloader": {"default": "native"}, "hls_prefer_native": True,
        "enable_file_urls": False, "js_runtimes": {}, "remote_components": set(),
        "cachedir": False, "compat_opts": set(), "ffmpeg_location": str(Path.cwd() / "disabled-ffmpeg"),
        "max_filesize": max_bytes, "ratelimit": 16 * 1024 * 1024, "concurrent_fragment_downloads": 1,
        "outtmpl": {"default": "media.%(format_id)s.%(ext)s"},
        "format": lambda context: select_formats(context, quality),
        "match_filter": lambda info, *, incomplete: (
            "VL_FORMATO" if info.get("is_live") or info.get("live_status") == "is_upcoming" else None),
        "progress_hooks": [progress],
    }
    try:
        with Downloader(params) as ydl:
            ydl.add_post_processor(Metadata(ydl), when="before_dl")
            info = ydl.extract_info(url, download=True)
            if not info or info.get("_type") in {"playlist", "multi_video"}:
                emit("error", code="playlist")
                return 1
            paths = [str(item.get("filepath") or "") for item in info.get("requested_downloads", [])]
            if not paths or any(not path or not Path(path).is_file() for path in paths):
                emit("error", code="size" if paths else "format")
                return 1
            emit("done", paths=paths)
            return 0
    except Exception as error:
        message = f"{error} {logger.error_text}".lower()
        code = "extractor"
        for needles, label in (
            (("vl_destino_bloqueado",), "destination"),
            (("vl_tamanho", "larger than max-filesize"), "size"),
            (("vl_playlist",), "playlist"),
            (("drm",), "drm"),
            (("vl_formato", "requested format", "no video formats"), "format"),
            (("unsupported url",), "unsupported"),
            (("sign in", "login", "403", "429", "forbidden"), "restricted"),
            (("timed out", "getaddrinfo", "connection"), "network"),
        ):
            if any(needle in message for needle in needles):
                code = label
                break
        emit("error", code=code)
        return 1


if __name__ == "__main__":
    raise SystemExit(download(sys.argv[1], sys.argv[2], int(sys.argv[3])))
