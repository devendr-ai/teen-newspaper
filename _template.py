"""
The Young Global Citizen Daily — 2-PAGE DAILY TEMPLATE (v3)
============================================================
Parameterized 2-page, 2-column newspaper generator. Fewer, deeper stories.

Usage:
    python3 _template.py [content.json] [output.pdf]

LAYOUT (frozen as of 2026-08-12 — two wide columns, ~264pt each):
  PAGE 1 — masthead drawn on canvas, then 2 columns:
      col 1 : LEAD story  + custom map + "Why this matters"
      col 2 : story A     + illustration + "Connect the dots"
  PAGE 2 — banner, then 2 columns:
      col 1 : story D (India) + "Also in India" + briefs + Vocabulary
      col 2 : story E (US) + bar chart + extras + Did You Know
              + Sports + Watchlist + sign-off

Four news items per issue: lead, story A, India, US. Any extra entries in
p1_stories beyond index 0 are ignored by the layout.

The 3-column layout is preserved as _template_3col_archive.py.

The template enforces:
  * Per-slot character budgets (validate_content)
  * Strict motif validation — an unknown illustration motif raises rather
    than silently rendering a blank card
  * Auto-shrink retry if the PDF overflows 2 pages (build_with_retries)
  * Hard gates: page_count == 2 AND no '[IMAGE:'/'[CHART:'/'[MAP:'/'[PHOTO:'

The 4-page every-other-day template is preserved as _template_4page_archive.py.
"""
import datetime as _dt
import json
import os
import re
import sys

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    PageBreak, Table, TableStyle, NextPageTemplate, FrameBreak, Flowable
)

PAGE_W, PAGE_H = letter  # 612 x 792
PAGE_COUNT = 2

# ---------- Color palette ----------
INK       = colors.HexColor("#1A1A1A")
ACCENT    = colors.HexColor("#A6192E")
SECONDARY = colors.HexColor("#0B3D5C")
MUTED     = colors.HexColor("#6B6B6B")
PAPER     = colors.HexColor("#FAF7F1")
LIGHTBG   = colors.HexColor("#F1EBDD")

# ---------- Layout constants ----------
LEFT_M, RIGHT_M = 0.5*inch, 0.5*inch
TOP_M,  BOT_M   = 0.5*inch, 0.5*inch
CONTENT_W = PAGE_W - LEFT_M - RIGHT_M          # 540 pt
MAST_H    = 1.55*inch
GUTTER    = 0.16*inch
NCOLS     = 2
COL_W     = (CONTENT_W - (NCOLS - 1)*GUTTER) / float(NCOLS)   # ~264 pt

# ---------- Per-slot character budgets (tuned for a 264pt column) ----------
# Scaled ~1.5x from the 3-column era: a wider measure fits more characters
# per line, so each story can run longer without adding vertical height.
BUDGETS = {
    "lead_kicker":     40,
    "lead_headline":   70,
    "lead_deck":      260,
    "lead_byline":     40,
    "lead_body":     1150,
    "lead_why":       720,
    "story_kicker":    40,
    "story_headline":  90,
    "story_deck":     260,
    "story_body":    1150,
    "story_extra":    900,   # why / connect / analyst on a full-size story
    "short_headline":  90,
    "short_body":     840,
    "also_item":      240,
    "vocab_word":      28,
    "vocab_def":      260,
    "did_you_know":   480,
    "brief":          200,
    "sports_body":    560,
    "watch_item":     180,
}

# ---------- Styles ----------
_styles = getSampleStyleSheet()
section_tag = ParagraphStyle('SectionTag', fontName='Helvetica-Bold', fontSize=7.5,
    leading=9, alignment=TA_LEFT, textColor=ACCENT, spaceAfter=2, letterSpacing=1.5)
headline_big = ParagraphStyle('HeadlineBig', fontName='Times-Bold', fontSize=19,
    leading=21, alignment=TA_LEFT, textColor=INK, spaceAfter=4)
headline_med = ParagraphStyle('HeadlineMed', fontName='Times-Bold', fontSize=13,
    leading=15, alignment=TA_LEFT, textColor=INK, spaceAfter=3)
headline_sm = ParagraphStyle('HeadlineSm', fontName='Times-Bold', fontSize=10.5,
    leading=12, alignment=TA_LEFT, textColor=INK, spaceAfter=1)
deck_style = ParagraphStyle('Deck', fontName='Times-Italic', fontSize=9.5,
    leading=12, alignment=TA_LEFT, textColor=SECONDARY, spaceAfter=5)
byline_style = ParagraphStyle('Byline', fontName='Helvetica-Oblique', fontSize=7.5,
    leading=9, alignment=TA_LEFT, textColor=MUTED, spaceAfter=3)
body_style = ParagraphStyle('Body', fontName='Times-Roman', fontSize=9,
    leading=11.5, alignment=TA_JUSTIFY, textColor=INK, spaceAfter=4, firstLineIndent=9)
body_lead = ParagraphStyle('BodyLead', fontName='Times-Roman', fontSize=9,
    leading=11.5, alignment=TA_JUSTIFY, textColor=INK, spaceAfter=4)
why_title = ParagraphStyle('WhyTitle', fontName='Helvetica-Bold', fontSize=8,
    leading=10, alignment=TA_LEFT, textColor=ACCENT, spaceAfter=2, letterSpacing=1)
why_body = ParagraphStyle('WhyBody', fontName='Times-Roman', fontSize=8.5,
    leading=10.5, alignment=TA_LEFT, textColor=INK, spaceAfter=2)
caption_style = ParagraphStyle('Caption', fontName='Helvetica-Oblique', fontSize=6.5,
    leading=8, alignment=TA_LEFT, textColor=MUTED, spaceAfter=2)
sign_style = ParagraphStyle('Sign', fontName='Times-Italic', fontSize=7.5,
    leading=9.5, alignment=TA_CENTER, textColor=MUTED)
banner_style = ParagraphStyle('Banner', fontName='Helvetica-Bold', fontSize=10,
    leading=12, textColor=SECONDARY, alignment=TA_CENTER)


# ============================================================
#  CUSTOM DRAWN FLOWABLES  (no external images — sandbox has no egress)
# ============================================================
class HRule(Flowable):
    def __init__(self, width, thickness=1, color=INK):
        Flowable.__init__(self)
        self.width = width
        self.thickness = thickness
        self.color = color
        self.height = thickness + 2
    def draw(self):
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, 1, self.width, 1)


class StyledMap(Flowable):
    """Stylized two-landmass map with a chokepoint / border marker."""
    def __init__(self, spec, width=COL_W, height=1.5*inch):
        Flowable.__init__(self)
        self.spec = spec or {}
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        c.setFillColor(colors.HexColor("#CDE4EF"))
        c.rect(0, 0, w, h, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#E3D6B3"))
        p = c.beginPath()
        p.moveTo(0, h); p.lineTo(w, h); p.lineTo(w, h*0.58)
        p.lineTo(w*0.72, h*0.63); p.lineTo(w*0.55, h*0.50)
        p.lineTo(w*0.40, h*0.64); p.lineTo(w*0.20, h*0.72); p.lineTo(0, h*0.70)
        p.close(); c.drawPath(p, stroke=0, fill=1)
        p = c.beginPath()
        p.moveTo(0, 0); p.lineTo(w, 0); p.lineTo(w, h*0.33)
        p.lineTo(w*0.78, h*0.36); p.lineTo(w*0.60, h*0.28)
        p.lineTo(w*0.42, h*0.38); p.lineTo(w*0.24, h*0.30); p.lineTo(0, h*0.28)
        p.close(); c.drawPath(p, stroke=0, fill=1)
        c.setStrokeColor(ACCENT); c.setLineWidth(1.6); c.setDash(4, 2)
        c.line(w*0.04, h*0.46, w*0.96, h*0.46); c.setDash()
        c.setFillColor(ACCENT); c.circle(w*0.48, h*0.46, 3.5, stroke=0, fill=1)
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 7)
        c.drawRightString(w*0.96, h*0.86, self.spec.get("label_top", ""))
        c.drawString(w*0.04, h*0.09, self.spec.get("label_bottom", ""))
        c.setFont("Helvetica-Bold", 6.5); c.setFillColor(ACCENT)
        c.drawCentredString(w*0.50, h*0.51, self.spec.get("title", ""))
        c.setFillColor(SECONDARY); c.setFont("Helvetica-Oblique", 6)
        c.drawString(w*0.03, h*0.39, self.spec.get("footnote", ""))
        c.setStrokeColor(INK); c.setLineWidth(0.5)
        c.rect(0, 0, w, h, stroke=1, fill=0)


class BarChart(Flowable):
    """Bar chart driven by real numbers from the day's reporting."""
    def __init__(self, spec, width=COL_W, height=1.7*inch):
        Flowable.__init__(self)
        self.spec = spec or {}
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        s = self.spec
        c.setFillColor(PAPER); c.rect(0, 0, w, h, stroke=0, fill=1)
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 7.5)
        c.drawString(6, h-12, s.get("title", "")[:46])
        c.setFont("Helvetica-Oblique", 6); c.setFillColor(MUTED)
        c.drawString(6, h-20, s.get("subtitle", "")[:52])
        margin_l, margin_b = 26, 24
        chart_w = w - margin_l - 8
        chart_h = h - margin_b - 32
        c.setStrokeColor(INK); c.setLineWidth(0.6)
        c.line(margin_l, margin_b, margin_l, margin_b + chart_h)
        c.line(margin_l, margin_b, margin_l + chart_w, margin_b)
        labels = s.get("labels", [])
        values = s.get("values", [])
        if not values:
            return
        max_v = s.get("max") or max(values)
        prefix = s.get("value_prefix", "")
        hi = s.get("highlight_after", -1)
        bar_w = chart_w / (len(values) * 1.8)
        gap = (chart_w - bar_w*len(values)) / (len(values)+1)
        for i, v in enumerate(values):
            x = margin_l + gap + i*(bar_w + gap)
            bar_h = (v / max_v) * chart_h
            c.setFillColor(ACCENT if i > hi else SECONDARY)
            c.rect(x, margin_b, bar_w, bar_h, stroke=0, fill=1)
            c.setFillColor(INK); c.setFont("Helvetica-Bold", 6)
            c.drawCentredString(x + bar_w/2, margin_b + bar_h + 2, f"{prefix}{v}")
            c.setFont("Helvetica", 5.5); c.setFillColor(MUTED)
            lab = labels[i] if i < len(labels) else ""
            c.drawCentredString(x + bar_w/2, margin_b - 8, lab.replace("\n", " ")[:14])
        c.setFillColor(MUTED); c.setFont("Helvetica", 5)
        for v in (0, max_v*0.5, max_v):
            y = margin_b + (v / max_v) * chart_h
            c.line(margin_l - 2, y, margin_l, y)
            c.drawRightString(margin_l - 3, y-1.5, f"{prefix}{int(v)}")
        c.setStrokeColor(INK); c.setLineWidth(0.5)
        c.rect(0, 0, w, h, stroke=1, fill=0)


class IllustrationCard(Flowable):
    """Drawn editorial illustration. Every registered motif paints a full
    scene edge-to-edge — there is no blank fallback. An unknown motif is a
    build-time error (see validate_content), never a blank card."""

    def __init__(self, spec, width=COL_W, height=1.15*inch):
        Flowable.__init__(self)
        self.spec = spec or {}
        self.width = width
        self.height = height

    # ---- shared scene helpers -------------------------------------
    @staticmethod
    def _sky(c, w, h, top="#BBD7E8", horizon=0.42, ground="#D8CFAE"):
        c.setFillColor(colors.HexColor(top))
        c.rect(0, h*horizon, w, h*(1-horizon), stroke=0, fill=1)
        c.setFillColor(colors.HexColor(ground))
        c.rect(0, 0, w, h*horizon, stroke=0, fill=1)

    @staticmethod
    def _sun(c, w, h, x=0.80, y=0.78, r=9, col="#E8A33C"):
        c.setFillColor(colors.HexColor(col))
        c.circle(w*x, h*y, r, stroke=0, fill=1)

    @staticmethod
    def _waves(c, w, h, tops, col="#FAF7F1"):
        c.setStrokeColor(colors.HexColor(col)); c.setLineWidth(0.7)
        for y in tops:
            x = 0
            while x < w:
                c.line(x, y, x+6, y+1.4); c.line(x+6, y+1.4, x+12, y)
                x += 12

    # ---- motifs ---------------------------------------------------
    def _draw_ship(self, c, w, h):
        self._sky(c, w, h, "#BBD7E8", 0.46, "#8FBCD4")
        self._sun(c, w, h)
        c.setFillColor(colors.HexColor("#1F2D3A"))
        c.rect(w*0.08, h*0.30, w*0.58, h*0.11, stroke=0, fill=1)
        p = c.beginPath()
        p.moveTo(w*0.66, h*0.30); p.lineTo(w*0.78, h*0.36)
        p.lineTo(w*0.66, h*0.41); p.close()
        c.drawPath(p, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#FAF7F1"))
        c.rect(w*0.14, h*0.41, w*0.11, h*0.12, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#A6192E"))
        c.rect(w*0.185, h*0.53, w*0.02, h*0.09, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#3A4A57"))
        for i in range(5):
            c.rect(w*(0.30+i*0.07), h*0.41, w*0.05, h*0.07, stroke=0, fill=1)
        self._waves(c, w, h, (h*0.10, h*0.20))

    def _draw_strait(self, c, w, h):
        c.setFillColor(colors.HexColor("#8FBCD4"))
        c.rect(0, 0, w, h, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#C9B98C"))
        p = c.beginPath()
        p.moveTo(0, h); p.lineTo(w, h); p.lineTo(w, h*0.66)
        p.lineTo(w*0.66, h*0.60); p.lineTo(w*0.34, h*0.72); p.lineTo(0, h*0.68)
        p.close(); c.drawPath(p, stroke=0, fill=1)
        p = c.beginPath()
        p.moveTo(0, 0); p.lineTo(w, 0); p.lineTo(w, h*0.30)
        p.lineTo(w*0.62, h*0.36); p.lineTo(w*0.30, h*0.24); p.lineTo(0, h*0.30)
        p.close(); c.drawPath(p, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#7A6E4E"))
        p = c.beginPath()
        p.moveTo(w*0.16, h*0.68); p.lineTo(w*0.24, h*0.92); p.lineTo(w*0.32, h*0.68)
        p.close(); c.drawPath(p, stroke=0, fill=1)
        p = c.beginPath()
        p.moveTo(w*0.68, h*0.30); p.lineTo(w*0.76, h*0.08); p.lineTo(w*0.84, h*0.30)
        p.close(); c.drawPath(p, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#1F2D3A"))
        c.rect(w*0.42, h*0.46, w*0.14, h*0.05, stroke=0, fill=1)
        self._waves(c, w, h, (h*0.40, h*0.56), "#E9F3F8")

    def _draw_border(self, c, w, h):
        self._sky(c, w, h, "#D9C9A8", 0.34, "#C4A97E")
        self._sun(c, w, h, 0.16, 0.80, 8, "#E8A33C")
        c.setStrokeColor(colors.HexColor("#4A4A4A")); c.setLineWidth(1.4)
        for i in range(6):
            x = w*(0.08 + i*0.17)
            c.line(x, h*0.34, x, h*0.80)
        c.setLineWidth(0.5)
        for j in range(9):
            y = h*(0.36 + j*0.05)
            c.line(w*0.05, y, w*0.95, y)
        c.setFillColor(colors.HexColor("#1F2D3A"))
        for i in range(11):
            x = w*(0.05 + i*0.085)
            c.circle(x, h*0.24, 3, stroke=0, fill=1)
            c.rect(x-2.5, h*0.06, 5, h*0.16, stroke=0, fill=1)

    def _draw_fire(self, c, w, h):
        c.setFillColor(colors.HexColor("#B14A2A"))
        c.rect(0, h*0.38, w, h*0.62, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#E8A33C"))
        c.rect(0, h*0.38, w, h*0.22, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#3B2A22"))
        c.rect(0, 0, w, h*0.38, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#1A1A1A"))
        for i in range(9):
            x = w*(0.04 + i*0.11)
            p = c.beginPath()
            p.moveTo(x-5, h*0.38); p.lineTo(x, h*0.38 + h*(0.16 + (i % 3)*0.05))
            p.lineTo(x+5, h*0.38); p.close()
            c.drawPath(p, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#E8532A"))
        for i in range(7):
            x = w*(0.08 + i*0.14)
            p = c.beginPath()
            p.moveTo(x-4, h*0.30); p.lineTo(x, h*0.30 + h*(0.14 + (i % 2)*0.06))
            p.lineTo(x+4, h*0.30); p.close()
            c.drawPath(p, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#0E0C0A"))
        for i in range(3):
            x = w*(0.14 + i*0.30)
            c.rect(x, h*0.06, w*0.12, h*0.11, stroke=0, fill=1)
            p = c.beginPath()
            p.moveTo(x-3, h*0.17); p.lineTo(x + w*0.06, h*0.25)
            p.lineTo(x + w*0.12 + 3, h*0.17); p.close()
            c.drawPath(p, stroke=0, fill=1)

    def _draw_flood(self, c, w, h):
        self._sky(c, w, h, "#9BA9B4", 0.50, "#6E8A9C")
        c.setFillColor(colors.HexColor("#7E6A4E"))
        c.rect(0, h*0.50, w, h*0.06, stroke=0, fill=1)
        for i in range(3):
            x = w*(0.10 + i*0.30)
            c.setFillColor(colors.HexColor("#EDE5D2"))
            c.rect(x, h*0.36, w*0.14, h*0.20, stroke=0, fill=1)
            c.setFillColor(colors.HexColor("#A6192E"))
            p = c.beginPath()
            p.moveTo(x-3, h*0.56); p.lineTo(x + w*0.07, h*0.68)
            p.lineTo(x + w*0.14 + 3, h*0.56); p.close()
            c.drawPath(p, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#5C7C90"))
        c.rect(0, 0, w, h*0.42, stroke=0, fill=1)
        self._waves(c, w, h, (h*0.12, h*0.26, h*0.38), "#BBD7E8")
        c.setFillColor(colors.HexColor("#1F2D3A"))
        p = c.beginPath()
        p.moveTo(w*0.60, h*0.30); p.lineTo(w*0.82, h*0.30)
        p.lineTo(w*0.78, h*0.22); p.lineTo(w*0.64, h*0.22); p.close()
        c.drawPath(p, stroke=0, fill=1)

    def _draw_grid(self, c, w, h):
        c.setFillColor(colors.HexColor("#141C26"))
        c.rect(0, 0, w, h, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#232F3D"))
        c.rect(0, 0, w, h*0.26, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#0A1119"))
        heights = [0.42, 0.30, 0.55, 0.38, 0.62, 0.34, 0.48]
        bw = w / len(heights)
        for i, hh in enumerate(heights):
            c.rect(i*bw, h*0.26, bw-2, h*hh, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#E8A33C"))
        for (i, j) in ((0, 1), (2, 3), (4, 2), (6, 1)):
            c.rect(i*bw + 4, h*(0.30 + j*0.08), 3, 4, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#6B7C8C")); c.setLineWidth(1.2)
        cx = w*0.78
        c.line(cx-8, h*0.26, cx-3, h*0.88); c.line(cx+8, h*0.26, cx+3, h*0.88)
        for y in (0.40, 0.56, 0.72):
            c.line(cx-6.5, h*y, cx+6.5, h*y)
        c.setLineWidth(0.7)
        c.line(0, h*0.80, cx-4, h*0.86); c.line(cx+4, h*0.86, w, h*0.80)

    def _draw_ballot(self, c, w, h):
        c.setFillColor(colors.HexColor("#E8DFC2"))
        c.rect(0, 0, w, h, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#0B3D5C"))
        c.rect(w*0.28, h*0.12, w*0.44, h*0.42, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#08293E"))
        c.rect(w*0.28, h*0.50, w*0.44, h*0.06, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#1A1A1A"))
        c.rect(w*0.44, h*0.535, w*0.12, h*0.02, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#FAF7F1"))
        c.rect(w*0.42, h*0.56, w*0.16, h*0.24, stroke=0, fill=1)
        c.setStrokeColor(MUTED); c.setLineWidth(0.5)
        for j in range(4):
            c.line(w*0.445, h*(0.62 + j*0.04), w*0.555, h*(0.62 + j*0.04))
        c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(w*0.50, h*0.745, "X")
        c.setFillColor(colors.HexColor("#3A4A57"))
        for i in range(4):
            x = w*(0.06 + i*0.055)
            c.circle(x, h*0.34, 2.5, stroke=0, fill=1)
            c.rect(x-2, h*0.18, 4, h*0.14, stroke=0, fill=1)

    def _draw_airdefense(self, c, w, h):
        c.setFillColor(colors.HexColor("#101826"))
        c.rect(0, 0, w, h, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#1C2A3A"))
        c.rect(0, 0, w, h*0.22, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#4A5A68"))
        c.rect(w*0.10, h*0.16, w*0.20, h*0.10, stroke=0, fill=1)
        c.saveState()
        c.translate(w*0.20, h*0.26); c.rotate(52)
        c.setFillColor(colors.HexColor("#8A99A6"))
        c.rect(-4, 0, 8, h*0.34, stroke=0, fill=1)
        c.restoreState()
        c.setStrokeColor(colors.HexColor("#E8A33C")); c.setLineWidth(1.2)
        c.line(w*0.24, h*0.34, w*0.56, h*0.86)
        c.setStrokeColor(colors.HexColor("#A6192E")); c.setLineWidth(1.0); c.setDash(3, 2)
        for x0, y0 in ((0.98, 0.92), (0.86, 0.96), (0.72, 0.90)):
            c.line(w*x0, h*y0, w*(x0-0.28), h*(y0-0.52))
        c.setDash()
        c.setFillColor(colors.HexColor("#F2D06B"))
        c.circle(w*0.56, h*0.86, 5, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#FAF7F1"))
        c.circle(w*0.56, h*0.86, 2, stroke=0, fill=1)

    def _draw_rocket(self, c, w, h):
        c.setFillColor(colors.HexColor("#0B1626"))
        c.rect(0, 0, w, h, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#FAF7F1"))
        for (x, y, r) in ((0.10, 0.86, 0.8), (0.28, 0.72, 0.6), (0.86, 0.80, 0.9),
                          (0.66, 0.92, 0.6), (0.44, 0.62, 0.5)):
            c.circle(w*x, h*y, r, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#D8D3C4"))
        p = c.beginPath()
        p.moveTo(w*0.50, h*0.92); p.lineTo(w*0.56, h*0.60)
        p.lineTo(w*0.44, h*0.60); p.close()
        c.drawPath(p, stroke=0, fill=1)
        c.rect(w*0.44, h*0.34, w*0.12, h*0.26, stroke=0, fill=1)
        c.setFillColor(ACCENT)
        p = c.beginPath()
        p.moveTo(w*0.44, h*0.40); p.lineTo(w*0.36, h*0.28)
        p.lineTo(w*0.44, h*0.30); p.close(); c.drawPath(p, stroke=0, fill=1)
        p = c.beginPath()
        p.moveTo(w*0.56, h*0.40); p.lineTo(w*0.64, h*0.28)
        p.lineTo(w*0.56, h*0.30); p.close(); c.drawPath(p, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#E8A33C"))
        p = c.beginPath()
        p.moveTo(w*0.45, h*0.34); p.lineTo(w*0.50, h*0.06)
        p.lineTo(w*0.55, h*0.34); p.close(); c.drawPath(p, stroke=0, fill=1)

    def _draw_podium(self, c, w, h):
        c.setFillColor(colors.HexColor("#E8DFC2"))
        c.rect(0, 0, w, h, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#D6CBAF"))
        c.rect(0, 0, w, h*0.16, stroke=0, fill=1)
        blocks = ((0.14, 0.30, "#B08D57", "3"), (0.40, 0.52, "#C9A227", "1"),
                  (0.66, 0.40, "#9AA5AD", "2"))
        for x, bh, col, num in blocks:
            c.setFillColor(colors.HexColor(col))
            c.rect(w*x, h*0.16, w*0.20, h*bh, stroke=0, fill=1)
            c.setFillColor(colors.HexColor("#3A2E14")); c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(w*(x+0.10), h*0.22, num)
            c.setFillColor(colors.HexColor("#1F2D3A"))
            c.circle(w*(x+0.10), h*(0.16+bh)+9, 3.2, stroke=0, fill=1)
            c.rect(w*(x+0.10)-3, h*(0.16+bh), 6, 8, stroke=0, fill=1)
        c.setStrokeColor(ACCENT); c.setLineWidth(1)
        c.line(0, h*0.94, w, h*0.94)

    def _draw_cricket(self, c, w, h):
        c.setFillColor(colors.HexColor("#6FA96F"))
        c.rect(0, 0, w, h, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#FAF7F1")); c.setLineWidth(1.4)
        c.circle(w*0.5, h*0.45, min(w, h)*0.52, stroke=1, fill=0)
        c.setFillColor(colors.HexColor("#D9C68A"))
        c.rect(w*0.44, h*0.14, w*0.12, h*0.62, stroke=0, fill=1)
        c.setStrokeColor(INK); c.setLineWidth(1)
        for x in (w*0.465, w*0.50, w*0.535):
            c.line(x, h*0.14, x, h*0.26)
            c.line(x, h*0.64, x, h*0.76)
        c.setFillColor(colors.HexColor("#1F2D3A"))
        c.circle(w*0.62, h*0.34, 3, stroke=0, fill=1)
        c.rect(w*0.605, h*0.16, 3, h*0.16, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#8A6A3A")); c.setLineWidth(2.2)
        c.line(w*0.63, h*0.30, w*0.70, h*0.16)
        c.setFillColor(ACCENT)
        c.circle(w*0.30, h*0.50, 3, stroke=0, fill=1)

    def _draw_skyline(self, c, w, h):
        self._sky(c, w, h, "#C6D9E8", 0.14, "#B4C4D2")
        c.setFillColor(colors.HexColor("#0B3D5C"))
        heights = [0.45, 0.32, 0.58, 0.40, 0.68, 0.36, 0.52, 0.30]
        bw = w / len(heights)
        for i, hh in enumerate(heights):
            c.rect(i*bw, h*0.14, bw-2, h*hh, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#E8DFC2"))
        for i, hh in enumerate(heights):
            for j in range(int(hh*7)):
                if (i + j) % 3 == 0:
                    c.rect(i*bw + 4, h*(0.18 + j*0.07), 2.5, 3, stroke=0, fill=1)
        c.setFillColor(ACCENT)
        c.rect(w*0.505, h*0.72, 2, h*0.20, stroke=0, fill=1)
        c.circle(w*0.512, h*0.92, 3.5, stroke=0, fill=1)

    def _draw_capitol(self, c, w, h):
        self._sky(c, w, h, "#CBDCEA", 0.16, "#BFC9B4")
        c.setFillColor(colors.HexColor("#FAF7F1"))
        c.rect(w*0.08, h*0.16, w*0.84, h*0.22, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#E0D9C2"))
        for i in range(8):
            c.rect(w*(0.14 + i*0.095), h*0.38, w*0.030, h*0.18, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#FAF7F1"))
        p = c.beginPath()
        p.moveTo(w*0.12, h*0.56); p.lineTo(w*0.88, h*0.56)
        p.lineTo(w*0.50, h*0.66); p.close(); c.drawPath(p, stroke=0, fill=1)
        c.circle(w*0.50, h*0.74, h*0.11, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#E0D9C2"))
        c.rect(w*0.40, h*0.66, w*0.20, h*0.06, stroke=0, fill=1)
        c.setFillColor(ACCENT)
        c.rect(w*0.495, h*0.84, w*0.01, h*0.10, stroke=0, fill=1)
        c.rect(w*0.505, h*0.88, w*0.05, h*0.05, stroke=0, fill=1)

    def _draw_robot(self, c, w, h):
        self._sky(c, w, h, "#DDE5EF", 0.20, "#C9C2AC")
        c.setFillColor(colors.HexColor("#0B3D5C"))
        c.rect(w*0.40, h*0.34, w*0.20, h*0.28, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#1A1A1A"))
        c.rect(w*0.42, h*0.64, w*0.16, h*0.16, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#E8A33C"))
        c.circle(w*0.46, h*0.72, 2, stroke=0, fill=1)
        c.circle(w*0.54, h*0.72, 2, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#0B3D5C")); c.setLineWidth(3)
        c.line(w*0.40, h*0.58, w*0.26, h*0.46)
        c.line(w*0.60, h*0.58, w*0.74, h*0.64)
        c.line(w*0.45, h*0.34, w*0.34, h*0.20)
        c.line(w*0.55, h*0.34, w*0.66, h*0.20)
        c.setStrokeColor(colors.HexColor("#8A99A6")); c.setLineWidth(0.8)
        c.line(w*0.50, h*0.80, w*0.50, h*0.88)
        c.setFillColor(ACCENT); c.circle(w*0.50, h*0.89, 2, stroke=0, fill=1)
        c.setStrokeColor(MUTED); c.setLineWidth(0.6)
        for y in (0.42, 0.52, 0.62):
            c.line(w*0.04, h*y, w*0.18, h*y)

    def _draw_farm(self, c, w, h):
        self._sky(c, w, h, "#CFE0EC", 0.44, "#D4B96A")
        self._sun(c, w, h, 0.82, 0.80, 9, "#E8A33C")
        c.setStrokeColor(colors.HexColor("#A98F45")); c.setLineWidth(0.8)
        for i in range(14):
            x = w*(0.03 + i*0.072)
            c.line(x, 0, x, h*(0.16 + (i % 3)*0.05))
        c.setFillColor(colors.HexColor("#A6192E"))
        c.rect(w*0.08, h*0.44, w*0.20, h*0.16, stroke=0, fill=1)
        p = c.beginPath()
        p.moveTo(w*0.06, h*0.60); p.lineTo(w*0.18, h*0.72)
        p.lineTo(w*0.30, h*0.60); p.close(); c.drawPath(p, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#3B2A22"))
        c.rect(w*0.15, h*0.44, w*0.06, h*0.10, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#6B5A2A")); c.setLineWidth(1)
        c.line(0, h*0.44, w, h*0.44)

    def _draw_globe(self, c, w, h):
        c.setFillColor(colors.HexColor("#0B1626"))
        c.rect(0, 0, w, h, stroke=0, fill=1)
        r = min(w, h)*0.36
        c.setFillColor(colors.HexColor("#1E5A7A"))
        c.circle(w*0.50, h*0.50, r, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#4E8C5A"))
        c.circle(w*0.44, h*0.58, r*0.34, stroke=0, fill=1)
        c.circle(w*0.60, h*0.44, r*0.26, stroke=0, fill=1)
        c.circle(w*0.38, h*0.36, r*0.20, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#8FBCD4")); c.setLineWidth(0.5)
        c.circle(w*0.50, h*0.50, r, stroke=1, fill=0)
        for f in (0.35, 0.68):
            c.line(w*0.50 - r, h*0.50 - r + 2*r*f, w*0.50 + r, h*0.50 - r + 2*r*f)
        c.setStrokeColor(ACCENT); c.setLineWidth(0.9); c.setDash(3, 2)
        c.circle(w*0.50, h*0.50, r*1.28, stroke=1, fill=0); c.setDash()

    def _draw_court(self, c, w, h):
        self._sky(c, w, h, "#DDE5EF", 0.18, "#C4BCA6")
        c.setFillColor(colors.HexColor("#F2EDE0"))
        c.rect(w*0.10, h*0.18, w*0.80, h*0.20, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#E0D9C2"))
        for i in range(6):
            c.rect(w*(0.16 + i*0.125), h*0.38, w*0.035, h*0.24, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#F2EDE0"))
        p = c.beginPath()
        p.moveTo(w*0.12, h*0.62); p.lineTo(w*0.88, h*0.62)
        p.lineTo(w*0.50, h*0.76); p.close(); c.drawPath(p, stroke=0, fill=1)
        c.setStrokeColor(ACCENT); c.setLineWidth(1.2)
        c.line(w*0.50, h*0.80, w*0.50, h*0.94)
        c.line(w*0.38, h*0.92, w*0.62, h*0.92)
        c.line(w*0.38, h*0.92, w*0.38, h*0.86)
        c.line(w*0.62, h*0.92, w*0.62, h*0.86)
        c.setFillColor(ACCENT)
        c.circle(w*0.38, h*0.85, 2.6, stroke=0, fill=1)
        c.circle(w*0.62, h*0.85, 2.6, stroke=0, fill=1)

    def _draw_protest(self, c, w, h):
        self._sky(c, w, h, "#D3DCE4", 0.30, "#B9B3A2")
        c.setFillColor(colors.HexColor("#2A3744"))
        for i in range(13):
            x = w*(0.03 + i*0.076)
            c.circle(x, h*0.32 + (i % 3), 3.4, stroke=0, fill=1)
            c.rect(x-3, h*0.08, 6, h*0.22, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#4A4A4A")); c.setLineWidth(1)
        for x, ph in ((0.20, 0.62), (0.52, 0.70), (0.80, 0.58)):
            c.line(w*x, h*0.34, w*x, h*ph)
        c.setFillColor(colors.HexColor("#FAF7F1"))
        c.rect(w*0.13, h*0.62, w*0.16, h*0.14, stroke=0, fill=1)
        c.rect(w*0.45, h*0.70, w*0.16, h*0.14, stroke=0, fill=1)
        c.rect(w*0.73, h*0.58, w*0.16, h*0.14, stroke=0, fill=1)
        c.setStrokeColor(MUTED); c.setLineWidth(0.5)
        for bx, by in ((0.13, 0.62), (0.45, 0.70), (0.73, 0.58)):
            for j in range(3):
                c.line(w*(bx+0.02), h*(by+0.035+j*0.035),
                       w*(bx+0.14), h*(by+0.035+j*0.035))

    def _draw_hospital(self, c, w, h):
        self._sky(c, w, h, "#D8E6EF", 0.16, "#C2CBC4")
        c.setFillColor(colors.HexColor("#FAF7F1"))
        c.rect(w*0.14, h*0.16, w*0.72, h*0.58, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#BBD7E8"))
        for i in range(4):
            for j in range(3):
                c.rect(w*(0.20 + i*0.16), h*(0.24 + j*0.16), w*0.10, h*0.10,
                       stroke=0, fill=1)
        c.setFillColor(ACCENT)
        c.rect(w*0.46, h*0.78, w*0.08, h*0.16, stroke=0, fill=1)
        c.rect(w*0.42, h*0.82, w*0.16, h*0.08, stroke=0, fill=1)
        c.setStrokeColor(INK); c.setLineWidth(0.6)
        c.line(w*0.14, h*0.74, w*0.86, h*0.74)

    _MOTIFS = {
        "ship": _draw_ship,
        "strait": _draw_strait,
        "border": _draw_border,
        "fire": _draw_fire,
        "flood": _draw_flood,
        "grid": _draw_grid,
        "ballot": _draw_ballot,
        "airdefense": _draw_airdefense,
        "rocket": _draw_rocket,
        "podium": _draw_podium,
        "cricket": _draw_cricket,
        "skyline": _draw_skyline,
        "capitol": _draw_capitol,
        "robot": _draw_robot,
        "farm": _draw_farm,
        "globe": _draw_globe,
        "court": _draw_court,
        "protest": _draw_protest,
        "hospital": _draw_hospital,
    }

    @classmethod
    def known_motifs(cls):
        return sorted(cls._MOTIFS.keys())

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        motif = (self.spec or {}).get("motif", "")
        drawer = self._MOTIFS.get(motif)
        if drawer is None:
            raise ValueError(
                f"unknown illustration motif {motif!r}; "
                f"known: {', '.join(self.known_motifs())}")
        drawer(self, c, w, h)
        c.setStrokeColor(INK); c.setLineWidth(0.5)
        c.rect(0, 0, w, h, stroke=1, fill=0)
        title = (self.spec or {}).get("title", "")
        sub   = (self.spec or {}).get("subtitle", "Editorial illustration")
        c.setFillColor(colors.Color(0, 0, 0, alpha=0.58))
        c.rect(0, 0, w, 14, stroke=0, fill=1)
        c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 6.5)
        c.drawString(5, 5, title[:44])
        c.setFont("Helvetica-Oblique", 5.5); c.setFillColor(colors.HexColor("#DEDEDE"))
        c.drawRightString(w-5, 5, sub[:26])


# ============================================================
#  PAGE BACKGROUNDS
# ============================================================
def make_paper_background(date_str):
    def _bg(canv, doc):
        canv.saveState()
        canv.setFillColor(PAPER)
        canv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        canv.setFont("Helvetica", 6.5); canv.setFillColor(MUTED)
        canv.drawCentredString(
            PAGE_W/2, 0.32*inch,
            f"The Young Global Citizen Daily  •  {date_str}  •  "
            f"Page {canv.getPageNumber()} of {PAGE_COUNT}")
        canv.restoreState()
    return _bg


def make_page1_background(date_str, vol_str, location):
    paper_bg = make_paper_background(date_str)
    def _bg(canv, doc):
        paper_bg(canv, doc)
        canv.saveState()
        cx = PAGE_W / 2
        y = PAGE_H - 0.5*inch - 4
        canv.setStrokeColor(INK); canv.setLineWidth(0.6)
        canv.line(LEFT_M, y, PAGE_W - RIGHT_M, y)
        y -= 36
        canv.setFillColor(INK); canv.setFont("Times-Bold", 34)
        canv.drawCentredString(cx, y, "THE YOUNG GLOBAL CITIZEN")
        y -= 22
        canv.setFillColor(ACCENT); canv.setFont("Times-Italic", 18)
        canv.drawCentredString(cx, y, "D A I L Y")
        y -= 14
        canv.setFillColor(MUTED); canv.setFont("Times-Italic", 9.5)
        canv.drawCentredString(cx, y,
            "“News that helps you think like a global thinker.”")
        y -= 6
        canv.setStrokeColor(INK); canv.setLineWidth(1.5)
        canv.line(LEFT_M, y, PAGE_W - RIGHT_M, y)
        y -= 3; canv.setLineWidth(0.4)
        canv.line(LEFT_M, y, PAGE_W - RIGHT_M, y)
        y -= 10
        canv.setFillColor(INK); canv.setFont("Helvetica", 8)
        canv.drawCentredString(cx, y,
            f"{vol_str}  •  {date_str}  •  {location}  •  "
            f"{PAGE_COUNT} Pages")
        y -= 5; canv.setLineWidth(0.4)
        canv.line(LEFT_M, y, PAGE_W - RIGHT_M, y)
        canv.restoreState()
    return _bg


# ============================================================
#  CONTENT NORMALISATION + VALIDATION
# ============================================================
def _len_no_html(s):
    if not s:
        return 0
    return len(re.sub(r"<[^>]+>", "", s))


def normalize_content(content):
    """Accept the legacy 4-page schema and map it onto the 2-page one."""
    if "p1_stories" not in content:
        p1 = list(content.get("world_stories", []))
        if content.get("p1_right"):
            p1r = dict(content["p1_right"])
            p1r.setdefault("deck", "")
            p1.append(p1r)
        content["p1_stories"] = p1[:3]
    if "p2_stories" not in content:
        content["p2_stories"] = list(content.get("home_stories", []))[:2]
    learn = content.setdefault("learn", {})
    learn.setdefault("vocab", [])
    learn.setdefault("did_you_know", "")
    return content


_TAG_RE = re.compile(r"<(/?)([a-zA-Z]+)[^>]*>")


def _fit(text, budget):
    """Truncate `text` so its visible (non-HTML) length is <= budget, cutting
    at a word boundary and leaving no dangling or unclosed tags."""
    if not text or _len_no_html(text) <= budget:
        return text
    out, visible, i = [], 0, 0
    while i < len(text) and visible < budget:
        if text[i] == "<":
            j = text.find(">", i)
            if j == -1:
                break
            out.append(text[i:j+1]); i = j + 1
            continue
        out.append(text[i]); visible += 1; i += 1
    s = "".join(out)
    # back off to the last word boundary in the visible tail
    m = re.search(r"\s\S*$", s)
    if m and m.start() > len(s) * 0.6:
        s = s[:m.start()]
    s = re.sub(r"<[^>]*$", "", s).rstrip(" ,;:—-")
    # close any tags left open
    depth = []
    for mt in _TAG_RE.finditer(s):
        if mt.group(1):
            if depth and depth[-1] == mt.group(2):
                depth.pop()
        else:
            depth.append(mt.group(2))
    for tag in reversed(depth):
        s += f"</{tag}>"
    return s + "…"


def enforce_budgets(content):
    """Hard-fit every budgeted slot so validate_content cannot fail on length.
    Motif errors are deliberately NOT auto-fixed — those must be a build error."""
    lead = content["lead"]
    for k, b in (("kicker", "lead_kicker"), ("headline", "lead_headline"),
                 ("deck", "lead_deck"), ("byline", "lead_byline"),
                 ("why", "lead_why")):
        if lead.get(k):
            lead[k] = _fit(lead[k], BUDGETS[b])
    if lead.get("body"):
        lead["body"] = _fit_paragraphs(lead["body"], BUDGETS["lead_body"])

    p1 = content.get("p1_stories", [])
    for i, s in enumerate(p1):
        body_b = "story_body" if i == 0 else "short_body"
        head_b = "story_headline" if i == 0 else "short_headline"
        if s.get("kicker"):
            s["kicker"] = _fit(s["kicker"], BUDGETS["story_kicker"])
        s["headline"] = _fit(s["headline"], BUDGETS[head_b])
        if s.get("deck"):
            s["deck"] = _fit(s["deck"], BUDGETS["story_deck"])
        if s.get("body"):
            s["body"] = _fit_paragraphs(s["body"], BUDGETS[body_b])
        for k in ("why", "connect", "analyst"):
            if s.get(k):
                s[k] = _fit(s[k], BUDGETS["story_extra"])

    for s in content.get("p2_stories", []):
        if s.get("kicker"):
            s["kicker"] = _fit(s["kicker"], BUDGETS["story_kicker"])
        s["headline"] = _fit(s["headline"], BUDGETS["story_headline"])
        if s.get("deck"):
            s["deck"] = _fit(s["deck"], BUDGETS["story_deck"])
        if s.get("body"):
            s["body"] = _fit_paragraphs(s["body"], BUDGETS["story_body"])
        for k in ("why", "connect", "analyst"):
            if s.get(k):
                s[k] = _fit(s[k], BUDGETS["story_extra"])
        if s.get("also"):
            s["also"] = [_fit(a, BUDGETS["also_item"]) for a in s["also"]]

    learn = content["learn"]
    for v in learn.get("vocab", []):
        v["word"] = _fit(v["word"], BUDGETS["vocab_word"])
        v["def"] = _fit(v["def"], BUDGETS["vocab_def"])
    if learn.get("did_you_know"):
        learn["did_you_know"] = _fit(learn["did_you_know"], BUDGETS["did_you_know"])
    if content.get("briefs"):
        content["briefs"] = [_fit(b, BUDGETS["brief"]) for b in content["briefs"]]
    if content.get("sports", {}).get("body"):
        content["sports"]["body"] = _fit(content["sports"]["body"],
                                         BUDGETS["sports_body"])
    if content.get("watchlist"):
        content["watchlist"] = [_fit(w, BUDGETS["watch_item"])
                                for w in content["watchlist"]]
    return content


def _fit_paragraphs(paras, budget):
    """Fit a list of body paragraphs to a combined visible-character budget."""
    total = sum(_len_no_html(p) for p in paras) + max(0, len(paras) - 1)
    if total <= budget:
        return paras
    out, left = [], budget - max(0, len(paras) - 1)
    for p in paras:
        if left <= 0:
            break
        n = _len_no_html(p)
        if n <= left:
            out.append(p); left -= n
        else:
            if left > 120:
                out.append(_fit(p, left))
            left = 0
    return out or [_fit(paras[0], budget)]


def validate_content(content):
    """Raise ValueError listing every slot that exceeds its budget, and every
    illustration whose motif is unknown (which would render blank)."""
    errors = []

    def chk(value, key):
        n = _len_no_html(value)
        if n > BUDGETS[key]:
            errors.append(f"{key}: {n} chars (budget {BUDGETS[key]})")

    def chk_illustration(spec, where):
        if not spec:
            return
        motif = spec.get("motif", "")
        if motif not in IllustrationCard._MOTIFS:
            errors.append(
                f"{where}: illustration motif {motif!r} is not a drawable scene "
                f"(would render blank). Choose one of: "
                f"{', '.join(IllustrationCard.known_motifs())}")

    lead = content["lead"]
    chk(lead.get("kicker", ""),   "lead_kicker")
    chk(lead.get("headline", ""), "lead_headline")
    chk(lead.get("deck", ""),     "lead_deck")
    chk(lead.get("byline", ""),   "lead_byline")
    chk("\n".join(lead.get("body", [])), "lead_body")
    chk(lead.get("why", ""),      "lead_why")
    chk_illustration(lead.get("illustration"), "lead")

    p1 = content.get("p1_stories", [])
    for i, s in enumerate(p1):
        chk(s.get("kicker", ""), "story_kicker")
        body = "\n".join(s.get("body", []))
        if i == 0:
            chk(s.get("headline", ""), "story_headline")
            chk(s.get("deck", ""), "story_deck")
            chk(body, "story_body")
        else:
            chk(s.get("headline", ""), "short_headline")
            chk(s.get("deck", ""), "story_deck")
            chk(body, "short_body")
        for k in ("why", "connect", "analyst"):
            chk(s.get(k, ""), "story_extra")
        chk_illustration(s.get("illustration"), f"p1_stories[{i}]")

    for i, s in enumerate(content.get("p2_stories", [])):
        chk(s.get("kicker", ""),   "story_kicker")
        chk(s.get("headline", ""), "story_headline")
        chk(s.get("deck", ""),     "story_deck")
        chk("\n".join(s.get("body", [])), "story_body")
        for k in ("why", "connect", "analyst"):
            chk(s.get(k, ""), "story_extra")
        for a in s.get("also", []):
            chk(a, "also_item")
        chk_illustration(s.get("illustration"), f"p2_stories[{i}]")

    for v in content["learn"].get("vocab", []):
        chk(v["word"], "vocab_word")
        chk(v["def"],  "vocab_def")
    chk(content["learn"].get("did_you_know", ""), "did_you_know")
    for b in content.get("briefs", []):
        chk(b, "brief")
    chk(content.get("sports", {}).get("body", ""), "sports_body")
    for wch in content.get("watchlist", []):
        chk(wch, "watch_item")

    if errors:
        raise ValueError("Budget violations:\n  - " + "\n  - ".join(errors))


# ============================================================
#  STORY ASSEMBLY
# ============================================================
def _extras(out, s):
    for key, label in (("why", "WHY THIS MATTERS"),
                       ("connect", "CONNECT THE DOTS"),
                       ("analyst", "THINK LIKE AN ANALYST")):
        if s.get(key):
            out.append(Spacer(1, 4))
            out.append(Paragraph(label, why_title))
            out.append(Paragraph(s[key], why_body))


def _lead_block(content):
    out = []
    lead = content["lead"]
    out.append(Paragraph(lead["kicker"], section_tag))
    out.append(Paragraph(lead["headline"], headline_big))
    if lead.get("deck"):
        out.append(Paragraph(lead["deck"], deck_style))
    out.append(Paragraph(lead.get("byline", "By the Editor-in-Chief"), byline_style))
    out.append(HRule(COL_W, 0.5))
    out.append(Spacer(1, 3))
    for i, para in enumerate(lead["body"]):
        out.append(Paragraph(para, body_lead if i == 0 else body_style))
    if lead.get("map"):
        out.append(Spacer(1, 3))
        out.append(StyledMap(lead["map"], width=COL_W, height=1.7*inch))
        out.append(Paragraph(lead["map"].get("caption", ""), caption_style))
    if lead.get("illustration"):
        out.append(Spacer(1, 3))
        out.append(IllustrationCard(lead["illustration"], width=COL_W,
                                    height=1.25*inch))
        out.append(Paragraph(lead["illustration"].get("caption", ""), caption_style))
    _extras(out, lead)
    return out


def _story_column(s, compact=False, with_chart=False, with_illustration=False):
    out = []
    out.append(Paragraph(s.get("kicker", ""), section_tag))
    out.append(Paragraph(s["headline"], headline_sm if compact else headline_med))
    if s.get("deck"):
        out.append(Paragraph(s["deck"], deck_style))
    out.append(HRule(COL_W, 0.5))
    out.append(Spacer(1, 3))
    for i, para in enumerate(s.get("body", [])):
        out.append(Paragraph(para, body_lead if i == 0 else body_style))
    if with_illustration and s.get("illustration"):
        out.append(Spacer(1, 3))
        out.append(IllustrationCard(s["illustration"], width=COL_W, height=1.40*inch))
        out.append(Paragraph(s["illustration"].get("caption", ""), caption_style))
    if with_chart and s.get("chart"):
        out.append(Spacer(1, 4))
        out.append(BarChart(s["chart"], width=COL_W, height=1.80*inch))
        out.append(Paragraph(s["chart"].get("caption", ""), caption_style))
    _extras(out, s)
    if s.get("also"):
        out.append(Spacer(1, 4))
        out.append(Paragraph(s.get("also_title", "ALSO IN THE NEWS"), why_title))
        for line in s["also"]:
            out.append(Paragraph(f"• {line}", why_body))
    return out


def build_story(content):
    s = []
    p1 = content.get("p1_stories", [])
    p2 = content.get("p2_stories", [])

    # ---------------- PAGE 1 ----------------
    s += _lead_block(content)
    s.append(FrameBreak())
    if len(p1) > 0:
        s += _story_column(p1[0], with_illustration=True)

    s.append(NextPageTemplate('Page2'))
    s.append(PageBreak())

    # ---------------- PAGE 2 ----------------
    s.append(HRule(CONTENT_W, 1.2))
    s.append(Spacer(1, 2))
    s.append(Paragraph(
        "<b>PAGE 2</b>  •  <b>HOME FRONT &amp; LEARN</b>  •  "
        "India, the United States, and your toolkit", banner_style))
    s.append(Spacer(1, 2))
    s.append(HRule(CONTENT_W, 0.5))
    s.append(FrameBreak())

    learn = content["learn"]

    # col 1 — India story + also + briefs + vocabulary
    if len(p2) > 0:
        s += _story_column(p2[0])
    if content.get("briefs"):
        s.append(Spacer(1, 6))
        s.append(Paragraph("ONE-LINE BRIEFS", why_title))
        for b in content["briefs"]:
            s.append(Paragraph(f"• {b}", why_body))
    if learn.get("vocab"):
        s.append(Spacer(1, 7))
        s.append(HRule(COL_W, 0.5))
        s.append(Spacer(1, 3))
        s.append(Paragraph("VOCABULARY BUILDER", section_tag))
        s.append(Paragraph(learn.get("vocab_title", "Words That Unlock Today"),
                           headline_med))
        s.append(HRule(COL_W, 0.5))
        s.append(Spacer(1, 3))
        for v in learn["vocab"]:
            s.append(Paragraph(f"<b>{v['word']}</b>", headline_sm))
            s.append(Paragraph(v["def"], why_body))
            s.append(Spacer(1, 2))
    if learn.get("did_you_know"):
        s.append(Spacer(1, 5))
        s.append(Paragraph("DID YOU KNOW?", section_tag))
        s.append(Paragraph(learn["did_you_know"], why_body))
    s.append(FrameBreak())

    # col 2 — US story + chart, then Sports / Watchlist / sign-off
    if len(p2) > 1:
        s += _story_column(p2[1], with_chart=True)
    if content.get("sports") or content.get("watchlist"):
        s.append(Spacer(1, 7))
        s.append(HRule(COL_W, 0.5))
        s.append(Spacer(1, 2))
    if content.get("sports"):
        sp = content["sports"]
        s.append(Spacer(1, 5))
        s.append(Paragraph("SPORTS CORNER", section_tag))
        s.append(Paragraph(sp.get("title", ""), headline_sm))
        s.append(Paragraph(sp.get("body", ""), why_body))
    if content.get("watchlist"):
        s.append(Spacer(1, 5))
        s.append(Paragraph("TOMORROW'S WATCHLIST", section_tag))
        for wch in content["watchlist"]:
            s.append(Paragraph(f"• {wch}", why_body))
    if learn.get("quote"):
        s.append(Spacer(1, 5))
        s.append(HRule(COL_W, 0.5))
        s.append(Paragraph(f"<i>“{learn['quote']}”</i>", sign_style))
        s.append(HRule(COL_W, 0.5))
    s.append(Spacer(1, 5))
    s.append(Paragraph(
        "You are not just reading the news — you are learning to think "
        "about it. See you tomorrow.", sign_style))
    return s


# ============================================================
#  DOCUMENT BUILD
# ============================================================
def _make_doc(output_path, content):
    date_str = content["meta"]["date_str"]
    vol_str  = content["meta"]["vol_str"]
    location = content["meta"]["location"]

    doc = BaseDocTemplate(
        output_path, pagesize=letter,
        leftMargin=LEFT_M, rightMargin=RIGHT_M,
        topMargin=TOP_M, bottomMargin=BOT_M,
        title=f"The Young Global Citizen Daily — {date_str}",
        author="Editor-in-Chief, The Young Global Citizen",
    )

    def _cols(page_id, body_h, y0):
        frames = []
        for i in range(NCOLS):
            x = LEFT_M + i*(COL_W + GUTTER)
            frames.append(Frame(
                x, y0, COL_W, body_h, id=f'{page_id}_c{i}',
                leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0))
        return frames

    p1_body_h = PAGE_H - TOP_M - MAST_H - BOT_M - 0.08*inch
    page1_frames = _cols('p1', p1_body_h, BOT_M)

    top_h = 0.42*inch
    top_y = PAGE_H - TOP_M - top_h
    p2_top = Frame(LEFT_M, top_y, CONTENT_W, top_h, id='p2_top',
                   leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    p2_body_h = PAGE_H - TOP_M - top_h - BOT_M - 0.10*inch
    page2_frames = [p2_top] + _cols('p2', p2_body_h, BOT_M)

    doc.addPageTemplates([
        PageTemplate(id='Page1', frames=page1_frames,
                     onPage=make_page1_background(date_str, vol_str, location)),
        PageTemplate(id='Page2', frames=page2_frames,
                     onPage=make_paper_background(date_str)),
    ])
    return doc


# ============================================================
#  AUTO-SHRINK RETRY + VERIFY
# ============================================================
def _shrink_content(content, factor=0.85, scope="all"):
    """Trim the single longest trimmable string in `scope`.

    scope="col3"  — only the page-2 third column (vocab defs, Did You Know,
                    sports, watchlist). This is the frame that actually
                    overflows onto a phantom page 3, so it must be trimmed
                    first; trimming a page-1 story would not help.
    scope="all"   — anything trimmable in the content tree.
    """
    candidates = []   # (setter, text)

    def add_list(parent, key, floor=120):
        for i, v in enumerate(parent.get(key, []) or []):
            if isinstance(v, str) and len(v) >= floor:
                def _set(nv, _l=parent[key], _i=i): _l[_i] = nv
                candidates.append((_set, v))

    def add_field(parent, key, floor=120):
        v = parent.get(key)
        if isinstance(v, str) and len(v) >= floor:
            def _set(nv, _p=parent, _k=key): _p[_k] = nv
            candidates.append((_set, v))

    if scope != "col3":
        add_list(content["lead"], "body")
        add_field(content["lead"], "why")
        for s in content.get("p1_stories", []) + content.get("p2_stories", []):
            add_list(s, "body")
            add_list(s, "also")
            for k in ("why", "connect", "analyst"):
                add_field(s, k)
        add_list(content, "briefs")

    # page-2 column 3
    add_list(content, "watchlist", floor=80)
    for v in content["learn"].get("vocab", []):
        add_field(v, "def", floor=90)
    add_field(content["learn"], "did_you_know", floor=90)
    if content.get("sports"):
        add_field(content["sports"], "body", floor=90)

    if not candidates:
        return False
    setter, text = max(candidates, key=lambda c: len(c[1]))
    # Reuse _fit so the cut lands on a word boundary and never leaves a
    # dangling or unclosed HTML tag (reportlab rejects unbalanced markup).
    target = max(80, int(_len_no_html(text) * factor))
    new_text = _fit(text, target)
    if new_text == text:
        return False
    setter(new_text)
    return True


def verify_pdf(path):
    """Hard gates. Returns (ok, reason)."""
    try:
        from pypdf import PdfReader
    except Exception:
        try:
            from PyPDF2 import PdfReader
        except Exception:
            return True, "no pdf reader available"
    try:
        reader = PdfReader(path)
    except Exception as e:
        return False, f"unreadable pdf: {e}"
    n = len(reader.pages)
    if n != PAGE_COUNT:
        return False, f"page count = {n}, expected {PAGE_COUNT}"
    text = ""
    for p in reader.pages:
        try:
            text += p.extract_text() or ""
        except Exception:
            pass
    for needle in ("[IMAGE:", "[CHART:", "[MAP:", "[PHOTO:"):
        if needle in text:
            return False, f"placeholder string '{needle}' found in PDF"
    return True, "ok"


def build_with_retries(content, output_path, max_retries=10):
    content = enforce_budgets(normalize_content(content))
    last_reason = "not built"
    for attempt in range(max_retries + 1):
        validate_content(content)   # raises only on unknown motifs now

        doc = _make_doc(output_path, content)
        doc.build(build_story(content))
        ok, reason = verify_pdf(output_path)
        if ok:
            return attempt, "ok"
        last_reason = reason
        # A page-count overflow is almost always the page-2 third column
        # spilling onto a phantom page 3 — trim that column first, and only
        # fall back to trimming stories once it has nothing left to give.
        if not _shrink_content(content, factor=0.88, scope="col3"):
            if not _shrink_content(content, factor=0.88, scope="all"):
                break
    return max_retries, f"failed after retries: {last_reason}"


# ============================================================
#  MINIMAL DEFAULT CONTENT (smoke test only)
# ============================================================
DEFAULT_CONTENT = {
    "meta": {"date_str": "Template Preview", "vol_str": "Vol. 1  •  No. 0",
             "location": "New Jersey, USA"},
    "lead": {
        "kicker": "TOP STORY", "headline": "Template Preview",
        "deck": "This is the 2-page layout smoke test.",
        "byline": "By the Editor-in-Chief",
        "body": ["Replace this content with a real issue JSON."],
        "map": {"title": "SAMPLE MAP", "label_top": "NORTH",
                "label_bottom": "SOUTH", "footnote": "sample",
                "caption": "Sample map."},
        "why": "Placeholder.",
    },
    "p1_stories": [
        {"kicker": "WORLD", "headline": "Story A", "deck": "", "body": ["Body."],
         "illustration": {"title": "Sample", "subtitle": "Editorial illustration",
                          "motif": "globe", "caption": "Sample."}},
        {"kicker": "WORLD", "headline": "Story B", "body": ["Body."]},
        {"kicker": "WORLD", "headline": "Story C", "body": ["Body."]},
    ],
    "p2_stories": [
        {"kicker": "INDIA", "headline": "Story D", "body": ["Body."]},
        {"kicker": "UNITED STATES", "headline": "Story E", "body": ["Body."],
         "chart": {"title": "Sample", "subtitle": "units", "labels": ["A", "B"],
                   "values": [1, 2], "max": 3, "caption": "Sample."}},
    ],
    "briefs": ["Brief one."],
    "learn": {"vocab_title": "Words",
              "vocab": [{"word": "Sample", "def": "A sample."}],
              "did_you_know": "A fact.", "quote": "A quote."},
    "sports": {"title": "Sport", "body": "Result."},
    "watchlist": ["Something to watch."],
}


def find_workspace_dir():
    base = "/sessions"
    if os.path.isdir(base):
        for sess in os.listdir(base):
            cand = os.path.join(base, sess, "mnt", "Young Global Citizen Daily")
            if os.path.isdir(cand):
                return cand
    return os.getcwd()


def main():
    content_path = sys.argv[1] if len(sys.argv) > 1 else None
    output_path  = sys.argv[2] if len(sys.argv) > 2 else None

    if content_path and os.path.exists(content_path):
        with open(content_path) as f:
            content = json.load(f)
    else:
        content = DEFAULT_CONTENT

    if not output_path:
        today = _dt.date.today().isoformat()
        output_path = os.path.join(find_workspace_dir(),
                                   f"Young_Global_Citizen_Daily_{today}.pdf")

    attempts, status = build_with_retries(content, output_path)
    print(f"PDF: {output_path}")
    print(f"Build status: {status} (after {attempts} retry/retries)")
    if status != "ok":
        sys.exit(2)


if __name__ == "__main__":
    main()
