"""Real Chromium UI check. Requires Playwright and installed Microsoft Edge."""
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

SAMPLE = "https://download.blender.org/durian/trailer/sintel_trailer-480p.mp4"
origin, key_file = sys.argv[1:]
key = Path(key_file).read_text().strip()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge")
    desktop = browser.new_page(viewport={"width": 1280, "height": 900})
    desktop.goto(origin)
    expect(desktop.get_by_role("heading", name="Entre no VideoLivre")).to_be_visible()
    expect(desktop.locator("#version")).to_have_text("v0.1.0")
    manifest = desktop.request.get(origin + "/manifest.webmanifest").json()
    assert manifest["display"] == "standalone"
    for icon in manifest["icons"]:
        assert desktop.request.get(origin + icon["src"]).headers["content-type"] == "image/png"

    phone = browser.new_page(**playwright.devices["Pixel 7"], accept_downloads=True)
    errors = []
    phone.on("pageerror", lambda error: errors.append(str(error)))
    phone.goto(origin)
    phone.get_by_label("Chave de acesso").fill(key)
    phone.get_by_role("button", name="Entrar", exact=True).click()
    expect(phone.get_by_role("heading", name="Novo download")).to_be_visible()
    expect(phone.get_by_text("A fila está vazia")).to_be_visible()
    assert phone.evaluate("document.documentElement.scrollWidth === innerWidth")
    phone.get_by_label("Link do vídeo").fill(SAMPLE)
    phone.get_by_label("Crédito").fill("@João Vídeos")
    phone.get_by_role("button", name="Adicionar à fila").click()
    expect(phone.get_by_label("Crédito")).to_have_value("")
    link = phone.get_by_role("link", name="Baixar arquivo")
    expect(link).to_be_visible(timeout=40000)
    with phone.expect_download() as file:
        link.click()
    assert file.value.suggested_filename.endswith(" [@João Vídeos].mp4")
    assert Path(file.value.path()).stat().st_size > 10000
    phone.get_by_role("button", name="Limpar histórico").click()
    phone.get_by_role("dialog").get_by_role("button", name="Limpar histórico").click()
    expect(phone.get_by_text("A fila está vazia")).to_be_visible()
    expect(phone.get_by_role("button", name="Limpar histórico")).to_be_disabled()
    phone.get_by_role("button", name="Sair").click()
    expect(phone.get_by_role("heading", name="Entre no VideoLivre")).to_be_visible()
    assert not errors, errors
    browser.close()
print("Edge em desktop e viewport móvel, login, fila, crédito, download, histórico e saída OK.")
