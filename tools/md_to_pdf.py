"""Render the handoff markdown to a PDF, simply and without a converter."""
import re
import sys
from pathlib import Path

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)
from reportlab.lib import colors

src = Path(sys.argv[1]).read_text(encoding="utf-8")
out = Path(sys.argv[2])

base = getSampleStyleSheet()
styles = {
    "h1": ParagraphStyle("h1", parent=base["Heading1"], fontSize=19, spaceAfter=10,
                         textColor=colors.HexColor("#111827")),
    "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=14, spaceBefore=14,
                         spaceAfter=6, textColor=colors.HexColor("#1f2937")),
    "h3": ParagraphStyle("h3", parent=base["Heading3"], fontSize=11.5, spaceBefore=10,
                         spaceAfter=4, textColor=colors.HexColor("#374151")),
    "body": ParagraphStyle("body", parent=base["BodyText"], fontSize=9.6, leading=14,
                           alignment=TA_LEFT, spaceAfter=6),
    "code": ParagraphStyle("code", parent=base["BodyText"], fontName="Courier",
                           fontSize=8.4, leading=11, leftIndent=8,
                           textColor=colors.HexColor("#1f2937"), spaceAfter=6),
    "bullet": ParagraphStyle("bullet", parent=base["BodyText"], fontSize=9.6,
                             leading=13.5, leftIndent=12, bulletIndent=4,
                             spaceAfter=3),
}


def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Pull code spans out first. A literal asterisk inside one, such as
    # spells*.csv, otherwise gets eaten by the emphasis pass and leaves
    # overlapping tags that reportlab refuses to parse.
    spans = []

    def stash(match):
        spans.append(match.group(1))
        return "@@C" + str(len(spans) - 1) + "@@"

    text = re.sub(r"`(.+?)`", stash, text)
    # Bold is dropped rather than rendered. This document exists to be pasted
    # into another model, and reportlab's bold font runs do not survive text
    # extraction - they come out as a single replacement glyph, so emphasis
    # would silently delete the very sentences it was meant to stress.
    # Emphasis markers are stripped rather than rendered. This document
    # is meant to be pasted into another model, and reportlab's bold
    # font runs do not survive text extraction - they come out as one
    # replacement glyph, which would silently delete the very sentences
    # the emphasis was there to stress. Code spans are already stashed,
    # so removing every asterisk here is safe.
    text = text.replace("*", "")
    for index, span in enumerate(spans):
        token = "@@C" + str(index) + "@@"
        text = text.replace(token, '<font face="Courier">' + span + "</font>")
    return text


flow = []
lines = src.splitlines()
i = 0
while i < len(lines):
    line = lines[i]

    if line.startswith("|"):                       # table
        rows = []
        while i < len(lines) and lines[i].startswith("|"):
            cells = [c.strip() for c in lines[i].strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                rows.append(cells)
            i += 1
        width = max(len(r) for r in rows)
        data = [[Paragraph(inline(c), styles["body"]) for c in r + [""] * (width - len(r))]
                for r in rows]
        table = Table(data, colWidths=[(170 * mm) / width] * width, repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(table)
        flow.append(Spacer(1, 7))
        continue

    if line.startswith("    ") and line.strip():     # indented code block
        block = []
        while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
            if lines[i].strip():
                block.append(lines[i][4:])
            elif block:
                break
            i += 1
        flow.append(Paragraph("<br/>".join(
            l.replace(" ", "&nbsp;").replace("&", "&amp;") for l in block), styles["code"]))
        flow.append(Spacer(1, 4))
        continue

    if line.startswith("### "):
        flow.append(Paragraph(inline(line[4:]), styles["h3"]))
    elif line.startswith("## "):
        flow.append(Paragraph(inline(line[3:]), styles["h2"]))
    elif line.startswith("# "):
        flow.append(Paragraph(inline(line[2:]), styles["h1"]))
    elif line.strip() == "---":
        flow.append(Spacer(1, 8))
    elif line.startswith("- "):
        flow.append(Paragraph(inline(line[2:]), styles["bullet"], bulletText="\u2022"))
    elif line.strip():
        flow.append(Paragraph(inline(line), styles["body"]))
    i += 1

doc = SimpleDocTemplate(str(out), pagesize=A4,
                        leftMargin=20 * mm, rightMargin=20 * mm,
                        topMargin=18 * mm, bottomMargin=18 * mm,
                        title="Clash Royale simulator handoff")
doc.build(flow)
print("wrote", out)
