from __future__ import annotations

import csv
import io
from pathlib import Path


def submissions_csv(items: list[dict]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Группа", "Ученик", "Email", "Работа", "Попытка", "Статус", "Баллы", "Дата"])
    for item in items:
        review = item.get("review")
        writer.writerow(
            [
                item["groupName"],
                item["studentName"],
                item["studentEmail"],
                item["title"],
                item["attempt"],
                "Проверено" if item["status"] == "graded" else "На проверке",
                f"{review['total']}/{review['maximum']}" if review else "",
                item["submittedAt"],
            ]
        )
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def submissions_pdf(items: list[dict]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font = "Helvetica"
    if font_path.is_file():
        pdfmetrics.registerFont(TTFont("DejaVu", font_path))
        font = "DejaVu"
    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, title="Работы учеников")
    styles = getSampleStyleSheet()
    styles["Title"].fontName = font
    story = [Paragraph("Работы учеников", styles["Title"]), Spacer(1, 12)]
    rows = [["Группа", "Ученик", "Работа", "Попытка", "Статус", "Баллы"]]
    for item in items:
        review = item.get("review")
        rows.append(
            [
                item["groupName"],
                item["studentName"],
                item["title"],
                str(item["attempt"]),
                "Проверено" if review else "На проверке",
                f"{review['total']}/{review['maximum']}" if review else "—",
            ]
        )
    table = Table(rows, repeatRows=1, colWidths=[70, 90, 145, 45, 65, 45])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8b1a1a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f1e6")]),
            ]
        )
    )
    story.append(table)
    document.build(story)
    return output.getvalue()
