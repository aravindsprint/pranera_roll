"""
pranera_roll/outward_request_events.py

Outward Request rules added by the Roll App, plus a fallback copy of
pranera_knit's status tracking.

Always on (these are new rules — pranera_knit has no copy of them, so they
run on every save from any page, Desk included):

  * One Outward Request per Work Order. Checked when a request is created
    or its Work Order is changed, so the handful of older duplicates on the
    site can still be opened and re-saved as they are.
  * From ≠ To.
  * A row's warehouse must belong to the From building (when both the
    warehouse's building and From are set), and a warehouse needs a batch
    of the row's item — the pair is what gets reserved.

Stand-down while pranera_knit is installed (it already does exactly this,
same pattern as roll_wise_pick_list_events.py — see utils.py):

  * Base validation (Work Order XOR Purchase Order, qty > 0, batch belongs
    to the item, created_by / status defaults, no edits once processing).
    The same-day approval rules live in pranera_knit only.
  * on_trash guard and the status tracking along the pick chain:
        Outward Request
          └─ Roll Pick Assignment (outward_request)          → Roll Pick Assigned
              └─ Roll Wise Pick List (roll_pick_assignment)   → Picked
                  └─ Stock Entry (custom_roll_wise_pick_list) → Completed
"""
import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from pranera_roll.utils import knit_app_owns_hooks

PENDING, PROCESSING, COMPLETED = "Pending", "Processing", "Completed"
ASSIGNED, PICKED = "Roll Pick Assigned", "Picked"


# ── Outward Request ───────────────────────────────────────────────────────

def validate_outward_request(doc, method=None):
    if not knit_app_owns_hooks():
        _base_validate(doc)
    validate_one_request_per_work_order(doc)
    _validate_from_and_warehouses(doc)


def existing_request_for_work_order(work_order, exclude=None):
    if not work_order:
        return None
    return frappe.db.get_value(
        "Outward Request",
        {"work_order": work_order, "name": ["!=", exclude or ""]},
        "name", order_by="creation asc",
    )


def validate_one_request_per_work_order(doc):
    if not doc.get("work_order"):
        return
    if not (doc.is_new() or doc.has_value_changed("work_order")):
        return
    other = existing_request_for_work_order(doc.work_order, exclude=doc.name)
    if other:
        frappe.throw(
            _("Work Order {0} already has Outward Request {1}. Only one Outward Request "
              "is allowed per Work Order — open {1} and edit it instead.")
            .format(doc.work_order, other),
            title=_("Duplicate Outward Request"),
        )


def _validate_from_and_warehouses(doc):
    from_building = doc.get("from_building")
    if from_building and from_building == doc.get("to_building"):
        frappe.throw(_("From and To can't be the same building ({0})").format(from_building))

    warehouses = {r.get("warehouse") for r in doc.get("items") or [] if r.get("warehouse")}
    if not warehouses:
        return
    wh_building = dict(frappe.get_all(
        "Warehouse", filters={"name": ["in", list(warehouses)]},
        fields=["name", "building"], as_list=True,
    ))
    for row in doc.items:
        wh = row.get("warehouse")
        if not wh:
            continue
        if not row.batch:
            frappe.throw(_("Row {0}: pick a Batch along with Warehouse {1}").format(row.idx, wh))
        building = wh_building.get(wh)
        if from_building and building and building != from_building:
            frappe.throw(_("Row {0}: Warehouse {1} is in {2}, not in From building {3}")
                         .format(row.idx, wh, building, from_building))


def _base_validate(doc):
    """pranera_knit's validate_outward_request, minus same-day approval."""
    if bool(doc.work_order) == bool(doc.purchase_order):
        frappe.throw(_("Set either a Work Order or a Purchase Order (exactly one)"))
    if not doc.get("items"):
        frappe.throw(_("Add at least one item"))
    for row in doc.items:
        if flt(row.qty) <= 0:
            frappe.throw(_("Row {0}: Qty must be greater than zero").format(row.idx))
        if row.batch:
            batch_item = frappe.db.get_value("Batch", row.batch, "item")
            if batch_item and batch_item != row.item_code:
                frappe.throw(_("Row {0}: Batch {1} belongs to item {2}, not {3}")
                             .format(row.idx, row.batch, batch_item, row.item_code))
    if doc.date and str(doc.date) < frappe.utils.nowdate() and (
            doc.is_new() or doc.has_value_changed("date")):
        frappe.throw(_("Date can't be in the past"))

    if doc.is_new():
        doc.created_by = doc.created_by or frappe.session.user
        doc.created_on = doc.created_on or now_datetime()
        doc.status = ""
        doc.request_status = PENDING
        return
    if frappe.db.get_value("Outward Request", doc.name, "request_status") != PENDING:
        frappe.throw(_("Outward Request {0} is already being processed and can no longer be edited")
                     .format(doc.name))


def on_trash_outward_request(doc, method=None):
    if knit_app_owns_hooks():
        return
    linked = frappe.get_all(
        "Roll Pick Assignment",
        filters={"outward_request": doc.name, "docstatus": ["<", 2]},
        pluck="name", limit=1,
    )
    if linked:
        frappe.throw(_("Cannot delete: Roll Pick Assignment {0} is linked to this request")
                     .format(linked[0]))


# ── Status tracking (fallback copy) ───────────────────────────────────────

def compute_status(outward_request):
    assignments = frappe.get_all(
        "Roll Pick Assignment",
        filters={"outward_request": outward_request, "docstatus": 1}, pluck="name",
    )
    if not assignments:
        return "", PENDING
    pick_lists = frappe.get_all(
        "Roll Wise Pick List",
        filters={"roll_pick_assignment": ["in", assignments], "docstatus": 1}, pluck="name",
    )
    if not pick_lists:
        return ASSIGNED, PROCESSING
    if frappe.db.exists("Stock Entry", {"custom_roll_wise_pick_list": ["in", pick_lists], "docstatus": 1}):
        return COMPLETED, COMPLETED
    return PICKED, PROCESSING


def refresh_status(outward_request):
    if not outward_request or not frappe.db.exists("Outward Request", outward_request):
        return
    if knit_app_owns_hooks():
        # Same logic plus its push notifications.
        frappe.get_attr("pranera_knit.outward_request_events.refresh_status")(outward_request)
        return
    status, request_status = compute_status(outward_request)
    current = frappe.db.get_value(
        "Outward Request", outward_request, ["status", "request_status"], as_dict=True
    )
    if (current.status or "") == status and current.request_status == request_status:
        return
    frappe.db.set_value("Outward Request", outward_request,
                        {"status": status, "request_status": request_status}, update_modified=True)


def refresh_for_assignment(roll_pick_assignment):
    """Called by api/roll_pick.create_roll_picking_entry once it has stamped
    roll_pick_assignment onto the pick list (the on_submit hooks fire
    before that link exists). Works with or without pranera_knit."""
    if roll_pick_assignment:
        refresh_status(frappe.db.get_value("Roll Pick Assignment", roll_pick_assignment, "outward_request"))


def on_roll_pick_assignment_change(doc, method=None):
    if knit_app_owns_hooks():
        return
    refresh_status(doc.get("outward_request"))
    before = doc.get_doc_before_save() if method == "on_update_after_submit" else None
    if before and before.get("outward_request") != doc.get("outward_request"):
        refresh_status(before.get("outward_request"))


def on_roll_wise_pick_list_change(doc, method=None):
    if knit_app_owns_hooks():
        return
    refresh_for_assignment(doc.get("roll_pick_assignment"))


def on_stock_entry_change(doc, method=None):
    if knit_app_owns_hooks():
        return
    pick_list = doc.get("custom_roll_wise_pick_list")
    if pick_list:
        refresh_for_assignment(frappe.db.get_value("Roll Wise Pick List", pick_list, "roll_pick_assignment"))
