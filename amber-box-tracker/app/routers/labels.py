"""Label PDFs (PRD-02 section 2.2): 4x6in or A4 carton QR labels, and
ArUco shelf markers. QR payload is KYC1:<code> with EC level M; the
destination never lives in the QR (PRD-01 section 1.4)."""
from __future__ import annotations

import io
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlmodel import select

from app.db import SessionDep
from app.models import Carton, Shelf

router = APIRouter(prefix="/api/labels", tags=["labels"])

LABEL_W_MM, LABEL_H_MM = 101.6, 152.4  # 4x6 in


def _qr_image(payload: str) -> io.BytesIO:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    buffer = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


@router.get("/cartons.pdf")
def cartons_pdf(
    session: SessionDep,
    delivery_id: str | None = None,
    format: Annotated[str, Query(pattern="^(4x6|a4)$")] = "4x6",
):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    query = select(Carton)
    if delivery_id:
        query = query.where(Carton.delivery_id == delivery_id)
    cartons = session.exec(query).all()

    buffer = io.BytesIO()
    page_size = A4 if format == "a4" else (LABEL_W_MM * mm, LABEL_H_MM * mm)
    pdf = canvas.Canvas(buffer, pagesize=page_size)
    width, height = page_size
    for index, carton in enumerate(cartons):
        if format == "a4" and index % 2 == 1:
            x_offset = width / 2  # 2-up on A4
        else:
            x_offset = 0
            if index:
                pdf.showPage()
        if format == "4x6" and index:
            pdf.showPage()
        img = _qr_image(f"KYC1:{carton.label_code}")
        side = min(width / 2 if format == "a4" else width, height) * 0.6
        pdf.drawImage(
            ImageReader(img),
            x_offset + (width / 2 - side) / 2 if format == "a4" else (width - side) / 2,
            height - side - 15 * mm,
            side,
            side,
        )
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(12 * mm if not x_offset else x_offset + 12 * mm, height - 10 * mm, carton.label_code)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(12 * mm if not x_offset else x_offset + 12 * mm, height - 16 * mm, carton.item_name[:40])
        pdf.drawString(12 * mm if not x_offset else x_offset + 12 * mm, height - 21 * mm, carton.po_number)
    pdf.save()
    return Response(
        buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=cartons.pdf"},
    )


@router.get("/shelves.pdf")
def shelves_pdf(session: SessionDep):
    try:
        import cv2
    except ImportError:
        return Response(
            "opencv-contrib-python-headless is required for ArUco markers",
            status_code=503,
        )
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    for index, shelf in enumerate(session.exec(select(Shelf)).all()):
        if index:
            pdf.showPage()
        marker = cv2.aruco.generateImageMarker(dictionary, shelf.marker_id, 600)
        ok, png = cv2.imencode(".png", marker)
        if not ok:
            continue
        side = 120 * mm
        pdf.drawImage(
            ImageReader(io.BytesIO(png.tobytes())),
            (width - side) / 2,
            height - side - 30 * mm,
            side,
            side,
        )
        pdf.setFont("Helvetica-Bold", 20)
        pdf.drawCentredString(width / 2, height - 20 * mm, f"{shelf.code} (marker {shelf.marker_id})")
    pdf.save()
    return Response(
        buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=shelves.pdf"},
    )
