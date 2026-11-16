"""
pranera_roll/api/outward_request.py
Whitelisted methods behind the roll-app "Outward Request" page.

Ported from pranera_knit/api/outward_request.py, with:

  * From building (from_building) next to To — required from this page.
  * One Outward Request per Work Order — fetching a Work Order that already
    has one returns `existing_request` instead of items, and the save is
    refused server-side (outward_request_events.validate_one_request_per_work_order).
  * Batch + Warehouse per row. The batch dropdown (search_batch_stock) lists
    one option per (batch, warehouse) with stock, limited to the From
    building's warehouses, and shows for each:
        stock_qty      Stock Ledger balance of that batch in that warehouse
        reserved_qty   qty other, not-yet-Completed Outward Requests have on
                       the same batch + warehouse (reservations[] says which
                       request / Work Order / PO holds it)
        available_qty  stock_qty − reserved_qty
    A request stops reserving once it's Completed (its Stock Entry is
    submitted, so the stock has actually left that warehouse).
    Rows saved without a warehouse (older requests, or ones made on the Knit
    App page) can't be tied to a warehouse; they're reported per batch as
    unallocated_qty so the number isn't silently lost.

Same-day approval and vehicle gate entries belong to pranera_knit; they're
used when it's installed (as on erp.pranera.in) and skipped otherwise.
"""
import frappe
from frappe import _
from frappe.utils import flt, nowdate, now_datetime

from pranera_roll.outward_request_events import existing_request_for_work_order
from pranera_roll.utils import knit_app_owns_hooks

QTY_EPSILON = 0.001
BATCH_OPTION_LIMIT = 60

LIST_FIELDS = [
    "name", "date", "from_building", "to_building", "work_order", "purchase_order",
    "created_by", "created_on", "status", "request_status", "modified",
]


def _knit(path):
    """A pranera_knit function, or None when that app isn't installed."""
    return frappe.get_attr(f"pranera_knit.{path}") if knit_app_owns_hooks() else None


def _has_field(doctype, fieldname):
    return frappe.get_meta(doctype).has_field(fieldname)


# ── Fetch items ───────────────────────────────────────────────────────────

@frappe.whitelist()
def get_outward_request_items(work_order=None, purchase_order=None, from_building=None, name=None):
    if bool(work_order) == bool(purchase_order):
        frappe.throw(_("Pass either a Work Order or a Purchase Order"))

    if work_order:
        existing = existing_request_for_work_order(work_order, exclude=name)
        if existing:
            return {"source": "Work Order", "receipts": [], "items": [],
                    "existing_request": existing}
        res = _items_from_work_order(work_order)
    else:
        res = _items_from_purchase_order(purchase_order)

    _fill_single_warehouse(res["items"], from_building)
    _attach_stock_info(res["items"], exclude_request=name)
    return res


def _items_from_purchase_order(purchase_order):
    if not frappe.db.exists("Purchase Order", purchase_order):
        frappe.throw(_("Purchase Order {0} not found").format(purchase_order))

    receipt_names = frappe.get_all(
        "Subcontracting Receipt Item",
        filters={"purchase_order": purchase_order, "docstatus": 1},
        pluck="parent", distinct=True,
    )
    receipts = frappe.get_all(
        "Subcontracting Receipt",
        filters={"name": ["in", receipt_names or [""]], "docstatus": 1, "is_return": 0},
        pluck="name", order_by="posting_date asc, creation asc",
    )
    if not receipts:
        frappe.throw(_("No submitted Subcontracting Receipt found for Purchase Order {0}")
                     .format(purchase_order))

    supplied = frappe.get_all(
        "Subcontracting Receipt Supplied Item",
        filters={"parenttype": "Subcontracting Receipt", "parent": ["in", receipts]},
        fields=["parent", "idx", "rm_item_code", "batch_no", "serial_and_batch_bundle",
                "consumed_qty", "required_qty", "stock_uom"],
    )
    order = {n: i for i, n in enumerate(receipts)}
    supplied.sort(key=lambda r: (order[r.parent], r.idx))

    bundle_names = [r.serial_and_batch_bundle for r in supplied if r.serial_and_batch_bundle]
    bundle_entries = {}
    if bundle_names:
        for e in frappe.get_all(
            "Serial and Batch Entry",
            filters={"parent": ["in", bundle_names]},
            fields=["parent", "batch_no", "qty"], order_by="idx asc",
        ):
            if e.batch_no:
                bundle_entries.setdefault(e.parent, []).append(e)

    merged = {}
    for r in supplied:
        entries = bundle_entries.get(r.serial_and_batch_bundle)
        if entries:
            parts = [(e.batch_no, abs(flt(e.qty))) for e in entries]
        else:
            parts = [(r.batch_no or "", flt(r.consumed_qty) or flt(r.required_qty))]
        for batch, qty in parts:
            _merge(merged, r.rm_item_code, batch, r.stock_uom, qty)

    return {"source": "Purchase Order", "receipts": receipts, "items": _rows(merged)}


def _items_from_work_order(work_order):
    wo = frappe.db.get_value("Work Order", work_order, ["name", "docstatus"], as_dict=True)
    if not wo:
        frappe.throw(_("Work Order {0} not found").format(work_order))
    if wo.docstatus == 2:
        frappe.throw(_("Work Order {0} is cancelled").format(work_order))

    required = frappe.get_all(
        "Work Order Item",
        filters={"parenttype": "Work Order", "parent": work_order},
        fields=["item_code", "stock_uom", "required_qty"], order_by="idx asc",
    )
    if not required:
        frappe.throw(_("Work Order {0} has no Required Items").format(work_order))

    merged = {}
    for r in required:
        _merge(merged, r.item_code, "", r.stock_uom, flt(r.required_qty))
    return {"source": "Work Order", "receipts": [], "items": _rows(merged)}


def _merge(merged, item_code, batch, stock_uom, qty):
    key = (item_code, batch or "", stock_uom or "")
    if key in merged:
        merged[key]["qty"] += qty
    else:
        merged[key] = {"item_code": item_code, "batch": batch or "", "warehouse": "",
                       "stock_uom": stock_uom or "", "qty": qty}


def _rows(merged):
    rows = []
    for r in merged.values():
        r["qty"] = round(r["qty"], 3)
        if r["qty"] > 0:
            rows.append(r)
    return rows


def _fill_single_warehouse(rows, from_building):
    """PO rows arrive with a batch but no warehouse. When that batch has
    stock in exactly one warehouse (of the From building, if set), fill it
    in; otherwise the user picks one from the dropdown."""
    batched = [r for r in rows if r.get("batch") and not r.get("warehouse")]
    if not batched:
        return
    balances = _batch_balances([r["batch"] for r in batched], from_building=from_building)
    by_batch = {}
    for b in balances:
        by_batch.setdefault(b.batch, []).append(b.warehouse)
    for r in batched:
        whs = by_batch.get(r["batch"], [])
        if len(whs) == 1:
            r["warehouse"] = whs[0]


# ── Stock + reservations ──────────────────────────────────────────────────

def _batch_balances(batches, from_building=None):
    """Positive Stock Ledger balances per (batch, warehouse) for these
    batches — the batch read from each entry's Serial and Batch Bundle, or
    the legacy batch_no column (same numbers as the Stock page). Driven by
    batch (indexed on both tables), which is ~70x faster than scanning a
    high-volume item's whole ledger."""
    batches = tuple({b for b in batches or [] if b})
    if not batches:
        return []
    rows = frappe.db.sql(
        """
        SELECT batch, warehouse, SUM(qty) AS qty FROM (
            SELECT sbe.batch_no AS batch, sle.warehouse, sbe.qty
            FROM `tabSerial and Batch Entry` sbe
            JOIN `tabStock Ledger Entry` sle
              ON sle.serial_and_batch_bundle = sbe.parent AND sle.is_cancelled = 0
            WHERE sbe.batch_no IN %(batches)s
            UNION ALL
            SELECT sle.batch_no, sle.warehouse, sle.actual_qty
            FROM `tabStock Ledger Entry` sle
            WHERE sle.batch_no IN %(batches)s AND sle.is_cancelled = 0
              AND IFNULL(sle.serial_and_batch_bundle, '') = ''
        ) x
        GROUP BY batch, warehouse
        HAVING qty > %(eps)s
        """,
        {"batches": batches, "eps": QTY_EPSILON}, as_dict=True,
    )
    if not rows:
        return []
    buildings = dict(frappe.get_all(
        "Warehouse", filters={"name": ["in", list({r.warehouse for r in rows})]},
        fields=["name", "building"], as_list=True,
    ))
    out = []
    for r in rows:
        r.building = buildings.get(r.warehouse) or ""
        if from_building and r.building != from_building:
            continue
        r.qty = round(flt(r.qty), 3)
        out.append(r)
    return out


def _reservations(batches, exclude_request=None):
    """Outward Request rows on these batches whose request isn't Completed
    yet (and isn't the one being edited), keyed by batch."""
    if not batches:
        return {}
    has_wh = _has_field("Outward Request Item", "warehouse")
    rows = frappe.db.sql(
        f"""
        SELECT i.batch, {"IFNULL(i.warehouse, '')" if has_wh else "''"} AS warehouse,
               i.qty, i.stock_uom, o.name AS outward_request, o.work_order,
               o.purchase_order, o.request_status, o.to_building, o.date
        FROM `tabOutward Request Item` i
        JOIN `tabOutward Request` o ON o.name = i.parent
        WHERE i.parenttype = 'Outward Request'
          AND i.batch IN %(batches)s
          AND IFNULL(o.request_status, 'Pending') != 'Completed'
          AND o.name != %(exclude)s
        ORDER BY o.creation ASC
        """,
        {"batches": tuple(set(batches)), "exclude": exclude_request or ""},
        as_dict=True,
    )
    by_batch = {}
    for r in rows:
        r.qty = round(flt(r.qty), 3)
        by_batch.setdefault(r.batch, []).append(r)
    return by_batch


def _stock_info(batch, warehouse, stock_qty, reservations):
    """Numbers shown for one (batch, warehouse): reservations on the same
    warehouse are subtracted; ones with no warehouse are reported apart."""
    mine = [r for r in reservations if r.warehouse == warehouse]
    unallocated = [r for r in reservations if not r.warehouse]
    reserved = round(sum(r.qty for r in mine), 3)
    return {
        "stock_qty": round(flt(stock_qty), 3),
        "reserved_qty": reserved,
        "available_qty": round(flt(stock_qty) - reserved, 3),
        "unallocated_qty": round(sum(r.qty for r in unallocated), 3),
        "reservations": [_reservation_dict(r) for r in mine],
        "unallocated_reservations": [_reservation_dict(r) for r in unallocated],
    }


def _reservation_dict(r):
    return {
        "outward_request": r.outward_request, "work_order": r.work_order or "",
        "purchase_order": r.purchase_order or "", "qty": r.qty,
        "request_status": r.request_status or "Pending", "to_building": r.to_building or "",
        "date": r.date,
    }


def _attach_stock_info(rows, exclude_request=None):
    """rows[i]["stock_info"] for every row that has a batch + warehouse."""
    keyed = [r for r in rows if r.get("batch") and r.get("warehouse")]
    if not keyed:
        return rows
    batches = [r["batch"] for r in keyed]
    stock = {(b.batch, b.warehouse): b.qty for b in _batch_balances(batches)}
    reservations = _reservations(batches, exclude_request)
    buildings = dict(frappe.get_all(
        "Warehouse", filters={"name": ["in", list({r["warehouse"] for r in keyed})]},
        fields=["name", "building"], as_list=True,
    ))
    for r in keyed:
        r["building"] = buildings.get(r["warehouse"]) or ""
        r["stock_info"] = _stock_info(
            r["batch"], r["warehouse"], stock.get((r["batch"], r["warehouse"]), 0),
            reservations.get(r["batch"], []),
        )
    return rows


def _source_projects(work_order=None, purchase_order=None):
    if work_order:
        project = frappe.db.get_value("Work Order", work_order, "project")
        return [project] if project else []
    if purchase_order:
        projects = set(frappe.get_all(
            "Purchase Order Item",
            filters={"parent": purchase_order, "parenttype": "Purchase Order",
                     "project": ["is", "set"]},
            pluck="project", distinct=True,
        ))
        header = frappe.db.get_value("Purchase Order", purchase_order, "project")
        if header:
            projects.add(header)
        return sorted(projects)
    return []


@frappe.whitelist()
def search_batch_stock(item_code, txt=None, work_order=None, purchase_order=None,
                       from_building=None, exclude_request=None):
    """Batch dropdown on an item row: one option per (batch, warehouse)
    holding stock of this item — only enabled batches of the source
    document's project(s), only warehouses of the From building — with the
    stock / reserved / available numbers described at the top."""
    if not item_code:
        return []
    frappe.has_permission("Batch", "read", throw=True)

    has_project_field = _has_field("Batch", "custom_project")
    conditions, values = ["item = %(item)s", "disabled = 0"], {"item": item_code}
    projects = _source_projects(work_order, purchase_order)
    if projects:
        # Batch.custom_project isn't filled on this site, so a batch belongs
        # to a project when its name starts with "<project>/" or
        # "<project>-<n>/" (split / repack) — see pranera_knit search_batches.
        project_conds = []
        if has_project_field:
            project_conds.append("custom_project IN %(projects)s")
            values["projects"] = tuple(projects)
        for i, project in enumerate(projects):
            values[f"p{i}_slash"] = _like_prefix(project) + "/%"
            values[f"p{i}_dash"] = _like_prefix(project) + "-%"
            project_conds += [f"name LIKE %(p{i}_slash)s", f"name LIKE %(p{i}_dash)s"]
        conditions.append("(" + " OR ".join(project_conds) + ")")
    batch_meta = {
        b.name: b for b in frappe.db.sql(
            f"""SELECT name, stock_uom FROM `tabBatch`
            WHERE {" AND ".join(conditions)}
            ORDER BY creation DESC LIMIT 1000""",
            values, as_dict=True,
        )
    }
    if not batch_meta:
        return []

    needle = (txt or "").strip().lower()
    candidates = [
        b for b in _batch_balances(list(batch_meta), from_building=from_building)
        if not needle or needle in b.batch.lower() or needle in b.warehouse.lower()
    ]
    reservations = _reservations([b.batch for b in candidates], exclude_request)
    options = []
    for b in candidates:
        info = _stock_info(b.batch, b.warehouse, b.qty, reservations.get(b.batch, []))
        options.append({
            "batch": b.batch, "warehouse": b.warehouse, "building": b.building,
            "stock_uom": batch_meta[b.batch].stock_uom or "", **info,
        })
    # Free stock first (most free on top), fully reserved ones last.
    options.sort(key=lambda o: (o["available_qty"] <= QTY_EPSILON, -o["available_qty"], o["batch"]))
    return options[:BATCH_OPTION_LIMIT]


def _like_prefix(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ── Create / update / read ────────────────────────────────────────────────

@frappe.whitelist()
def save_outward_request(date=None, from_building=None, to_building=None, work_order=None,
                         purchase_order=None, items=None, name=None):
    items = frappe.parse_json(items) if isinstance(items, str) else (items or [])
    if not from_building:
        frappe.throw(_("From is required"))
    for i, r in enumerate(items, start=1):
        if r.get("batch") and not r.get("warehouse"):
            frappe.throw(_("Row {0}: pick the batch from the list so its warehouse is set too")
                         .format(i))

    doc = frappe.get_doc("Outward Request", name) if name else frappe.new_doc("Outward Request")
    default_date = _knit("outward_request_approval.default_request_date")
    doc.date = date or (doc.date if name else (default_date() if default_date else nowdate()))
    doc.from_building = from_building
    doc.to_building = to_building
    doc.work_order = work_order or None
    doc.purchase_order = purchase_order or None
    doc.set("items", [])
    for r in items:
        doc.append("items", {
            "item_code": r.get("item_code"),
            "batch": r.get("batch") or None,
            "warehouse": r.get("warehouse") or None,
            "qty": flt(r.get("qty")),
            "stock_uom": r.get("stock_uom") or None,
        })
    doc.save()
    frappe.db.commit()
    return get_outward_request(doc.name)


@frappe.whitelist()
def get_outward_request(name):
    doc = frappe.get_doc("Outward Request", name)
    doc.check_permission("read")
    out = doc.as_dict()
    out["items"] = _attach_stock_info([
        {"item_code": r.item_code, "batch": r.batch or "", "warehouse": r.get("warehouse") or "",
         "qty": r.qty, "stock_uom": r.stock_uom or ""}
        for r in doc.items
    ], exclude_request=name)
    out["created_by_name"] = frappe.utils.get_fullname(doc.created_by) if doc.created_by else ""
    out["roll_pick_assignments"] = frappe.get_all(
        "Roll Pick Assignment",
        filters={"outward_request": name, "docstatus": ["<", 2]},
        fields=["name", "status", "assigned_to", "docstatus"], order_by="creation asc",
    )
    vehicles = _knit("vehicle_gate_entry_events.vehicles_for_outward_requests")
    out["vehicle_gate_entries"] = vehicles([name]).get(name, []) if vehicles else []
    out["approved_by_name"] = frappe.utils.get_fullname(doc.approved_by) if doc.get("approved_by") else ""
    is_approver = _knit("outward_request_approval.is_approver")
    out["can_approve"] = bool(doc.get("same_day_approval") == "Pending" and is_approver and is_approver())
    return out


@frappe.whitelist()
def get_outward_request_config():
    """Same-day cut-off rules from pranera_knit when installed; otherwise
    plain "today or later" with no approval step."""
    knit_config = _knit("api.outward_request.get_outward_request_config")
    if knit_config:
        return knit_config()
    now = now_datetime()
    return {
        "now": now, "today": now.date(), "default_date": now.date(),
        "cutoff_time": "23:59", "cutoff_label": "", "after_cutoff": False,
        "require_approval": 0, "is_approver": 0, "approvers": [],
    }


def _decide(name, approve, remarks):
    decide = _knit("outward_request_approval.decide")
    if not decide:
        frappe.throw(_("Same-day approval needs the Knit App (pranera_knit)"))
    decide(name, approve=approve, remarks=remarks)
    return get_outward_request(name)


@frappe.whitelist()
def approve_same_day(name, remarks=None):
    return _decide(name, True, remarks)


@frappe.whitelist()
def reject_same_day(name, remarks=None):
    return _decide(name, False, remarks)


@frappe.whitelist()
def list_outward_requests(request_status=None, txt=None, limit=50, same_day_approval=None):
    filters = {}
    if request_status:
        filters["request_status"] = request_status
    fields = list(LIST_FIELDS)
    if _has_field("Outward Request", "same_day_approval"):
        fields.append("same_day_approval")
        if same_day_approval:
            filters["same_day_approval"] = same_day_approval
    or_filters = None
    if txt:
        like = f"%{txt}%"
        or_filters = {
            "name": ["like", like], "to_building": ["like", like], "from_building": ["like", like],
            "work_order": ["like", like], "purchase_order": ["like", like],
        }
    rows = frappe.get_list(
        "Outward Request", filters=filters, or_filters=or_filters,
        fields=fields, order_by="creation desc", limit_page_length=int(limit or 50),
    )
    users = {r.created_by for r in rows if r.created_by}
    full_names = dict(frappe.get_all(
        "User", filters={"name": ["in", list(users) or [""]]},
        fields=["name", "full_name"], as_list=True,
    ))
    vehicles_fn = _knit("vehicle_gate_entry_events.vehicles_for_outward_requests")
    vehicles = vehicles_fn([r.name for r in rows]) if vehicles_fn and rows else {}
    for r in rows:
        r["created_by_name"] = full_names.get(r.created_by, r.created_by)
        r["vehicle_nos"] = [v.vehicle_no for v in vehicles.get(r.name, [])]
    return rows


# ── Lookups for the form ──────────────────────────────────────────────────

@frappe.whitelist()
def get_buildings():
    return frappe.get_all(
        "Building", filters={"disabled": 0},
        fields=["name", "building_name", "building_code", "city"],
        order_by="building_name asc", limit_page_length=0,
    )


@frappe.whitelist()
def search_work_orders(txt=None):
    """Submitted Work Orders, each with the Outward Request it already has
    (if any) so the page can say so before fetching."""
    filters = {"docstatus": 1}
    if txt:
        filters["name"] = ["like", f"%{txt}%"]
    rows = frappe.get_all(
        "Work Order", filters=filters,
        fields=["name", "production_item", "status"], limit=30, order_by="modified desc",
    )
    if rows:
        taken = {}
        for r in frappe.get_all(
            "Outward Request",
            filters={"work_order": ["in", [w.name for w in rows]]},
            fields=["name", "work_order"], order_by="creation asc",
        ):
            taken.setdefault(r.work_order, r.name)
        for w in rows:
            w["outward_request"] = taken.get(w.name, "")
    return rows


@frappe.whitelist()
def search_purchase_orders(txt=None):
    filters = {"docstatus": 1, "is_subcontracted": 1}
    if txt:
        filters["name"] = ["like", f"%{txt}%"]
    return frappe.get_all(
        "Purchase Order", filters=filters,
        fields=["name", "supplier_name", "status"], limit=30, order_by="modified desc",
    )


# ── Roll Pick Assignment from a request ───────────────────────────────────
# Same plan as pranera_knit, but batch rows are kept per (batch, warehouse)
# and the warehouse goes onto the Assignment's batch_items row as the
# planning hint create_pick_order already supports. When every batch row
# sits in one warehouse, that warehouse is the default Source Warehouse.

def _assignment_plan(doc):
    plan = {"outward_request": doc.name, "excluded": [], "batch_items": [], "uom_totals": {}}
    for r in doc.items:
        uom = r.stock_uom or "Kgs"
        plan["uom_totals"][uom] = round(plan["uom_totals"].get(uom, 0.0) + flt(r.qty), 3)

    merged, excluded = {}, []
    for r in doc.items:
        if not r.batch:
            excluded.append({"item_code": r.item_code, "qty": flt(r.qty), "stock_uom": r.stock_uom})
            continue
        key = (r.batch, r.get("warehouse") or "")
        if key in merged:
            merged[key]["qty"] = round(merged[key]["qty"] + flt(r.qty), 3)
        else:
            merged[key] = {"batch": r.batch, "warehouse": r.get("warehouse") or "",
                           "item_code": r.item_code, "qty": flt(r.qty), "stock_uom": r.stock_uom}
    batch_items = list(merged.values())
    row_warehouses = {b["warehouse"] for b in batch_items}
    single_wh = next(iter(row_warehouses)) if len(row_warehouses) == 1 else None

    if doc.work_order:
        wo = frappe.db.get_value("Work Order", doc.work_order,
                                 ["project", "wip_warehouse", "source_warehouse"], as_dict=True) or {}
        plan.update({
            "pick_type": "To Work Order",
            "document_name": doc.work_order,
            "project": wo.get("project"),
            "default_source_warehouse": single_wh or wo.get("source_warehouse"),
            "default_target_warehouse": wo.get("wip_warehouse"),
            "subcontracting_orders": [],
        })
        if batch_items:
            plan.update({
                "batch_items": batch_items,
                "pick_qty": round(sum(b["qty"] for b in batch_items), 3),
                "excluded": excluded,
                "non_kgs": {},
            })
        else:
            plan.update({
                "pick_qty": plan["uom_totals"].get("Kgs", 0.0),
                "non_kgs": {u: q for u, q in plan["uom_totals"].items() if u != "Kgs"},
            })
        return plan

    sco = frappe.get_all(
        "Subcontracting Order",
        filters={"purchase_order": doc.purchase_order, "docstatus": 1},
        fields=["name", "supplier_warehouse", "status"], order_by="creation desc",
    )
    plan.update({
        "pick_type": "To Subcontracting Order",
        "document_name": doc.purchase_order,
        "project": frappe.db.get_value("Purchase Order", doc.purchase_order, "project"),
        "batch_items": batch_items,
        "pick_qty": round(sum(b["qty"] for b in batch_items), 3),
        "excluded": excluded,
        "subcontracting_orders": sco,
        "default_source_warehouse": single_wh,
        "default_target_warehouse": sco[0].supplier_warehouse if sco else None,
        "non_kgs": {},
    })
    return plan


def _assert_cleared(doc):
    assert_cleared = _knit("outward_request_approval.assert_cleared")
    if assert_cleared:
        assert_cleared(doc)


@frappe.whitelist()
def get_pick_assignment_defaults(name):
    doc = frappe.get_doc("Outward Request", name)
    doc.check_permission("read")
    _assert_cleared(doc)
    return _assignment_plan(doc)


@frappe.whitelist()
def create_roll_pick_assignment(name, source_warehouse, target_warehouse, assigned_to,
                                subcontracting_order=None, pick_qty=None, remarks=None,
                                roll_source=None):
    from pranera_roll.api.pick_order import create_pick_order

    doc = frappe.get_doc("Outward Request", name)
    doc.check_permission("write")
    if doc.request_status != "Pending":
        frappe.throw(_("Outward Request {0} is already {1}").format(name, doc.request_status))
    _assert_cleared(doc)

    plan = _assignment_plan(doc)
    if not source_warehouse or not target_warehouse:
        frappe.throw(_("Source and Target Warehouse are required"))

    route = " → ".join(b for b in (doc.get("from_building"), doc.to_building) if b)
    args = dict(
        pick_type=plan["pick_type"],
        source_warehouse=source_warehouse,
        target_warehouse=target_warehouse,
        assigned_to=assigned_to,
        project=plan.get("project"),
        remarks=remarks or _("Outward Request {0} · {1}").format(name, route),
        roll_source=roll_source,
        outward_request=name,
    )
    batch_rows = [{"batch": b["batch"], "qty": b["qty"], "warehouse": b["warehouse"] or None}
                  for b in plan["batch_items"]]

    if plan["pick_type"] == "To Work Order" and batch_rows:
        args.update(document_name=plan["document_name"], batch_items=batch_rows)
    elif plan["pick_type"] == "To Work Order":
        target = flt(pick_qty) or plan["pick_qty"]
        if target <= 0:
            frappe.throw(_("Enter the Pick Qty (kg) — this request has no Kgs items to default from"))
        args.update(document_name=plan["document_name"], pick_qty=target)
    else:
        valid = {s.name for s in plan["subcontracting_orders"]}
        if not valid:
            frappe.throw(_("No submitted Subcontracting Order found for Purchase Order {0}")
                         .format(doc.purchase_order))
        subcontracting_order = subcontracting_order or plan["subcontracting_orders"][0].name
        if subcontracting_order not in valid:
            frappe.throw(_("Subcontracting Order {0} is not linked to Purchase Order {1}")
                         .format(subcontracting_order, doc.purchase_order))
        if not batch_rows:
            frappe.throw(_("None of this request's items has a batch, so there is nothing to roll-pick"))
        args.update(purchase_order=doc.purchase_order, subcontracting_order=subcontracting_order,
                    batch_items=batch_rows)

    result = create_pick_order(**args)
    return {"name": result.get("name"), "outward_request": get_outward_request(name)}
