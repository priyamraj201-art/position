"""Generate 4x6 / A4 PDF carton QR labels and ArUco 4x4_50 shelf marker PDFs."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

import cv2
import qrcode
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PAGE_4X6 = (101.6 * mm, 152.4 * mm)

DEFAULT_CARTONS: list[dict[str, Any]] = [
    {
        "label_code": "KYC1:BV2401",
        "item_name": "2in ball valve",
        "po_number": "PO-1077",
        "po_line": 1,
        "delivery_id": "DEL-2211",
        "dest_level": 2,
        "dest_shelf": "L2-B2",
    },
    {
        "label_code": "KYC1:BV2402",
        "item_name": "2in ball valve",
        "po_number": "PO-1077",
        "po_line": 1,
        "delivery_id": "DEL-2211",
        "dest_level": 2,
        "dest_shelf": "L2-B2",
    },
    {
        "label_code": "KYC1:BF1201",
        "item_name": "3in butterfly valve",
        "po_number": "PO-1077",
        "po_line": 2,
        "delivery_id": "DEL-2211",
        "dest_level": 2,
        "dest_shelf": "L2-B1",
    },
    {
        "label_code": "KYC1:YS0601",
        "item_name": "Y strainer",
        "po_number": "PO-1077",
        "po_line": 3,
        "delivery_id": "DEL-2211",
        "dest_level": 2,
        "dest_shelf": "L2-B1",
    },
    {
        "label_code": "KYC1:DM0401",
        "item_name": "AHU-3 damper kit",
        "po_number": "PO-1077",
        "po_line": 4,
        "delivery_id": "DEL-2211",
        "dest_level": 2,
        "dest_shelf": "L2-B2",
    },
    {
        "label_code": "KYC1:DM0402",
        "item_name": "AHU-3 damper kit",
        "po_number": "PO-1077",
        "po_line": 4,
        "delivery_id": "DEL-2211",
        "dest_level": 2,
        "dest_shelf": "L2-B3",
    },
    {
        "label_code": "KYC1:CH0201",
        "item_name": "Chiller parts kit CH-2",
        "po_number": "PO-1042",
        "po_line": 1,
        "delivery_id": "DEL-2190",
        "dest_level": 3,
        "dest_shelf": "L3-A1",
    },
    {
        "label_code": "KYC1:CH0202",
        "item_name": "Chiller parts kit CH-2",
        "po_number": "PO-1042",
        "po_line": 1,
        "delivery_id": "DEL-2190",
        "dest_level": 3,
        "dest_shelf": "L3-A1",
    },
]

DEFAULT_SHELVES: list[dict[str, Any]] = [
    {"code": "L2-B1", "level": 2, "marker_id": 1},
    {"code": "L2-B2", "level": 2, "marker_id": 2},
    {"code": "L2-B3", "level": 2, "marker_id": 3},
    {"code": "L3-A1", "level": 3, "marker_id": 11},
    {"code": "L3-A2", "level": 3, "marker_id": 12},
]


def make_qr_pil(payload: str, box_size: int = 12, border: int = 2) -> Image.Image:
    """Create a high-contrast QR code PIL image with Error Correction Level M."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def make_aruco_pil(marker_id: int, size_px: int = 600) -> Image.Image:
    """Generate a DICT_4X4_50 ArUco marker PIL image."""
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker_img = cv2.aruco.generateImageMarker(aruco_dict, marker_id, size_px)
    rgb = cv2.cvtColor(marker_img, cv2.COLOR_GRAY2RGB)
    return Image.fromarray(rgb)


def _draw_carton_label(
    c: canvas.Canvas,
    carton: dict[str, Any],
    origin_x: float,
    origin_y: float,
    width: float,
    height: float,
) -> None:
    """Draw a single carton label inside the given bounding box."""
    qr_size = 90 * mm
    qr_x = origin_x + (width - qr_size) / 2
    qr_y = origin_y + height - qr_size - 6 * mm

    qr_img = make_qr_pil(carton["label_code"])
    c.drawImage(ImageReader(qr_img), qr_x, qr_y, width=qr_size, height=qr_size)

    text_center_x = origin_x + width / 2
    dest_level = carton.get("dest_level", "?")
    dest_shelf = carton.get("dest_shelf", "?")

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(text_center_x, qr_y - 9 * mm, f"FLOOR {dest_level} · SHELF {dest_shelf}")

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(text_center_x, qr_y - 17 * mm, str(carton.get("item_name", ""))[:36])

    c.setFont("Helvetica", 10)
    po_num = carton.get("po_number", "")
    po_line = carton.get("po_line", "")
    delivery_id = carton.get("delivery_id", "")
    c.drawCentredString(text_center_x, qr_y - 24 * mm, f"{po_num} (Line {po_line}) · {delivery_id}")

    c.setFont("Courier-Bold", 13)
    c.drawCentredString(text_center_x, qr_y - 32 * mm, carton["label_code"])


def generate_carton_labels_pdf(
    cartons: list[dict[str, Any]],
    layout: str = "4x6",
) -> bytes:
    """Generate a PDF containing carton QR labels in 4x6 (1/page) or A4 (2/page) layout."""
    buf = io.BytesIO()
    if layout.lower() == "a4":
        page_w, page_h = A4
        c = canvas.Canvas(buf, pagesize=A4)
        half_h = page_h / 2
        for idx, carton in enumerate(cartons):
            slot = idx % 2
            y_offset = half_h if slot == 0 else 0
            _draw_carton_label(c, carton, 0, y_offset, page_w, half_h)
            if slot == 0 and idx + 1 < len(cartons):
                c.setDash(3, 3)
                c.line(10 * mm, half_h, page_w - 10 * mm, half_h)
                c.setDash()
            if slot == 1 or idx == len(cartons) - 1:
                c.showPage()
    else:
        page_w, page_h = PAGE_4X6
        c = canvas.Canvas(buf, pagesize=PAGE_4X6)
        for carton in cartons:
            _draw_carton_label(c, carton, 0, 0, page_w, page_h)
            c.showPage()

    c.save()
    return buf.getvalue()


def generate_shelf_markers_pdf(shelves: list[dict[str, Any]]) -> bytes:
    """Generate an A4 PDF with 100mm ArUco 4x4_50 markers and 20mm white quiet zones."""
    buf = io.BytesIO()
    page_w, page_h = A4
    c = canvas.Canvas(buf, pagesize=A4)
    marker_size = 100 * mm

    for shelf in shelves:
        marker_id = int(shelf["marker_id"])
        marker_img = make_aruco_pil(marker_id)
        x = (page_w - marker_size) / 2
        y = (page_h - marker_size) / 2 + 15 * mm

        # 20mm white quiet zone around the 100mm marker
        quiet = 20 * mm
        c.setFillColorRGB(1, 1, 1)
        c.rect(x - quiet, y - quiet, marker_size + 2 * quiet, marker_size + 2 * quiet, stroke=0, fill=1)
        c.drawImage(ImageReader(marker_img), x, y, width=marker_size, height=marker_size)

        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 28)
        c.drawCentredString(page_w / 2, y - 32 * mm, f"SHELF {shelf['code']}")
        c.setFont("Helvetica", 14)
        c.drawCentredString(
            page_w / 2,
            y - 42 * mm,
            f"Floor {shelf['level']} · ArUco DICT_4X4_50 · ID {marker_id}",
        )
        c.showPage()

    c.save()
    return buf.getvalue()


def _load_seed(seed_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not seed_path.exists():
        return DEFAULT_CARTONS, DEFAULT_SHELVES
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    shelves_by_id = {s["id"]: s for s in data.get("shelves", [])}
    cartons = []
    for c_item in data.get("cartons", []):
        shelf = shelves_by_id.get(c_item.get("dest_shelf_id"), {})
        cartons.append(
            {
                **c_item,
                "dest_shelf": shelf.get("code", c_item.get("dest_shelf", "UNKNOWN")),
            }
        )
    return cartons or DEFAULT_CARTONS, data.get("shelves", DEFAULT_SHELVES)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Amber Box Tracker PDF labels & markers")
    parser.add_argument("--seed", type=Path, default=Path("data/seed.json"))
    parser.add_argument("--out-dir", type=Path, default=Path("output/labels"))
    parser.add_argument("--layout", choices=["4x6", "a4"], default="4x6")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    cartons, shelves = _load_seed(args.seed)

    carton_pdf = args.out_dir / f"cartons_{args.layout}.pdf"
    carton_pdf.write_bytes(generate_carton_labels_pdf(cartons, layout=args.layout))

    shelf_pdf = args.out_dir / "shelf_markers.pdf"
    shelf_pdf.write_bytes(generate_shelf_markers_pdf(shelves))

    print(f"Generated {carton_pdf} ({len(cartons)} cartons) and {shelf_pdf} ({len(shelves)} shelves)")


if __name__ == "__main__":
    main()
