"""DOCX → PDF(LibreOffice) → PNG(pdftoppm). 글꼴 별칭은 render/fonts.conf (박스 전용)."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

FONTS_CONF = Path(__file__).resolve().parent.parent / "render" / "fonts.conf"


def docx_to_pdf(docx: Path, outdir: Path) -> Path:
    env = dict(os.environ)
    if FONTS_CONF.exists():
        env["FONTCONFIG_FILE"] = str(FONTS_CONF)
    profile = tempfile.mkdtemp(prefix="lo-nomu-")
    try:
        subprocess.run(["soffice", f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf",
                        "--outdir", str(outdir), str(docx)], check=True, capture_output=True, timeout=180, env=env)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    return outdir / (docx.stem + ".pdf")


def pdf_to_png(pdf: Path, dpi=110) -> list:
    prefix = pdf.with_suffix("")
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(prefix)], check=True, capture_output=True, timeout=120)
    return sorted(pdf.parent.glob(prefix.name + "-*.png"))


def pdf_fonts(pdf: Path) -> str:
    r = subprocess.run(["pdffonts", str(pdf)], capture_output=True, text=True)
    return r.stdout
