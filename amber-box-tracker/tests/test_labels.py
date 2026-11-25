"""Round-trip tests verifying generated PDF labels and ArUco markers decode cleanly."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.make_labels import (
    DEFAULT_CARTONS,
    DEFAULT_SHELVES,
    generate_carton_labels_pdf,
    generate_shelf_markers_pdf,
)


def _render_pdf_pages(pdf_bytes: bytes, dpi: int = 150) -> list[np.ndarray]:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages: list[np.ndarray] = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        elif pix.n == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        pages.append(img)
    return pages


def _decode_qrs(img: np.ndarray) -> list[str]:
    try:
        detector = cv2.wechat_qrcode_WeChatQRCode()
        decoded, _ = detector.detectAndDecode(img)
        if decoded:
            return [d for d in decoded if d]
    except (cv2.error, AttributeError):
        pass
    qr_det = cv2.QRCodeDetector()
    ok, decoded_info, _, _ = qr_det.detectAndDecodeMulti(img)
    if ok and decoded_info:
        return [d for d in decoded_info if d]
    val, _, _ = qr_det.detectAndDecode(img)
    return [val] if val else []


def test_carton_labels_4x6_roundtrip() -> None:
    pdf_bytes = generate_carton_labels_pdf(DEFAULT_CARTONS, layout="4x6")
    pages = _render_pdf_pages(pdf_bytes)
    assert len(pages) == len(DEFAULT_CARTONS)

    for page_img, expected in zip(pages, DEFAULT_CARTONS, strict=True):
        decoded = _decode_qrs(page_img)
        assert expected["label_code"] in decoded


def test_carton_labels_a4_roundtrip() -> None:
    pdf_bytes = generate_carton_labels_pdf(DEFAULT_CARTONS[:4], layout="a4")
    pages = _render_pdf_pages(pdf_bytes)
    assert len(pages) == 2

    all_decoded: list[str] = []
    for page_img in pages:
        h = page_img.shape[0]
        all_decoded.extend(_decode_qrs(page_img[: h // 2]))
        all_decoded.extend(_decode_qrs(page_img[h // 2 :]))

    for expected in DEFAULT_CARTONS[:4]:
        assert expected["label_code"] in all_decoded


def test_shelf_markers_roundtrip() -> None:
    pdf_bytes = generate_shelf_markers_pdf(DEFAULT_SHELVES)
    pages = _render_pdf_pages(pdf_bytes)
    assert len(pages) == len(DEFAULT_SHELVES)

    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    detector = cv2.aruco.ArucoDetector(aruco_dict, cv2.aruco.DetectorParameters())

    for page_img, expected in zip(pages, DEFAULT_SHELVES, strict=True):
        _corners, ids, _ = detector.detectMarkers(page_img)
        assert ids is not None, f"Failed to detect ArUco marker {expected['marker_id']}"
        assert int(expected["marker_id"]) in ids.flatten().tolist()
