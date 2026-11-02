"""QR Code generation utility."""
import io
import subprocess
from typing import Optional

try:
    import qrcode
    from PIL import Image
    HAS_PIL_QR = True
except ImportError:
    HAS_PIL_QR = False


def generate_qr_bytes(text: str) -> io.BytesIO:
    """Generate a high-contrast QR code as PNG image bytes."""
    output = io.BytesIO()

    if HAS_PIL_QR:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(output, format="PNG")
        output.seek(0)
        return output

    # Fallback to system /usr/bin/qrencode
    try:
        proc = subprocess.run(
            ["/usr/bin/qrencode", "-o", "-", "-t", "PNG", "-s", "8", "-m", "2", text],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=10,
        )
        output.write(proc.stdout)
        output.seek(0)
        return output
    except Exception as exc:
        raise RuntimeError(f"Не удалось сгенерировать QR-код: {exc}") from exc
