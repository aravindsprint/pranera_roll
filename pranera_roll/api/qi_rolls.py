"""
pranera_roll/api/qi_rolls.py
Read-only API for the "QI Finish Rolls" page of the roll PWA.

Lists the rows of the "Roll Details" child table of SUBMITTED
"QI Report Details" documents, so finished rolls that were inspected
before the Roll doctype existed can have their 100 x 80 mm sticker
(re)printed.

Sticker QR format (old QI sticker — also what pick_order._parse_scanned_value
expects for roll_source == "QI Report Details"):

    item_code#batch_no#lot_no#roll_no

Search rules
------------
* A scanned QR (contains '#') is matched EXACTLY on roll_no + batch_no.
* Text that exactly equals a QI Report name, batch, lot, roll no or item
  code is matched exactly — a LIKE search for lot "PO18523-3" would also
  return "PO18523-30", "PO18523-31", ...
* Anything else is a LIKE '%text%' search over the same columns + fabric.

Roll Details is a child table, so it isn't readable through
/api/resource for most users; access is gated on read permission for the
parent doctype instead.
"""

import frappe
from frappe import _
from frappe.utils import cint

QI_DOCTYPE = "QI Report Details"
MAX_ALL_MATCHING = 5000

_SELECT = """
    SELECT
        d.name                                   AS row_id,
        d.idx                                    AS idx,
        q.name                                   AS qi_report,
        q.item_code                              AS item_code,
        q.batch_no                               AS batch_no,
        q.lot_no                                 AS lot_no,
        q.fabric                                 AS fabric,
        q.color                                  AS color,
        q.date                                   AS qi_date,
        d.roll_no                                AS roll_no,
        d.roll_weight                            AS roll_weight,
        d.width                                  AS width,
        d.gsm                                    AS gsm,
        d.grade                                  AS grade,
        IFNULL(NULLIF(d.stock_uom, ''), IFNULL(NULLIF(q.stock_uom, ''), 'Kgs')) AS stock_uom
"""

_FROM = """
    FROM `tabRoll Details` d
    INNER JOIN `tabQI Report Details` q ON q.name = d.parent
    WHERE d.parenttype = 'QI Report Details'
      AND d.parentfield = 'roll_details'
      AND q.docstatus = 1
"""

_ORDER = " ORDER BY q.creation DESC, d.idx ASC"


def _build_where(search):
    """Returns (extra_where_sql, params, match_mode)."""
    q = (search or "").strip()
    if not q:
        return "", {}, "all"

    # Scanned sticker QR: item_code#batch_no#lot_no#roll_no
    if "#" in q:
        parts = [p.strip() for p in q.split("#")]
        roll_no = parts[-1]
        batch = parts[1] if len(parts) >= 3 else ""
        params = {"roll_no": roll_no}
        where = " AND d.roll_no = %(roll_no)s"
        if batch:
            where += " AND q.batch_no = %(batch)s"
            params["batch"] = batch
        return where, params, "qr"

    exact_where = (
        " AND (q.name = %(q)s OR q.batch_no = %(q)s OR q.lot_no = %(q)s"
        " OR d.roll_no = %(q)s OR q.item_code = %(q)s)"
    )
    has_exact = frappe.db.sql(
        "SELECT 1 " + _FROM + exact_where + " LIMIT 1", {"q": q}
    )
    if has_exact:
        return exact_where, {"q": q}, "exact"

    like_where = (
        " AND (q.name LIKE %(like)s OR q.batch_no LIKE %(like)s OR q.lot_no LIKE %(like)s"
        " OR d.roll_no LIKE %(like)s OR q.item_code LIKE %(like)s OR q.fabric LIKE %(like)s)"
    )
    return like_where, {"like": f"%{q}%"}, "like"


@frappe.whitelist()
def get_qi_finish_rolls(search=None, start=0, page_length=20, all_matching=0):
    """Paged list of submitted QI Report Details roll rows.

    all_matching=1 ignores start/page_length and returns every matching
    row (capped at MAX_ALL_MATCHING) — used by "Select all matching"."""
    frappe.has_permission(QI_DOCTYPE, "read", throw=True)

    where, params, match_mode = _build_where(search)

    total = frappe.db.sql("SELECT COUNT(*) " + _FROM + where, params)[0][0]

    if cint(all_matching):
        limit_sql = f" LIMIT {MAX_ALL_MATCHING}"
    else:
        page_length = max(1, min(cint(page_length) or 20, 500))
        start = max(0, cint(start))
        limit_sql = f" LIMIT {page_length} OFFSET {start}"

    rows = frappe.db.sql(
        _SELECT + _FROM + where + _ORDER + limit_sql, params, as_dict=True
    )

    return {
        "rows": rows,
        "total": total,
        "match_mode": match_mode,
        "capped": bool(cint(all_matching) and total > MAX_ALL_MATCHING),
    }
