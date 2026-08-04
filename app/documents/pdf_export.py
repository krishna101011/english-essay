import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

from app.db.models import Document, DocumentVersion

_styles = getSampleStyleSheet()
_TITLE = ParagraphStyle("EssayTitle", parent=_styles["Title"], fontSize=18, spaceAfter=4)
_META = ParagraphStyle("EssayMeta", parent=_styles["Normal"], textColor=colors.slategray, spaceAfter=16)
_HEADING = ParagraphStyle("SectionHeading", parent=_styles["Heading2"], spaceBefore=16, spaceAfter=8)
_BODY = ParagraphStyle("EssayBody", parent=_styles["Normal"], leading=16, spaceAfter=10)
_SCORE = ParagraphStyle("ScoreLine", parent=_styles["Normal"], spaceAfter=4)
_CORRECTION = ParagraphStyle("Correction", parent=_styles["Normal"], leading=14)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_essay_pdf(document: Document, version: DocumentVersion) -> bytes:
    """Render an essay's content plus its feedback (score, corrections) as a
    downloadable PDF. Pure in-memory rendering - caller is responsible for
    owner-scoping `document`/`version` before calling this."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        title=document.title,
    )
    story = [
        Paragraph(_escape(document.title), _TITLE),
        Paragraph(
            f"Version {version.version_number} &middot; submitted {version.submitted_at.strftime('%Y-%m-%d %H:%M UTC')}",
            _META,
        ),
    ]

    if version.score is not None:
        score = version.score
        story.append(Paragraph("Scores", _HEADING))
        story.append(Paragraph(f"<b>Overall: {score.overall_score:.0f}/100</b>", _SCORE))
        story.append(Paragraph(f"Grammar: {score.grammar_score:.0f} &middot; Vocabulary: {score.vocab_score:.0f} "
                                f"&middot; Structure: {score.structure_score:.0f} &middot; Clarity: {score.clarity_score:.0f}", _SCORE))
        story.append(Paragraph(_escape(score.feedback_summary), _BODY))

    story.append(Paragraph("Essay", _HEADING))
    for paragraph in version.content.split("\n"):
        if paragraph.strip():
            story.append(Paragraph(_escape(paragraph), _BODY))

    corrections = sorted(version.corrections, key=lambda c: c.start_offset)
    if corrections:
        story.append(Paragraph("Feedback", _HEADING))
        items = [
            ListItem(
                Paragraph(
                    f"<b>{_escape(c.category.value.replace('_', ' ').title())}:</b> "
                    f"“{_escape(c.original_text)}” &rarr; “{_escape(c.suggested_text)}”"
                    f"<br/>{_escape(c.explanation)}",
                    _CORRECTION,
                )
            )
            for c in corrections
        ]
        story.append(ListFlowable(items, bulletType="bullet", start="circle"))

    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        "AI scores are guidance to support revision, not objective grading.", _META
    ))

    doc.build(story)
    return buffer.getvalue()
