"""
Desktop GUI for the PD-72 build pipeline.

Drop a PDF (or use File -> Open). The GUI auto-runs OCR and page numbering
in a worker thread, then runs detect() to find every affidavit exhibit.
The right pane walks the user one card at a time through each exhibit,
jumping the PDF preview to the slot page so they can confirm or correct
the page and title. The final Save step writes a TOML, runs bookmark.py
+ hyperlink.py, and produces the PD-72-compliant final PDF.

Run: python gui.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pdfplumber
from PySide6.QtCore import QObject, QPointF, Qt, QThread, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QSpinBox, QSplitter, QStackedWidget, QStatusBar, QVBoxLayout,
    QWidget,
)
from pypdf import PdfReader

from bookmark import add_bookmarks
from detect import _drop_unfilled, detect, emit_toml
from hyperlink import add_hyperlinks
from ocr import ocr_pdf
from pagenumber import add_page_numbers


PLACEHOLDER_TEXT = (
    "Drop a PDF anywhere in this window,\n"
    "or use File -> Open to browse for one.\n\n"
    "If the PDF needs OCR or page numbers,\n"
    "those run automatically before preview.\n\n"
    "Once it's loaded I'll walk through each\n"
    "affidavit exhibit one at a time so you\n"
    "can confirm the page and the title."
)


# ---- preprocessing helpers ----


def _needs_paging(pdf_path: Path) -> bool:
    """True if the first few pages don't show their page number top-centre."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        n_check = min(3, len(pdf.pages))
        for i in range(n_check):
            page = pdf.pages[i]
            top = page.crop((0, 0, page.width, page.height * 0.06))
            tokens = re.findall(r"\b\d+\b", (top.extract_text() or ""))
            if str(i + 1) in tokens:
                return False  # at least one page has a number — assume paged
    return True


class _Preprocessor(QObject):
    """Background worker: runs OCR and/or page numbering as needed."""
    progress = Signal(str)
    finished = Signal(Path)
    failed = Signal(str)

    def __init__(self, src: Path) -> None:
        super().__init__()
        self._src = src

    def run(self) -> None:
        try:
            current = self._src

            # Always OCR, even if a text layer is present. ocrmypdf is invoked
            # with --skip-text so already-searchable pages are passed through
            # untouched; this catches the common case of a Word-exported PDF
            # whose scanned-stamped exhibit cover sheets carry no text.
            self.progress.emit("Running OCR (this can take a few minutes)...")
            current = ocr_pdf(str(current))

            if _needs_paging(current):
                self.progress.emit("Adding page numbers...")
                current = add_page_numbers(str(current))
            else:
                self.progress.emit("PDF already page-numbered, skipping.")

            self.finished.emit(current)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class _Detector(QObject):
    """Background worker: runs detect() on the prepared PDF."""
    finished = Signal(object)  # tuple (bookmarks, index_pages, warnings, n_pages)
    failed = Signal(str)

    def __init__(self, pdf_path: Path) -> None:
        super().__init__()
        self._pdf_path = pdf_path

    def run(self) -> None:
        try:
            bookmarks, index_pages, warnings, _ctx = detect(self._pdf_path)
            n_pages = len(PdfReader(str(self._pdf_path)).pages)
            self.finished.emit((bookmarks, index_pages, warnings, n_pages))
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class _Saver(QObject):
    """Background worker: TOML -> bookmark.py -> hyperlink.py."""
    progress = Signal(str)
    finished = Signal(Path)  # final PDF path
    failed = Signal(str)

    def __init__(
        self,
        bookmarks: list[dict],
        index_pages: list[int],
        prepared_pdf: Path,
    ) -> None:
        super().__init__()
        self._bookmarks = bookmarks
        self._index_pages = index_pages
        self._prepared_pdf = prepared_pdf

    def run(self) -> None:
        try:
            cleaned = _drop_unfilled(self._bookmarks)
            toml_path = self._prepared_pdf.with_suffix(".bookmarks.toml")
            self.progress.emit(f"Writing {toml_path.name}...")
            toml_text = emit_toml(
                cleaned, [], self._prepared_pdf,
                index_pages=self._index_pages, draft=False,
            )
            toml_path.write_text(toml_text, encoding="utf-8")

            self.progress.emit("Adding bookmarks...")
            bookmarked = add_bookmarks(str(self._prepared_pdf), str(toml_path))

            self.progress.emit("Adding hyperlinks...")
            final = add_hyperlinks(str(bookmarked), str(toml_path))
            self.finished.emit(final)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


def build_review_tasks(bookmarks: list[dict]) -> list[dict]:
    """Flatten bookmarks into a per-exhibit review queue.

    One task per exhibit in every located affidavit. Tasks carry a `ref`
    pointing back at the exhibit dict so confirms mutate the bookmark
    tree in place.
    """
    tasks: list[dict] = []
    for b in bookmarks:
        if b.get("kind") != "affidavit" or not b.get("page"):
            continue
        surname = "?"
        if b.get("_affiant"):
            surname = b["_affiant"].split()[-1]
        date = b.get("_date") or "?"
        for ex in b.get("exhibit", []):
            tasks.append({
                "ref": ex,
                "parent_title": b["title"],
                "surname": surname,
                "date": date,
                "letter": ex.get("_letter", "?"),
                "missing": ex.get("page") is None,
                "hint_lo": ex.get("_hint_lo"),
                "hint_hi": ex.get("_hint_hi"),
                "verify_reason": ex.get("_reason"),
                "n_covers": ex.get("_n_covers"),
                "n_refs": ex.get("_n_refs"),
            })
    return tasks


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PD-72 Application Record Builder")
        self.resize(1400, 900)
        self.setAcceptDrops(True)

        self._pdf_doc = QPdfDocument(self)
        self._tasks: list[dict] = []
        self._task_idx = 0
        self._n_pages = 0
        # Held for the Save step — the bookmarks dict is the in-memory model
        # the review cards mutate, prepared_pdf is what we hand to bookmark.py.
        self._bookmarks: list[dict] = []
        self._index_pages: list[int] = []
        self._prepared_pdf: Path | None = None
        self._final_pdf: Path | None = None
        self._build_ui()
        self._build_menu()

        self.statusBar().showMessage("Ready. Open a PDF to begin.")

    # ---- UI construction ----

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left: PDF preview.
        self._pdf_view = QPdfView(self)
        self._pdf_view.setDocument(self._pdf_doc)
        self._pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self._pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        splitter.addWidget(self._pdf_view)

        # Right: stacked panel — intro / review / done.
        self._right_stack = QStackedWidget(self)
        self._right_stack.addWidget(self._build_intro_page())   # idx 0
        self._right_stack.addWidget(self._build_review_page())  # idx 1
        self._right_stack.addWidget(self._build_done_page())    # idx 2
        splitter.addWidget(self._right_stack)

        # Heavier weight on the PDF pane — that's what the user is reading.
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([840, 560])

        self.setCentralWidget(splitter)
        self.setStatusBar(QStatusBar(self))

    def _build_intro_page(self) -> QWidget:
        w = QWidget(self)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 24, 24, 24)

        self._intro_label = QLabel(PLACEHOLDER_TEXT, w)
        self._intro_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._intro_label.setWordWrap(True)
        f = self._intro_label.font()
        f.setPointSize(11)
        self._intro_label.setFont(f)
        layout.addWidget(self._intro_label)
        layout.addStretch(1)

        self._open_button = QPushButton("Open PDF...", w)
        self._open_button.setMinimumHeight(40)
        self._open_button.clicked.connect(self.open_file_dialog)
        layout.addWidget(self._open_button)
        return w

    def _build_review_page(self) -> QWidget:
        w = QWidget(self)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        self._card_progress = QLabel("", w)
        self._card_progress.setStyleSheet("color: #666;")
        layout.addWidget(self._card_progress)

        self._card_header = QLabel("", w)
        hf = self._card_header.font()
        hf.setPointSize(14)
        hf.setBold(True)
        self._card_header.setFont(hf)
        self._card_header.setWordWrap(True)
        layout.addWidget(self._card_header)

        self._card_parent = QLabel("", w)
        pf = self._card_parent.font()
        pf.setPointSize(10)
        self._card_parent.setFont(pf)
        self._card_parent.setStyleSheet("color: #555;")
        self._card_parent.setWordWrap(True)
        layout.addWidget(self._card_parent)

        # Yellow-flag note for verify-flagged exhibits and missing exhibits.
        self._card_note = QLabel("", w)
        self._card_note.setWordWrap(True)
        self._card_note.setStyleSheet(
            "background: #fff4d6; color: #6a4400; "
            "padding: 8px; border-radius: 4px;"
        )
        self._card_note.hide()
        layout.addWidget(self._card_note)

        page_row = QHBoxLayout()
        page_lbl = QLabel("Page:", w)
        page_row.addWidget(page_lbl)
        self._card_page = QSpinBox(w)
        self._card_page.setRange(1, 99999)
        self._card_page.setMinimumWidth(100)
        # Jump the PDF preview when the spinbox changes so the user sees
        # the page they're about to confirm.
        self._card_page.valueChanged.connect(self._on_card_page_changed)
        page_row.addWidget(self._card_page)
        page_row.addStretch(1)
        layout.addLayout(page_row)

        layout.addWidget(QLabel("Title:", w))
        self._card_title = QLineEdit(w)
        layout.addWidget(self._card_title)

        layout.addStretch(1)

        button_row = QHBoxLayout()
        self._card_skip_btn = QPushButton("Leave out", w)
        self._card_skip_btn.clicked.connect(self._on_card_skip)
        button_row.addWidget(self._card_skip_btn)
        button_row.addStretch(1)
        self._card_back_btn = QPushButton("Back", w)
        self._card_back_btn.clicked.connect(self._on_card_back)
        button_row.addWidget(self._card_back_btn)
        self._card_confirm_btn = QPushButton("Confirm", w)
        self._card_confirm_btn.setDefault(True)
        self._card_confirm_btn.setMinimumHeight(36)
        self._card_confirm_btn.clicked.connect(self._on_card_confirm)
        button_row.addWidget(self._card_confirm_btn)
        layout.addLayout(button_row)
        return w

    def _build_done_page(self) -> QWidget:
        w = QWidget(self)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        self._done_label = QLabel("", w)
        self._done_label.setWordWrap(True)
        df = self._done_label.font()
        df.setPointSize(12)
        self._done_label.setFont(df)
        layout.addWidget(self._done_label)

        layout.addStretch(1)

        self._save_button = QPushButton("Save final PDF", w)
        self._save_button.setMinimumHeight(44)
        sf = self._save_button.font()
        sf.setPointSize(12)
        sf.setBold(True)
        self._save_button.setFont(sf)
        self._save_button.clicked.connect(self._on_save_click)
        layout.addWidget(self._save_button)

        self._open_folder_button = QPushButton("Open folder", w)
        self._open_folder_button.clicked.connect(self._on_open_folder)
        self._open_folder_button.hide()
        layout.addWidget(self._open_folder_button)
        return w

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_act = QAction("&Open...", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self.open_file_dialog)
        file_menu.addAction(open_act)

        file_menu.addSeparator()

        quit_act = QAction("&Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

    # ---- file loading ----

    def open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open PDF",
            "",
            "PDF files (*.pdf);;All files (*)",
        )
        if path:
            self.load_pdf(Path(path))

    def load_pdf(self, path: Path) -> None:
        if not path.exists():
            self.statusBar().showMessage(f"File not found: {path}", 5000)
            return

        # Always run the preprocessor — the helpers short-circuit cheaply
        # when OCR / paging are already present, so this costs nothing for
        # already-processed files and saves the user from picking the
        # right variant of their input.
        self._open_button.setEnabled(False)
        self._open_button.setText("Processing... (see status bar)")
        self._intro_label.setText(f"Preparing {path.name}...")
        self.statusBar().showMessage(f"Checking {path.name}...")

        self._prep_thread = QThread(self)
        self._prep_worker = _Preprocessor(path)
        self._prep_worker.moveToThread(self._prep_thread)
        self._prep_thread.started.connect(self._prep_worker.run)
        self._prep_worker.progress.connect(
            lambda msg: self.statusBar().showMessage(msg)
        )
        self._prep_worker.finished.connect(self._on_preprocess_done)
        self._prep_worker.failed.connect(self._on_preprocess_failed)
        self._prep_worker.finished.connect(self._prep_thread.quit)
        self._prep_worker.failed.connect(self._prep_thread.quit)
        self._prep_thread.finished.connect(self._prep_thread.deleteLater)
        self._prep_thread.start()

    def _on_preprocess_done(self, processed: Path) -> None:
        status = self._pdf_doc.load(str(processed))
        if status != QPdfDocument.Error.None_:
            self.statusBar().showMessage(
                f"Couldn't open {processed.name} ({status.name})", 8000
            )
            self._reset_open_button()
            return

        self._prepared_pdf = processed
        self._n_pages = self._pdf_doc.pageCount()
        self.setWindowTitle(f"PD-72 Builder - {processed.name}")
        self.statusBar().showMessage(
            f"Scanning {processed.name} for affidavit exhibits..."
        )
        self._intro_label.setText(
            f"Loaded {processed.name} ({self._n_pages} pages).\n\n"
            "Scanning for affidavit exhibits..."
        )

        # Kick off detect() in a worker so the UI stays responsive on big
        # records (76-page reference takes ~1s; paranoid for larger ones).
        self._detect_thread = QThread(self)
        self._detect_worker = _Detector(processed)
        self._detect_worker.moveToThread(self._detect_thread)
        self._detect_thread.started.connect(self._detect_worker.run)
        self._detect_worker.finished.connect(self._on_detect_done)
        self._detect_worker.failed.connect(self._on_detect_failed)
        self._detect_worker.finished.connect(self._detect_thread.quit)
        self._detect_worker.failed.connect(self._detect_thread.quit)
        self._detect_thread.finished.connect(self._detect_thread.deleteLater)
        self._detect_thread.start()

    def _on_preprocess_failed(self, msg: str) -> None:
        self.statusBar().showMessage(f"Preprocessing failed - {msg}", 12000)
        self._intro_label.setText(
            f"Couldn't prepare the PDF:\n\n{msg}\n\nTry another file."
        )
        self._reset_open_button()

    def _reset_open_button(self) -> None:
        self._open_button.setEnabled(True)
        self._open_button.setText("Open PDF...")

    # ---- detect / review ----

    def _on_detect_done(self, payload: tuple) -> None:
        bookmarks, index_pages, warnings, n_pages = payload
        self._n_pages = n_pages
        self._bookmarks = bookmarks
        self._index_pages = index_pages
        self._tasks = build_review_tasks(bookmarks)

        if not self._tasks:
            # No exhibits to review, but the bookmarks tree may still be
            # worth saving (e.g. just a NOA + standalone documents) — let
            # the Save button decide.
            self._show_done(
                "No affidavit exhibits were detected.\n\n"
                "If the document tabs above are correct you can still save."
            )
            return

        n_warn = len(warnings)
        msg = (
            f"Found {len(self._tasks)} exhibit(s) across "
            f"{sum(1 for t in self._tasks if t['letter'] == 'A')} affidavit(s)."
        )
        if n_warn:
            msg += f" ({n_warn} warning(s) — check the log.)"
        self.statusBar().showMessage(msg, 8000)

        self._task_idx = 0
        self._right_stack.setCurrentIndex(1)
        self._show_current_task()

    def _on_detect_failed(self, msg: str) -> None:
        self.statusBar().showMessage(f"Detection failed - {msg}", 12000)
        self._intro_label.setText(
            f"Detection failed:\n\n{msg}\n\nTry another file."
        )
        self._reset_open_button()
        self._right_stack.setCurrentIndex(0)

    def _show_current_task(self) -> None:
        task = self._tasks[self._task_idx]
        ex = task["ref"]
        n = len(self._tasks)
        self._card_progress.setText(f"Exhibit {self._task_idx + 1} of {n}")
        self._card_header.setText(
            f"Affidavit of {task['surname']} made {task['date']} "
            f"- Exhibit {task['letter']}"
        )
        self._card_parent.setText(task["parent_title"])

        # Note row: missing-exhibit message wins over verify-flag message.
        if task["missing"]:
            lo, hi = task.get("hint_lo"), task.get("hint_hi")
            range_txt = f"between p{lo} and p{hi}" if lo and hi else ""
            self._card_note.setText(
                f"The body mentions Exhibit {task['letter']} but I couldn't "
                f"find its cover page. Look {range_txt} for a stamp that "
                f'starts "This is Exhibit {task["letter"]}".'
            )
            self._card_note.show()
        elif task.get("verify_reason") == "dense_window":
            self._card_note.setText(
                f"This section has {task['n_covers']} cover pages but the "
                f"body only lists {task['n_refs']} exhibits. One exhibit is "
                "probably a packet (e.g. a nested affidavit). Double-check "
                "that the page below is the right one."
            )
            self._card_note.show()
        elif task.get("verify_reason") == "nested_skip":
            self._card_note.setText(
                "This exhibit was found AFTER skipping past a nested "
                "affidavit's own exhibits. Worth a quick double-check."
            )
            self._card_note.show()
        else:
            self._card_note.hide()

        # Pre-fill page + title.
        default_page = ex.get("page") or task.get("hint_lo") or 1
        # Block the spinbox signal so setting the value doesn't kick off
        # an extra PDF jump before we've finished setting up the card.
        self._card_page.blockSignals(True)
        self._card_page.setRange(1, max(self._n_pages, 1))
        self._card_page.setValue(default_page)
        self._card_page.blockSignals(False)
        self._card_title.setText(ex.get("title", ""))

        self._jump_to_pdf_page(default_page)
        self._card_back_btn.setEnabled(self._task_idx > 0)
        self._card_confirm_btn.setFocus()

    def _on_card_page_changed(self, value: int) -> None:
        self._jump_to_pdf_page(value)

    def _on_card_confirm(self) -> None:
        task = self._tasks[self._task_idx]
        task["ref"]["page"] = self._card_page.value()
        new_title = self._card_title.text().strip() or task["ref"].get("title", "")
        task["ref"]["title"] = new_title
        self._advance()

    def _on_card_skip(self) -> None:
        task = self._tasks[self._task_idx]
        # Mark as None so _drop_unfilled (or the eventual save step) drops it.
        task["ref"]["page"] = None
        self._advance()

    def _on_card_back(self) -> None:
        if self._task_idx == 0:
            return
        self._task_idx -= 1
        self._show_current_task()

    def _advance(self) -> None:
        self._task_idx += 1
        if self._task_idx >= len(self._tasks):
            kept = sum(1 for t in self._tasks if t["ref"].get("page") is not None)
            dropped = len(self._tasks) - kept
            self._show_done(
                f"Review complete - {kept} exhibit(s) confirmed, "
                f"{dropped} dropped.\n\n"
                "Click Save to add bookmarks and hyperlinks."
            )
            return
        self._show_current_task()

    def _show_done(self, msg: str) -> None:
        self._done_label.setText(msg)
        self._save_button.setEnabled(True)
        self._save_button.setText("Save final PDF")
        self._save_button.show()
        self._open_folder_button.hide()
        self._final_pdf = None
        self._right_stack.setCurrentIndex(2)

    # ---- save (bookmark + hyperlink) ----

    def _on_save_click(self) -> None:
        if not self._prepared_pdf or not self._bookmarks:
            self.statusBar().showMessage("Nothing to save.", 5000)
            return
        self._save_button.setEnabled(False)
        self._save_button.setText("Saving...")
        self.statusBar().showMessage("Saving...")

        self._save_thread = QThread(self)
        self._save_worker = _Saver(
            self._bookmarks, self._index_pages, self._prepared_pdf
        )
        self._save_worker.moveToThread(self._save_thread)
        self._save_thread.started.connect(self._save_worker.run)
        self._save_worker.progress.connect(
            lambda msg: self.statusBar().showMessage(msg)
        )
        self._save_worker.finished.connect(self._on_save_done)
        self._save_worker.failed.connect(self._on_save_failed)
        self._save_worker.finished.connect(self._save_thread.quit)
        self._save_worker.failed.connect(self._save_thread.quit)
        self._save_thread.finished.connect(self._save_thread.deleteLater)
        self._save_thread.start()

    def _on_save_done(self, final: Path) -> None:
        self._final_pdf = final
        size_mb = final.stat().st_size / 1_000_000
        self._done_label.setText(
            f"Saved.\n\n{final.name}\n({size_mb:.1f} MB)\n\n"
            "Open it in Acrobat to verify the bookmarks and links, then "
            "use compliance.py to confirm PD-72 compliance."
        )
        self.statusBar().showMessage(f"Saved {final.name}", 8000)
        self._save_button.hide()
        self._open_folder_button.show()
        # Auto-load the final PDF into the preview so the user can spot-check
        # immediately without leaving the app.
        if self._pdf_doc.load(str(final)) == QPdfDocument.Error.None_:
            self.setWindowTitle(f"PD-72 Builder - {final.name}")

    def _on_save_failed(self, msg: str) -> None:
        self._done_label.setText(
            f"Save failed:\n\n{msg}\n\n"
            "The bookmarks TOML was written, so you can re-run "
            "bookmark.py + hyperlink.py from the command line."
        )
        self.statusBar().showMessage(f"Save failed - {msg}", 12000)
        self._save_button.setEnabled(True)
        self._save_button.setText("Try save again")

    def _on_open_folder(self) -> None:
        if not self._final_pdf:
            return
        # Open the containing folder with the final PDF preselected.
        try:
            subprocess.Popen(["explorer", "/select,", str(self._final_pdf)])
        except OSError:
            os.startfile(str(self._final_pdf.parent))

    def _jump_to_pdf_page(self, page_1indexed: int) -> None:
        """Scroll the preview so `page_1indexed` is the visible page."""
        if self._n_pages <= 0:
            return
        page = max(1, min(page_1indexed, self._n_pages))
        nav = self._pdf_view.pageNavigator()
        nav.jump(page - 1, QPointF(0, 0), nav.currentZoom())

    # ---- drag-and-drop ----

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        # Accept any drag that includes at least one local PDF path.
        urls = event.mimeData().urls() if event.mimeData() else []
        if any(u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf") for u in urls):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for u in event.mimeData().urls():
            if u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf"):
                self.load_pdf(Path(u.toLocalFile()))
                break


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
