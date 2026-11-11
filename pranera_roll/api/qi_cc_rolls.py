"""
pranera_roll/api/qi_cc_rolls.py
Read-only API for the "QI CC Finish Rolls" page of the roll PWA.

Collar / cuff counterpart of qi_rolls.py. Lists the rows of the
"CC Roll Details" child table of SUBMITTED "QI CC Report Details"
documents, and attaches the matching "CC Mistake Details" rows.

CC Mistake Details is a separate child table on the same report; a mistake
row belongs to a roll through (parent, roll_no) — there is no link field.

Sticker QR format (same as the fabric QI sticker — pick_order._get_qi_roll
already looks up CC Roll Details for roll_source == "QI Report Details"):

    item_code#batch_no#lot_no#roll_no

Search rules
------------
* A scanned QR (contains '#') is matched EXACTLY on roll_no + batch_no.
* Text that exactly equals a report name, batch, lot, roll no, item code
  or a mistake name is matched exactly.
* Anything else is a LIKE '%text%' search over the same columns + fabric,
  colour and mistake name.

Child tables aren't readable through /api/resource for most users, so
access is gated on read permission for the parent doctype instead.
"""

import math

import frappe
from frappe.utils import cint

QI_CC_DOCTYPE = "QI CC Report Details"
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
        d.greige_roll_no                         AS greige_roll_no,
        d.roll_weight                            AS roll_weight,
        d.width                                  AS width,
        d.total_qty                              AS total_qty,
        d.accepted_qty                           AS accepted_qty,
        d.rejected_qty                           AS rejected_qty,
        d.total_points                           AS total_points,
        d.knitting_machine_no                    AS knitting_machine_no,
        d.name_of_the_checker                    AS checker,
        IFNULL(NULLIF(d.stock_uom, ''), IFNULL(NULLIF(q.stock_uom, ''), 'Pcs')) AS stock_uom
"""

_FROM = """
    FROM `tabCC Roll Details` d
    INNER JOIN `tabQI CC Report Details` q ON q.name = d.parent
    WHERE d.parenttype = 'QI CC Report Details'
      AND d.parentfield = 'cc_roll_details'
      AND q.docstatus = 1
"""

_ORDER = " ORDER BY q.creation DESC, d.idx ASC"

# Mistake rows of the same report + roll no.
_MISTAKE_EXISTS = """
    EXISTS (
        SELECT 1 FROM `tabCC Mistake Details` m
        WHERE m.parent = d.parent
          AND m.parenttype = 'QI CC Report Details'
          AND m.parentfield = 'cc_mistake_details'
          AND m.roll_no = d.roll_no
          AND m.mistake_name {op} %({param})s
    )
"""


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
        " OR d.roll_no = %(q)s OR q.item_code = %(q)s OR "
        + _MISTAKE_EXISTS.format(op="=", param="q")
        + ")"
    )
    has_exact = frappe.db.sql(
        "SELECT 1 " + _FROM + exact_where + " LIMIT 1", {"q": q}
    )
    if has_exact:
        return exact_where, {"q": q}, "exact"

    like_where = (
        " AND (q.name LIKE %(like)s OR q.batch_no LIKE %(like)s OR q.lot_no LIKE %(like)s"
        " OR d.roll_no LIKE %(like)s OR q.item_code LIKE %(like)s OR q.fabric LIKE %(like)s"
        " OR q.color LIKE %(like)s OR "
        + _MISTAKE_EXISTS.format(op="LIKE", param="like")
        + ")"
    )
    return like_where, {"like": f"%{q}%"}, "like"


def _num(v):
    """twoqty / fourqty / total_*point are Data fields — may be '', None or 'NaN'."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return 0 if math.isnan(f) else f


def _attach_mistakes(rows):
    """Adds `mistakes` (one entry per mistake name, counts summed) and
    `mistake_points` to each roll row, from CC Mistake Details."""
    if not rows:
        return

    reports = list({r.qi_report for r in rows})
    roll_nos = list({r.roll_no for r in rows if r.roll_no})
    for r in rows:
        r["mistakes"] = []
        r["mistake_points"] = 0
    if not roll_nos:
        return

    mrows = frappe.db.sql(
        """
        SELECT m.parent, m.roll_no, m.mistake_name, m.idx,
               m.oneqty, m.twoqty, m.fourqty
        FROM `tabCC Mistake Details` m
        WHERE m.parenttype = 'QI CC Report Details'
          AND m.parentfield = 'cc_mistake_details'
          AND m.parent IN %(reports)s
          AND m.roll_no IN %(roll_nos)s
        ORDER BY m.parent, m.idx
        """,
        {"reports": reports, "roll_nos": roll_nos},
        as_dict=True,
    )

    # (report, roll_no) -> {mistake_name: {...}}  (dict keeps first-seen order)
    grouped = {}
    for m in mrows:
        key = (m.parent, m.roll_no)
        by_name = grouped.setdefault(key, {})
        name = m.mistake_name or "—"
        agg = by_name.setdefault(
            name, {"mistake_name": name, "one": 0, "two": 0, "four": 0, "points": 0}
        )
        one, two, four = _num(m.oneqty), _num(m.twoqty), _num(m.fourqty)
        agg["one"] += one
        agg["two"] += two
        agg["four"] += four
        agg["points"] += one + 2 * two + 4 * four

    for r in rows:
        by_name = grouped.get((r.qi_report, r.roll_no))
        if not by_name:
            continue
        mistakes = sorted(by_name.values(), key=lambda a: -a["points"])
        for a in mistakes:
            for k in ("one", "two", "four", "points"):
                a[k] = cint(a[k]) if float(a[k]).is_integer() else a[k]
        r["mistakes"] = mistakes
        r["mistake_points"] = sum(a["points"] for a in mistakes)


@frappe.whitelist()
def get_qi_cc_finish_rolls(search=None, start=0, page_length=20, all_matching=0):
    """Paged list of submitted QI CC Report Details roll rows, each with
    its CC Mistake Details summary.

    all_matching=1 ignores start/page_length and returns every matching
    row (capped at MAX_ALL_MATCHING) without mistakes — used by
    "Select all matching" (printing doesn't need them)."""
    frappe.has_permission(QI_CC_DOCTYPE, "read", throw=True)

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

    if not cint(all_matching):
        _attach_mistakes(rows)

    return {
        "rows": rows,
        "total": total,
        "match_mode": match_mode,
        "capped": bool(cint(all_matching) and total > MAX_ALL_MATCHING),
    }
