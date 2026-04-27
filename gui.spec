# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the PD-72 GUI.
#
# Build with:  pyinstaller gui.spec
# Output:      dist\PD72Builder\PD72Builder.exe

import sys
from pathlib import Path
import PySide6
import pdfminer

pyside6_dir = Path(PySide6.__file__).parent
pdfminer_dir = Path(pdfminer.__file__).parent

a = Analysis(
    ['gui.py'],
    pathex=['.'],
    binaries=[
        # PySide6 PDF support DLLs are not auto-collected.
        (str(pyside6_dir / 'Qt6Pdf.dll'),        'PySide6'),
        (str(pyside6_dir / 'Qt6PdfWidgets.dll'), 'PySide6'),
    ],
    datas=[
        # pdfplumber needs pdfminer's bundled font/cmap data.
        (str(pdfminer_dir), 'pdfminer'),
    ],
    hiddenimports=[
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'pikepdf._core',
        'pdfminer.high_level',
        'pdfminer.layout',
        'charset_normalizer',
        'ocrmypdf',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PD72Builder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PD72Builder',
)
