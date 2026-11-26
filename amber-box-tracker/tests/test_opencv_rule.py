"""OpenCV rule guard: the contrib headless build must provide WeChat QR.

The suite also passes with a broken cv2 (plain opencv-python shadowing the
contrib build), so assert the capability directly. Skips where cv2 is absent.
"""
from __future__ import annotations

import pytest

cv2 = pytest.importorskip("cv2")


def test_wechat_qrcode_capability_present():
    assert hasattr(cv2, "wechat_qrcode_WeChatQRCode"), (
        "cv2.wechat_qrcode missing: opencv-python is shadowing the pinned "
        "opencv-contrib-python-headless build - run python scripts/setup.py"
    )


def test_qr_decoder_constructs():
    from app.vision.qr import QRDecoder

    assert QRDecoder() is not None
