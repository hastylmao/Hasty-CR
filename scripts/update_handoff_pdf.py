"""Create the current project handoff PDF from the verified simulator state."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "HastyCR Simulator Handoff.pdf"


def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def build(output: Path = OUTPUT) -> None:
    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title", parent=styles["Title"], fontName="Helvetica-Bold",
                           fontSize=25, leading=30, textColor=colors.HexColor("#172033"),
                           spaceAfter=8)
    subtitle = ParagraphStyle("Subtitle", parent=styles["BodyText"], fontSize=10.5,
                              leading=15, textColor=colors.HexColor("#4b5563"),
                              spaceAfter=16)
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Helvetica-Bold",
                        fontSize=16, leading=20, textColor=colors.HexColor("#172033"),
                        spaceBefore=12, spaceAfter=7)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold",
                        fontSize=11.5, leading=15, textColor=colors.HexColor("#26354f"),
                        spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9.4,
                          leading=14, spaceAfter=6)
    small = ParagraphStyle("Small", parent=body, fontSize=8.3, leading=11.5,
                           textColor=colors.HexColor("#4b5563"))
    callout = ParagraphStyle("Callout", parent=body, fontName="Helvetica-Bold",
                             textColor=colors.HexColor("#9f1239"), backColor=colors.HexColor("#fff1f2"),
                             borderColor=colors.HexColor("#fecdd3"), borderWidth=0.6,
                             borderPadding=8, spaceBefore=4, spaceAfter=10)
    table_text = ParagraphStyle("Table", parent=body, fontSize=8.6, leading=11)

    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=17 * mm,
                            leftMargin=17 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title="Clash Royale simulator handoff", author="HastyCR")
    story = [
        paragraph("Clash Royale simulator: current handoff", title),
        paragraph("Evidence-based Python simulator status, updated 20 August 2026. "
                  "Scope: simulator only; no emulator or live-bot behavior was changed.", subtitle),
        paragraph("1. Current position", h1),
    ]
    rows = [
        ("Public card catalogue", "120 RoyaleAPI public cards; every one maps uniquely to shipped client data"),
        ("Random deck viewer", "119 resolvable public cards sampled into unique 8-card decks; Party Rocket excluded because its graph is quarantined"),
        ("Local client data", "207 card rows parsed; 176 deployable units clear in the top-level raw-field scan"),
        ("Spells", "27 resolvable spell actions; zero unresolved public spell rows"),
        ("Remaining source graphs", "9, all named and explicitly blocked on live collision or trajectory calibration"),
        ("RL readiness", "NOT READY - controlled live geometry/contact/projectile evidence is still required"),
        ("Tests", "1308 passing plus 2 pinned gaps; board symmetry, elixir rates, determinism, speed units and parser anchoring now pinned"),
        ("Fixed this shift", "Mirror resolved cards at level 12, where all 37 verified combat_rules overrides stopped applying - a mirrored Evolved Witch had 922 hitpoints against a verified 1451. Verified values are now carried along the client curve and are exact at the level they were verified at"),
        ("Capture plan", "python -m sim.probe_plan prints 18 controlled clips, each paired with the engine's current prediction"),
        ("Known measurement hazard", "self-play A/B is seat-confounded: BrainPolicy wins 60.5% from the bottom seat (z=+3.69) though the board is provably symmetric"),
    ]
    table = Table([[paragraph(a, table_text), paragraph(b, table_text)] for a, b in rows],
                  colWidths=[48 * mm, 122 * mm], repeatRows=0)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [table, Spacer(1, 8),
              paragraph("The simulator is approximately 80% complete for a credible RL environment. "
                        "The remaining risk is shared game physics and timing, not basic card-stat coverage.", callout)]

    story += [paragraph("2. What is implemented", h1),
              paragraph("The simulator reads shipped Supercell CSV/TOML data and a versioned RoyaleAPI card snapshot. "
                        "It covers charge, invulnerable dashes, shields, splash, projectile flight, death damage/spawns, "
                        "periodic spawners, timed buffs, knockback, burrowing, tower windup, pathfinding, spells, "
                        "evolutions, champions and current hero action handlers.", body),
              paragraph("The viewer now supports <b>--random-decks</b>. It builds two random public-card decks and uses a generic legal-placement policy. "
                        "That policy now presses an engaged champion/hero ability when it is legal, so Golden Knight's paid dash is exercised instead of being silently ignored.", body),
              paragraph("Viewer command", h2),
              paragraph(".\\.venvs\\buildabot\\Scripts\\python.exe -m sim.watch --random-decks --seed 8 --speed 2", small),
              paragraph("Seed 8 includes Golden Knight in the bottom deck. The dash occurs after deployment, engagement and sufficient ability elixir.", small)]

    story += [paragraph("3. Evidence and verification added", h1),
              paragraph("Nineteen user-supplied MuMu gameplay recordings were catalogued with source paths, dimensions, frame counts and SHA-256 hashes. "
                        "All hashes currently verify. The clips are approximately 30 fps with overlapping play, so they remain contextual evidence only - not calibration proof.", body),
              paragraph("The calibration workflow now includes: recording inventory; motion-event triage; exact frame export with source hash provenance; "
                        "source-file hash verification; and a strict readiness gate. Accepted evidence must cite a controlled 50+ fps capture, valid source frames, card levels/deployment, observed outcome and a real pytest regression test.", body),
              paragraph("Recent checks", h2),
              paragraph("Core simulator/viewer/deck/ability regression suite: passing. Random-deck visual smoke run: passing. "
                        "Recording hash verification: 19/19 passing. Catalogue audit: 120/120 public cards mapped. "
                        "Run <b>python -m sim.readiness</b> for the current strict training gate.", body)]

    story += [PageBreak(), paragraph("4. What must be done next", h1),
              paragraph("Do not fill these gaps with guessed sprite boxes, collision constants or projectile paths. Capture isolated 60 fps controlled clips, then calibrate and regression-test each result.", callout),
              paragraph("Shared calibration matrix", h2)]
    matrix = [
        ("Map anchors", "Tower centres, river, bridges and legal deployment boundary"),
        ("Troop contact", "Same-size/mixed-size contacts, including King Tower and open-lane cases"),
        ("Building contact", "Routes and contact around Cannon, Tesla and Goblin Cage"),
        ("Projectile timing", "Moving/stationary targets for homing and non-homing shots"),
        ("Spell timing", "Fireball, Arrows, Zap and Tornado cast-to-impact/miss behavior"),
    ]
    matrix_table = Table([[paragraph(a, table_text), paragraph(b, table_text)] for a, b in matrix],
                         colWidths=[48 * mm, 122 * mm])
    matrix_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2ff")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c7d2fe")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [matrix_table, paragraph("Nine named mechanics also remain calibration-gated", h2),
              paragraph("Executioner Evolution returning axe; Goblin Drill Evolution emergence; Princess Evolution trail; Hero Balloon payload; "
                        "Hero Magic Archer teleport/triple shot; Firecracker fan/deflection; Hero Mega Minion warp; Monk non-homing and spell reflection; Hero Wizard tornado pull.", body)]

    story += [paragraph("5. Handoff commands", h1),
              paragraph("python -m sim.coverage - current card/spell coverage", small),
              paragraph("python -m sim.action_audit - exact remaining source-graph calibration gates", small),
              paragraph("python -m sim.readiness - strict RL training readiness", small),
              paragraph("scripts/verify_live_probe_assets.py - verify recorded-video hashes", small),
              Spacer(1, 8),
              paragraph("Expected remaining effort: 1-3 focused engineering days after measurements for deterministic cleanup, plus 1-3 weeks for credible collision, placement, interception and timing parity. "
                        "Training should remain blocked until the probe matrix and the nine gates are evidenced and tested.", body)]

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
        canvas.line(17 * mm, 11 * mm, A4[0] - 17 * mm, 11 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(17 * mm, 7.5 * mm, "HastyCR simulator handoff - evidence-based status")
        canvas.drawRightString(A4[0] - 17 * mm, 7.5 * mm, f"Page {_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build()
