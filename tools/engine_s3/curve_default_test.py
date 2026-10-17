"""Prove the 2026-10-16 decision lands: an HDR source auto-selects UNPLUGGED (engine 7)
for both HDR10 and DV, and the option index the rail sets actually resolves back to 7.

The trap this checks: main_window._apply_auto_curve_default computes row.opt from
VALUE_MAP, and s3shell_panel._configure_curve_row REWRITES VALUE_MAP to whichever table
the hidden ui.showAllTonemappers hatch selected. So the index is only meaningful against
the table the shipped panel actually holds — which is why this drives the real panel
instead of reading the module-level default.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\code\unplugged-mpc-hc\src\unplugged-ui\src")

from PyQt6.QtWidgets import QApplication       # noqa: E402

app = QApplication([])

from mpvprocessor.ui import s3shell_panel as P  # noqa: E402

KEY = "hdr.toneMapCurve"
WANT = 7                       # the product default for every HDR source
failures = []


def auto_default(panel, is_hdr):
    """Verbatim arithmetic of MainWindow._apply_auto_curve_default, against a real row."""
    if not is_hdr:
        return None
    row = next((r for r in panel.rows if r.key == KEY), None)
    if row is None:
        failures.append("no tone-curve row on the rail")
        return None
    table = P.VALUE_MAP.get(row.key) or []
    if WANT not in table:
        failures.append(f"engine {WANT} is not an option of the live table {table}")
        return None
    before = row.opt
    row.opt = table.index(WANT)
    return table[row.opt], before, table          # engine value the row now pushes


for hatch, expected_table in ((False, P.CURVE_SIMPLE), (True, P.CURVE_ALL)):
    panel = P.S3ShellPanel()
    panel.show_all_curves = hatch
    panel._configure_curve_row()
    got = auto_default(panel, is_hdr=True)
    if got is None:
        continue
    pushed, before, table = got
    print(f"hatch={hatch!s:<5} table={table} labels={panel._row(KEY).options}")
    print(f"          opt {before} -> {table.index(WANT)}  pushes engine {pushed}")
    if table != list(expected_table):
        failures.append(f"hatch={hatch}: table is {table}, expected {list(expected_table)}")
    if pushed != WANT:
        failures.append(f"hatch={hatch}: row pushes {pushed}, not {WANT}")
    if panel._row(KEY).opt >= len(panel._row(KEY).options):
        failures.append(f"hatch={hatch}: opt out of range for the visible labels")

# SDR must leave the curve alone (the other half of the contract).
panel = P.S3ShellPanel()
panel.show_all_curves = False
panel._configure_curve_row()
row = panel._row(KEY)
row.opt = 1
auto_default(panel, is_hdr=False)
print(f"SDR: opt unchanged at {row.opt} (expected 1)")
if row.opt != 1:
    failures.append("SDR source moved the curve; it must leave it alone")

# A legacy INI that still names GT7 Adapt must be honoured at load, then flipped by the
# auto default only when an HDR source actually attaches.
panel = P.S3ShellPanel()
panel.ini = {KEY: "10"}
panel.show_all_curves = False
panel._configure_curve_row()
print(f"INI says 10 -> rail lands on opt {panel._row(KEY).opt} "
      f"(engine {P.CURVE_SIMPLE[panel._row(KEY).opt]})")

print("RESULT:", "PASS — Unplugged (7) is the HDR default in both tables"
      if not failures else "FAIL — " + "; ".join(failures))
sys.exit(0 if not failures else 1)
