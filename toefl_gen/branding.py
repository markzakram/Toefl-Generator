"""Logo dan font TOEFL Academy yang disematkan ke halaman HTML (website dan file tryout).

Semua aset ditanam sebagai base64, jadi halaman tidak memuat apa pun dari luar dan file tryout tetap utuh saat dibuka
tanpa internet. Daftar aset ada di `assets/README.md`.
"""

import base64
from pathlib import Path

ASSETS = Path(__file__).with_name("assets")
EMBEDDED = {
    "__LOGO__": ASSETS / "logo.png",
    "__LOGO_MARK__": ASSETS / "logo-mark.png",
    "__FONT_DISPLAY__": ASSETS / "fonts" / "manrope-latin.woff2",
    "__FONT_BODY__": ASSETS / "fonts" / "dm-sans-latin.woff2",
}


def embed_assets(html):
    """Isi placeholder aset yang dipakai halaman ini saja."""
    for placeholder, path in EMBEDDED.items():
        if placeholder in html:
            html = html.replace(placeholder, base64.b64encode(path.read_bytes()).decode("ascii"))
    return html
