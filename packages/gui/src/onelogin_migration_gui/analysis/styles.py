"""Stylesheet snippets for the analysis UI."""

ANALYSIS_QSS = """
/* Use theme-provided palettes via role classes; no hex values */
QFrame.card {
  border: 1px solid;
  border-radius: 12px;
  padding: 16px;
}

QLabel.h1 { font-size: 22px; font-weight: 600; }
QLabel.subtle { font-size: 13px; }

QLabel.statValue {
  font-size: 34px;
  font-weight: 700;
  qproperty-alignment: "AlignRight|AlignVCenter";
}

QLabel.statLabel {
  font-size: 11px;
  letter-spacing: 1px;
  text-transform: uppercase;
}

QLabel.statCaption { font-size: 11px; }

.pill {
  border: 1px solid;
  border-radius: 14px;
  padding: 4px 10px;
}

.pill--success {}
.pill--warning {}
.pill--danger {}

.banner { border: 1px solid; border-radius: 8px; }
"""
