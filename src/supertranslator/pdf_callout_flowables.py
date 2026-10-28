"""Track actual ReportLab table splits, not predicted source-page fragments."""

from __future__ import annotations

from typing import Any

from reportlab.platypus import Flowable, Table

from supertranslator.pdf_callout_models import PdfCalloutLayoutPart
from supertranslator.pdf_flowables import PdfAssemblyError, PdfFlowableLayout, TrackedFlowable


def _cell_flowables(table: Table) -> list[TrackedFlowable]:
    def visit(value: Any) -> list[TrackedFlowable]:
        if isinstance(value, TrackedFlowable):
            return [value]
        if isinstance(value, (tuple, list)):
            return [flowable for child in value for flowable in visit(child)]
        return []
    return visit(table._cellvalues)


class TrackedCalloutTable(Flowable):
    def __init__(self, table: Table, *, group_id: str, unit_ids: tuple[str, ...],
                 parts: list[PdfCalloutLayoutPart], records: list[PdfFlowableLayout],
                 counters: dict[str, int]) -> None:
        super().__init__()
        self._table = table
        self._group_id = group_id
        self._unit_ids = unit_ids
        self._parts = parts
        self._records = records
        self._counters = counters
        self.hAlign = table.hAlign

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        self.width, self.height = self._table.wrapOn(self.canv, available_width, available_height)
        return self.width, self.height

    def split(self, available_width: float, available_height: float) -> list[Flowable]:
        tables = self._table.splitOn(self.canv, available_width, available_height)
        if len(tables) > 1:
            first = _cell_flowables(tables[0])
            # Table's in-cell splitter does not implement keepWithNext. Refuse
            # a title-only first part and let the normal frame retry move it.
            if first and all(item._semantic_role == "callout-title" for item in first):
                return []
        return [type(self)(table, group_id=self._group_id, unit_ids=self._unit_ids,
                          parts=self._parts, records=self._records, counters=self._counters)
                for table in tables]

    def getSpaceBefore(self) -> float:
        return self._table.getSpaceBefore()

    def getSpaceAfter(self) -> float:
        return self._table.getSpaceAfter()

    def draw(self) -> None:
        start = len(self._records)
        self._table.drawOn(self.canv, 0, 0)
        drawn = self._records[start:]
        units = tuple(dict.fromkeys(record.unit_id for record in drawn))
        if (not units or any(record.callout_group_id != self._group_id for record in drawn)
                or any(unit not in self._unit_ids for unit in units)):
            raise PdfAssemblyError("drawn callout table has invalid group/unit ownership")
        x, y = self.canv.absolutePosition(0, self.height)
        page_height = self.canv._pagesize[1]
        split_part = self._counters.get(self._group_id, 0)
        self._counters[self._group_id] = split_part + 1
        self._parts.append(PdfCalloutLayoutPart(self._group_id, int(self.canv.getPageNumber()),
            split_part, (float(x), float(page_height - y), float(self.width), float(self.height)), units))
