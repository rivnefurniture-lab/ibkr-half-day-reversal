from __future__ import annotations

from pathlib import Path

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from halfreversal.version import APP_VERSION

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "output" / "pdf" / "Scott_Half_Day_Reversal_Instructions.pdf"
DASHBOARD_URL = "https://half-day-reversal-production.up.railway.app"

STEPS = [
    (
        f"Download version {APP_VERSION} from the dashboard again and replace the older July 31 "
        "copy. On Mac, open the DMG and double-click the connector. It installs itself into "
        "Applications and opens automatically."
    ),
    (
        "If macOS blocks the first launch, use System Settings - Privacy & Security - Open Anyway, "
        "then double-click the connector in the download window once more. This is required only "
        "once."
    ),
    (
        "Open Half-Day Reversal Connector. Saved keys remain after upgrades. If setup appears, "
        "enter the dashboard access key and Databento key supplied by Andrii, keep live mode "
        "locked, and save."
    ),
    "Open TWS Paper and sign in to paper account DUH450551.",
    (
        "In TWS open Global Configuration - API - Settings. Enable ActiveX and Socket Clients, "
        "disable Read-Only API, use port 7497, allow localhost/127.0.0.1, click Apply, then "
        "restart TWS."
    ),
    (
        "Wait until the connector says Online. Keep TWS and the connector open through the next "
        "market open. The dashboard controls become available automatically."
    ),
    (
        "In dashboard Settings choose IBKR Paper, host 127.0.0.1, port 7497, client ID 17, and "
        "account DUH450551. Click Use current S&amp;P 400 beside Universe."
    ),
    (
        "For the first safe paper cycle use 1% total capital, 1% maximum per position, one maximum "
        "position, and automatic runs off. Save settings."
    ),
    (
        "Click Connect IBKR. Confirm the account label ends in 0551, then click Test paper order "
        "path. A green result means IBKR accepted the MOC what-if; no order is sent."
    ),
    (
        "Click Preview scan during regular US market hours. Confirm the dashboard shows the "
        "current mid-cap universe and selected worst intraday performer."
    ),
    (
        "For a real paper cycle, run between 3:37 and 3:44 PM New York time. Review the selection, "
        "arm with PAPER, then click Scan & execute. Confirm the MOC buy in TWS. The app stores the "
        "fill and submits the MKT/OPG sell at about 8:00 AM New York time for the next 9:30 AM "
        "opening auction."
    ),
    (
        "After the safe paper cycle is signed off, the full 400-stock bottom-decile configuration "
        "uses maximum positions 40. Choose the total capital allocation deliberately and keep "
        "automatic runs off until the full settings are reviewed."
    ),
]


def build_pdf(output_path: Path = OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "SimpleTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontName="Helvetica",
        fontSize=17,
        leading=20,
        spaceAfter=7 * mm,
    )
    body_style = ParagraphStyle(
        "SimpleBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.4,
        leading=12.2,
        spaceAfter=2.6 * mm,
    )
    note_style = ParagraphStyle(
        "SimpleNote",
        parent=body_style,
        fontSize=8.7,
        leading=11,
        spaceAfter=2 * mm,
    )
    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title="Half-Day Reversal - IBKR Paper Setup",
        author="Andrii Liudvichuk",
    )
    story = [
        Paragraph("Half-Day Reversal - IBKR Paper Setup", title_style),
        Paragraph(f"<b>Dashboard:</b> {DASHBOARD_URL}", body_style),
        Spacer(1, 1.5 * mm),
    ]
    story.extend(
        Paragraph(f"<b>{number}.</b> {step}", body_style)
        for number, step in enumerate(STEPS, start=1)
    )
    story.extend(
        [
            Spacer(1, 1.5 * mm),
            Paragraph(
                "<b>If it does not connect:</b> click Open diagnostics in the connector and send "
                "connector.log to Andrii. If the setup screen cannot open, send startup-error.log "
                "from Library/Application Support/Half-Day Reversal. The logs do not contain "
                "either access key.",
                note_style,
            ),
            Paragraph(
                "<b>Safety:</b> keep live mode locked until the complete MOC/MOO paper cycle has "
                "been reviewed. Auction orders do not guarantee a price.",
                note_style,
            ),
        ]
    )
    document.build(story)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("The setup PDF was not created")
    if stringWidth(f"Connector version {APP_VERSION}", "Helvetica", 9) <= 0:
        raise RuntimeError("ReportLab font verification failed")
    return output_path


if __name__ == "__main__":
    print(build_pdf())
