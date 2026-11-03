import os

from fpdf import FPDF

FONTS = os.path.join(os.path.dirname(__file__), "fonts")
MAX_CHARS = 500_000


def render(content: str, title: str | None = None) -> bytes:
    """Plain text to PDF. '# ' and '## ' lines are headings, '- ' lines are bullets."""
    if len(content) > MAX_CHARS:
        raise ValueError(f"content is longer than {MAX_CHARS} characters")
    pdf = FPDF()
    pdf.add_font("dv", "", os.path.join(FONTS, "DejaVuSans.ttf"))
    pdf.add_font("dv", "B", os.path.join(FONTS, "DejaVuSans-Bold.ttf"))
    pdf.add_page()
    def line(text, size, style="", indent=0):
        pdf.set_font("dv", style, size)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(0, size * 0.55, text, new_x="LMARGIN", new_y="NEXT")

    if title:
        line(title, 18, "B")
        pdf.ln(3)
    for raw in content.splitlines():
        if raw.startswith("## "):
            line(raw[3:], 13, "B")
        elif raw.startswith("# "):
            line(raw[2:], 16, "B")
        elif raw.startswith(("- ", "* ")):
            line("• " + raw[2:], 11, indent=4)
        elif raw.strip():
            line(raw, 11)
        else:
            pdf.ln(3)
    return bytes(pdf.output())
