"""
pranera_roll/patches/v1_4/add_outward_request_from_warehouse.py

Outward Request in the Roll App — "From" building and a warehouse per row.

The Outward Request / Outward Request Item doctypes were created by
pranera_knit (patches/v1_5/add_outward_request.py). On a site where that
already ran (erp.pranera.in) this patch only ADDS the new fields; on a
fresh site without pranera_knit it creates both doctypes first with the
same base schema, so the Roll App page works on its own.

Adds:
  * Outward Request.from_building  (Link Building, "From") — right after
    Date, next to "To". Not mandatory at DocType level, so requests saved
    from the Knit App page (which doesn't send it) still save; the Roll App
    API requires it.
  * Outward Request Item.warehouse (Link Warehouse) — right after Batch.
    The Roll App batch dropdown picks a (batch, warehouse) pair, so every
    row knows where its qty sits. That is what the per-warehouse
    reservation totals are computed from (api/outward_request.py).

Idempotent: fields that already exist are left alone.
"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Roll Module"

PERMISSIONS = [
    {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
    {"role": "Stock Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
    {"role": "Stock User", "read": 1, "write": 1, "create": 1, "report": 1},
    {"role": "Roll Picker", "read": 1},
]

# Same base schema pranera_knit creates — only used when the doctype is missing.
BASE_ITEM_FIELDS = [
    {"fieldname": "item_code", "label": "Item Code", "fieldtype": "Link", "options": "Item",
     "reqd": 1, "in_list_view": 1, "columns": 3},
    {"fieldname": "batch", "label": "Batch", "fieldtype": "Link", "options": "Batch",
     "in_list_view": 1, "columns": 3},
    {"fieldname": "qty", "label": "Qty", "fieldtype": "Float", "reqd": 1,
     "in_list_view": 1, "columns": 1},
    {"fieldname": "stock_uom", "label": "Stock UOM", "fieldtype": "Link", "options": "UOM",
     "in_list_view": 1, "columns": 1},
]

BASE_REQUEST_FIELDS = [
    {"fieldname": "date", "label": "Date", "fieldtype": "Date", "reqd": 1,
     "default": "Today", "in_list_view": 1},
    {"fieldname": "to_building", "label": "To", "fieldtype": "Link", "options": "Building",
     "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
    {"fieldname": "column_break_ref", "fieldtype": "Column Break"},
    {"fieldname": "work_order", "label": "Work Order", "fieldtype": "Link", "options": "Work Order",
     "in_standard_filter": 1},
    {"fieldname": "purchase_order", "label": "Purchase Order", "fieldtype": "Link",
     "options": "Purchase Order", "in_standard_filter": 1},
    {"fieldname": "section_items", "fieldtype": "Section Break", "label": "Items"},
    {"fieldname": "items", "label": "Items", "fieldtype": "Table",
     "options": "Outward Request Item", "reqd": 1},
    {"fieldname": "section_tracking", "fieldtype": "Section Break", "label": "Tracking"},
    {"fieldname": "created_by", "label": "Created By", "fieldtype": "Link", "options": "User",
     "read_only": 1},
    {"fieldname": "created_on", "label": "Created On", "fieldtype": "Datetime", "read_only": 1},
    {"fieldname": "column_break_status", "fieldtype": "Column Break"},
    {"fieldname": "status", "label": "Status", "fieldtype": "Select",
     "options": "\nRoll Pick Assigned\nPicked\nCompleted", "read_only": 1,
     "in_list_view": 1, "in_standard_filter": 1, "no_copy": 1},
    {"fieldname": "request_status", "label": "Doc Status", "fieldtype": "Select",
     "options": "Pending\nProcessing\nCompleted", "default": "Pending", "read_only": 1,
     "in_list_view": 1, "in_standard_filter": 1, "no_copy": 1},
]

# (field spec, insert after)
NEW_REQUEST_FIELDS = [
    ({"fieldname": "from_building", "label": "From", "fieldtype": "Link", "options": "Building",
      "in_list_view": 1, "in_standard_filter": 1,
      "description": "Building the material leaves from — the Roll App only lists "
                     "batch stock in this building's warehouses"}, "date"),
]
NEW_ITEM_FIELDS = [
    ({"fieldname": "warehouse", "label": "Warehouse", "fieldtype": "Link", "options": "Warehouse",
      "in_list_view": 1, "columns": 2,
      "description": "Where this row's batch qty is taken from — reserved against "
                     "that warehouse's stock until the request is Completed"}, "batch"),
]
# Grid widths once Warehouse joins the list view (total 10).
ITEM_COLUMNS = {"item_code": 3, "batch": 3, "warehouse": 2, "qty": 1, "stock_uom": 1}


def execute():
    _ensure_base_doctype("Outward Request Item", BASE_ITEM_FIELDS, {"istable": 1, "editable_grid": 1})
    _ensure_base_doctype("Outward Request", BASE_REQUEST_FIELDS, {
        "autoname": "OR/.YY./.#####",
        "naming_rule": "Expression (old style)",
        "track_changes": 1,
        "sort_field": "creation",
        "sort_order": "DESC",
        "search_fields": "to_building,work_order,purchase_order",
        "permissions": PERMISSIONS,
    })
    _insert_fields("Outward Request Item", NEW_ITEM_FIELDS, columns=ITEM_COLUMNS)
    _insert_fields("Outward Request", NEW_REQUEST_FIELDS)

    # How a pick is tied back to its request (also created by pranera_knit).
    create_custom_fields({
        "Roll Pick Assignment": [{
            "fieldname": "outward_request", "label": "Outward Request", "fieldtype": "Link",
            "options": "Outward Request", "insert_after": "purchase_order", "allow_on_submit": 1,
            "description": "Outward Request this pick fulfils — drives that request's Status",
        }],
    }, ignore_validate=True, update=True)


def _ensure_base_doctype(name, fields, props):
    if frappe.db.exists("DocType", name):
        return
    frappe.get_doc({
        "doctype": "DocType", "name": name, "module": MODULE, "custom": 1,
        "fields": fields, **props,
    }).insert(ignore_permissions=True)


def _insert_fields(doctype, specs, columns=None):
    doc = frappe.get_doc("DocType", doctype)
    existing = {f.fieldname for f in doc.fields}
    changed = False

    for spec, after in specs:
        if spec["fieldname"] in existing:
            continue
        fields = list(doc.fields)
        pos = next((i + 1 for i, f in enumerate(fields) if f.fieldname == after), len(fields))
        doc.fields = []
        for f in fields[:pos]:
            doc.append("fields", f)
        doc.append("fields", spec)
        for f in fields[pos:]:
            doc.append("fields", f)
        existing.add(spec["fieldname"])
        changed = True

    if columns:
        for f in doc.fields:
            if f.fieldname in columns and f.columns != columns[f.fieldname]:
                f.columns = columns[f.fieldname]
                changed = True

    if changed:
        for i, f in enumerate(doc.fields, start=1):
            f.idx = i
        doc.save(ignore_permissions=True)
