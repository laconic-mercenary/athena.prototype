"""Output contracts for the inventory ensemble — re-exported so the manifest can
reference them as `schemas.<ClassName>` (e.g. `schemas.ScanOutput`)."""

from .scan_output import ExtensionCount, ScanOutput
from .report_output import ReportOutput

__all__ = ["ExtensionCount", "ScanOutput", "ReportOutput"]
