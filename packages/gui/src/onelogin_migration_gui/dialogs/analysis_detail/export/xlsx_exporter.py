"""Minimal XLSX export implementation for analysis detail tables."""

from __future__ import annotations

import zipfile
from collections.abc import Sequence
from pathlib import Path
from xml.sax.saxutils import escape

from ..utils.formatters import excel_column_letter
from .export_utils import TableExportData, build_metadata_rows

__all__ = ["XLSXExporter"]


class XLSXExporter:
    """Write one or more table exports to a lightweight XLSX workbook."""

    def write_workbook(self, path: Path, sheets: Sequence[TableExportData]) -> None:
        """Persist the provided sheets to *path*."""
        if not sheets:
            raise ValueError("At least one sheet must be supplied.")

        prepared = self._prepare_sheets(sheets)
        path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as workbook:
            workbook.writestr("[Content_Types].xml", self._build_content_types_xml(len(prepared)))
            workbook.writestr("_rels/.rels", self._build_root_relationships())
            workbook.writestr("xl/workbook.xml", self._build_workbook_xml(prepared))
            workbook.writestr("xl/_rels/workbook.xml.rels", self._build_workbook_rels(prepared))

            for index, name, rows in prepared:
                sheet_xml = self._build_sheet_xml(rows)
                workbook.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml)

    # ------------------------------------------------------------------------- helpers
    def _prepare_sheets(
        self,
        sheets: Sequence[TableExportData],
    ) -> list[tuple[int, str, list[list[str]]]]:
        """Return sanitized sheet data ready for workbook serialization."""
        prepared: list[tuple[int, str, list[list[str]]]] = []
        used_names: set[str] = set()

        for index, sheet in enumerate(sheets, start=1):
            sheet_name = sheet.sheet_name or f"Sheet {index}"
            sanitized_name = self._sanitize_sheet_name(sheet_name, used_names)
            used_names.add(sanitized_name)

            headers = ["" if header is None else str(header) for header in sheet.headers]
            body_rows = [["" if cell is None else str(cell) for cell in row] for row in sheet.rows]

            context = sheet.filter_context or {}
            meta_rows = build_metadata_rows(
                context,
                sheet.export_mode,
                len(headers),
                sheet.include_metadata,
            )
            compiled_rows = meta_rows + [headers] + body_rows

            prepared.append((index, sanitized_name, compiled_rows))

        return prepared

    def _sanitize_sheet_name(self, proposed: str, existing: set[str]) -> str:
        """Ensure the sheet name complies with Excel constraints and is unique."""
        invalid_chars = set("[]:*?/\\")
        cleaned = "".join("_" if ch in invalid_chars or ord(ch) < 32 else ch for ch in proposed)
        cleaned = cleaned.strip() or "Sheet"
        cleaned = cleaned[:31]

        base = cleaned
        suffix = 1
        while cleaned in existing:
            suffix_text = f" ({suffix})"
            cleaned = (base[: 31 - len(suffix_text)] + suffix_text).strip()
            suffix += 1
        return cleaned or "Sheet"

    def _build_content_types_xml(self, sheet_count: int) -> str:
        """Return [Content_Types].xml defining workbook parts."""
        overrides = [
            '    <Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        ]
        for index in range(1, sheet_count + 1):
            overrides.append(
                f'    <Override PartName="/xl/worksheets/sheet{index}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
        overrides_text = "\n".join(overrides)

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
            '    <Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
            '    <Default Extension="xml" ContentType="application/xml"/>\n'
            f"{overrides_text}\n"
            "</Types>"
        )

    def _build_root_relationships(self) -> str:
        """Return the relationships manifest for the package root."""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '    <Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>\n'
            "</Relationships>"
        )

    def _build_workbook_xml(self, sheets: Sequence[tuple[int, str, list[list[str]]]]) -> str:
        """Return workbook definition referencing each sheet."""
        sheet_entries = []
        for index, name, _ in sheets:
            sheet_entries.append(
                f'        <sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
            )
        sheets_text = "\n".join(sheet_entries)

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"\n'
            '          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
            "    <sheets>\n"
            f"{sheets_text}\n"
            "    </sheets>\n"
            "</workbook>"
        )

    def _build_workbook_rels(self, sheets: Sequence[tuple[int, str, list[list[str]]]]) -> str:
        """Return workbook relationships linking to each worksheet."""
        relationships = []
        for index, _, _ in sheets:
            relationships.append(
                f'    <Relationship Id="rId{index}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{index}.xml"/>'
            )
        rels_text = "\n".join(relationships)

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            f"{rels_text}\n"
            "</Relationships>"
        )

    def _build_sheet_xml(self, rows: list[list[str]]) -> str:
        """Construct minimal worksheet XML for inline string cells."""
        max_columns = max((len(row) for row in rows), default=0)
        lines: list[str] = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
            "  <sheetData>",
        ]

        for row_idx, row in enumerate(rows, start=1):
            cells: list[str] = []
            for col_idx in range(1, max_columns + 1):
                value = row[col_idx - 1] if col_idx - 1 < len(row) else ""
                if value == "":
                    continue
                cell_ref = f"{excel_column_letter(col_idx)}{row_idx}"
                cells.append(
                    f'      <c r="{cell_ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
                )
            lines.append(f'    <row r="{row_idx}">')
            lines.extend(cells)
            lines.append("    </row>")

        lines.append("  </sheetData>")
        lines.append("</worksheet>")
        return "\n".join(lines)
