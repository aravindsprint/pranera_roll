"""
pranera_roll/api/roll_pick.py

Server-side Stock Entry builder for the Roll Pick Assignment (Pick Order)
flow — copied from pranera_roll/api/knit.py, keeping ONLY the pieces the
pick-order execution flow depends on:

  * _get_warehouse_address
  * get_batch_warehouse_overrides
  * get_pick_qty_targets_by_uom
  * create_roll_picking_entry   (incl. the authoritative +/-3% tolerance check)

Everything else in knit.py (Job Card / roll packing / reconciliation / QI /
yarn consumption) is out of scope for the Roll app and deliberately not
copied. create_roll_picking_entry is NOT exposed as a whitelisted endpoint
here — in this app it is only ever reached server-side through
api.pick_order.submit_pick_order, so there is no reason to give it its own
public URL.
"""
import frappe
import json
from frappe import _
from frappe.utils import now_datetime, today, get_datetime, nowtime, cint, flt


def _get_warehouse_address(warehouse):
    """
    Looks up the Address linked to a Warehouse. Warehouse has no forward
    Link field to Address — the relationship only exists the other way,
    via a Dynamic Link row on the Address doc (parenttype=Address,
    link_doctype=Warehouse, link_name=<warehouse>) — so this can't be done
    with a simple fetch_from and has to be a real lookup.
    """
    if not warehouse:
        return None
    return frappe.db.get_value(
        "Dynamic Link",
        {"link_doctype": "Warehouse", "link_name": warehouse, "parenttype": "Address"},
        "parent",
    )


def get_batch_warehouse_overrides(roll_pick_assignment):
    """batch -> warehouse map from a Roll Pick Assignment's own Batch Items
    table (the field populated via get_warehouses_for_batch in
    textiles_and_garments's roll_pick_assignment.py, showing each batch's
    actual per-warehouse qty when the supervisor set it up). A batch
    doesn't necessarily sit in the Assignment's single blanket Source
    Warehouse, so anywhere a batch's rolls get attributed to a warehouse —
    at scan time as much as at final Stock Entry creation — should prefer
    this override over the blanket source_warehouse. Only includes
    batches whose row actually has a warehouse set (that field is
    optional); callers fall back to the blanket source_warehouse for any
    batch missing from this map. Returns {} if roll_pick_assignment is
    falsy (a manual, non-Pick-Order fulfillment).

    "From Batch" Assignments ALWAYS return {} — for that pick type the
    worker picks the Source Warehouse on the Pick Order Execution page,
    and that selection must win for every roll, exactly as it does for
    "To Work Order": scans are recorded against it, changing it
    mid-session moves every already scanned roll to it, and the Stock
    Entry rows are built from it. The per-batch Warehouse on the Batch
    Items rows is only the supervisor's planning hint for From Batch
    (where stock was sitting when the Assignment was made), not a
    binding override."""
    if not roll_pick_assignment:
        return {}
    if frappe.db.get_value("Roll Pick Assignment", roll_pick_assignment, "pick_type") == "From Batch":
        return {}
    return {
        r.batch: r.warehouse
        for r in frappe.get_all(
            "Roll Pick Batch Item",
            filters={"parenttype": "Roll Pick Assignment", "parent": roll_pick_assignment},
            fields=["batch", "warehouse"],
        )
        if r.warehouse
    }


def get_pick_qty_targets_by_uom(assignment_doc):
    """Per-UOM breakdown of a Roll Pick Assignment's pick target — {uom:
    target_qty} — derived directly from the Assignment's own Batch Items
    (grouped by stock_uom), NOT from the doctype's own "Pick Qty (by UOM)"
    field. That field's computation logic isn't in any file this app
    ships — it's populated by something outside this codebase, almost
    certainly a Server Script that exists only on production, the exact
    known-risky pattern this app has hit before (see the module docstring
    on why Server Scripts are avoided here). Computing it fresh here also
    fixes the actual bug that prompted this: pick_qty itself is a single
    blended number that naively sums qty across every batch_items row
    regardless of stock_uom — for a mixed Kgs+Pcs Assignment that means
    adding a piece count directly to a weight and calling the sum "kg",
    which is meaningless. Each UOM's target must be checked against its
    own scanned total independently instead.

    Falls back to a single "Kgs" bucket built from pick_qty when there are
    no Batch Items at all (e.g. "From Work Order" / "Manual Roll Pick"
    flows, which are always plain single-UOM weight picks with no batch
    breakdown to derive from)."""
    targets = {}
    for row in (assignment_doc.batch_items or []):
        uom = row.stock_uom or "Kgs"
        targets[uom] = targets.get(uom, 0.0) + flt(row.qty)
    if not targets and assignment_doc.pick_qty:
        targets["Kgs"] = flt(assignment_doc.pick_qty)
    return targets


def create_roll_picking_entry(pick_type=None, document_name=None, document=None,
                               source_warehouse=None, target_warehouse=None,
                               posting_date=None, date=None, project=None,
                               batch_no=None, from_work_order=None,
                               from_subcontracting=None, rolls=None, items=None,
                               required_items=None, scanned_roll=None,
                               roll_pick_assignment=None, submit_stock_entry=1):
    """
    Creates a Roll Wise Pick List + Stock Entry (Material Transfer) for the
    picked rolls/batches. Exact port of Node's POST /api/createRollPickingEntry
    (knit_app.js), adapted to call ERPNext directly via frappe.get_doc instead
    of proxying HTTP requests:

      STEP 1 — create + submit a "Roll Wise Pick List":
        * batch_wise_pick_item is always populated (one row per item+batch).
        * roll_wise_pick_item is populated only for genuine roll-level picks —
          a "batch transfer" (every roll's roll_no == its batch_no, i.e. the
          GKF "pick the whole batch" flow) skips this child table.

      STEP 2 — create + submit a Stock Entry (Material Transfer):
        * naming_series is "MT/26/" for pick_type == "To Work Order" (Material
          Transfer for Manufacture), otherwise "MT/26/".
        * items are grouped by (item_code, batch_no) so multiple rolls of the
          same item/batch collapse into a single Stock Entry Detail row.
        * custom_batch_wise_packing_summary carries the batch/qty/roll-count
          breakdown for reporting.
        * work_order / purchase_order / subcontracting_order /
          custom_reference_stock_entry / custom_reference_batch is set based
          on pick_type + document, and project / custom_from_work_order /
          custom_from_subcontracting are set when supplied.

    Accepts both the old simplified payload shape (document_name, items,
    scanned_roll, date) and the full Ionic-app payload shape (document,
    posting_date, rolls, required_items, batch_no, from_work_order,
    from_subcontracting) so either caller works unchanged.

    roll_pick_assignment: optional — when a fulfillment comes from the
    Pick Order flow (a supervisor-assigned task, see api/pick_order.py),
    pass the Roll Pick Assignment name here. On success this stamps that
    reference onto the created Roll Wise Pick List (for traceability) and
    marks the Order's status "Completed" — or "In Progress" if
    submit_stock_entry is falsy, since the material hasn't actually moved
    yet. Ordinary manual picks (no Pick Order behind them) omit this and
    nothing changes.

    submit_stock_entry: the Roll Wise Pick List is ALWAYS submitted
    regardless — it's just the record of what was picked. This only
    controls the Stock Entry's docstatus: truthy (default) submits it
    immediately as before; falsy inserts it as a draft for someone to
    review and submit manually later.
    """
    frappe.has_permission("Stock Entry", throw=True)

    # ── Normalize inputs (accept either payload shape / JSON strings) ──────
    document_name = document or document_name
    posting_date  = posting_date or date or today()
    rolls = rolls if rolls is not None else items
    if isinstance(rolls, str):
        rolls = json.loads(rolls)
    if isinstance(required_items, str):
        required_items = json.loads(required_items)
    rolls = rolls or []

    if not posting_date:
        frappe.throw(_("Posting date is required"))
    if not target_warehouse:
        frappe.throw(_("Target warehouse is required"))
    if not source_warehouse:
        frappe.throw(_("Source warehouse is required"))
    if not rolls:
        frappe.throw(_("At least one roll is required"))

    # When fulfilling a Pick Order, the per-UOM target (from Batch Items,
    # see get_pick_qty_targets_by_uom) is the authoritative check —
    # validated here rather than only client-side, since this is the one
    # place a Pick Order's fulfillment actually becomes a real Stock
    # Entry. Each UOM is checked independently (a Kgs target and a Pcs
    # target are unrelated quantities — see get_pick_qty_targets_by_uom's
    # docstring for why they can't be blended into one number). Accounts
    # for whatever was already submitted against this Order in a prior
    # session too, so partial-then-resume fulfillment is checked against
    # the true cumulative total per UOM, not just this call's rolls.
    if roll_pick_assignment:
        assignment_doc = frappe.get_doc("Roll Pick Assignment", roll_pick_assignment)
        targets_by_uom = get_pick_qty_targets_by_uom(assignment_doc)

        if targets_by_uom:
            prior_lists = frappe.get_all(
                "Roll Wise Pick List",
                filters={"roll_pick_assignment": roll_pick_assignment, "docstatus": 1},
                pluck="name",
            )
            prior_by_uom = {}
            if prior_lists:
                prior_rows = frappe.get_all(
                    "Roll Wise Pick Item",
                    filters={"parenttype": "Roll Wise Pick List", "parent": ["in", prior_lists]},
                    fields=["qty", "uom"],
                )
                for r in prior_rows:
                    u = r.uom or "Kgs"
                    prior_by_uom[u] = prior_by_uom.get(u, 0.0) + flt(r.qty)

            this_by_uom = {}
            for r in rolls:
                u = r.get("uom") or "Kgs"
                this_by_uom[u] = this_by_uom.get(u, 0.0) + flt(r.get("qty"))

            for uom, target in targets_by_uom.items():
                if not target:
                    continue
                total_picked = prior_by_uom.get(uom, 0.0) + this_by_uom.get(uom, 0.0)
                tolerance = target * 0.03
                if not (target - tolerance <= total_picked <= target + tolerance):
                    frappe.throw(_(
                        "Picked quantity {0} {1} is outside the allowed \u00b13% tolerance for "
                        "the {1} target {2} (Pick Order {3})"
                    ).format(round(total_picked, 3), uom, target, roll_pick_assignment))

    try:
        # Per-batch warehouse override, from the Roll Pick Assignment's own
        # Batch Items table (batch -> warehouse), when this fulfillment
        # comes from the Pick Order flow. A batch doesn't necessarily sit
        # in the blanket Source Warehouse selected on the execution page —
        # the supervisor's per-batch warehouse (the one get_warehouses_for_batch
        # in textiles_and_garments showed available qty for when the
        # Assignment was built) is the one actually known to hold that
        # batch's stock, so the Stock Entry rows consuming it need to be
        # built against THAT warehouse — otherwise ERPNext's own
        # insufficient-batch-qty check fires against the wrong warehouse
        # ("Batch X only has 0 kg in <blanket source>, but Y kg was
        # entered"). Falls back to source_warehouse for any batch with no
        # warehouse set on its row (that field is optional) or when this
        # isn't a Pick Order fulfillment at all.
        batch_warehouse_overrides = get_batch_warehouse_overrides(roll_pick_assignment)

        def _warehouse_for_batch(batch_no):
            return batch_warehouse_overrides.get(batch_no) or source_warehouse

        # ── STEP 1: Roll Wise Pick List ─────────────────────────────────────
        batch_wise = {}
        for roll in rolls:
            key = (roll.get("batch_no"), roll.get("item_code"))
            b = batch_wise.setdefault(key, {
                "item_code": roll.get("item_code"),
                "warehouse": _warehouse_for_batch(roll.get("batch_no")),
                "batch":     roll.get("batch_no"),
                "qty":       0.0,
                "uom":       roll.get("uom"),
            })
            b["qty"] += float(roll.get("qty") or 0)

        is_batch_transfer = all(
            r.get("roll_no") == r.get("batch_no") for r in rolls
        )
        primary_batch = batch_no or rolls[0].get("batch_no")

        pick_list = frappe.new_doc("Roll Wise Pick List")
        pick_list.posting_date = posting_date
        pick_list.warehouse    = source_warehouse
        pick_list.batch        = primary_batch

        for b in batch_wise.values():
            pick_list.append("batch_wise_pick_item", {
                "item_code": b["item_code"],
                "warehouse": b["warehouse"],
                "batch":     b["batch"],
                "qty":       b["qty"],
                "uom":       b["uom"],
            })

        if not is_batch_transfer:
            for r in rolls:
                pick_list.append("roll_wise_pick_item", {
                    "item_code": r.get("item_code"),
                    "warehouse": _warehouse_for_batch(r.get("batch_no")),
                    "batch":     r.get("batch_no"),
                    "roll_no":   r.get("roll_no"),
                    "qty":       float(r.get("qty") or 0),
                    "uom":       r.get("uom"),
                })

        pick_list.insert(ignore_permissions=True)
        pick_list.submit()

        # ── STEP 2: Stock Entry ──────────────────────────────────────────────
        stock_entry_items = {}
        for r in rolls:
            key = (r.get("item_code"), r.get("batch_no"))
            se_item = stock_entry_items.setdefault(key, {
                "item_code":   r.get("item_code"),
                "s_warehouse": _warehouse_for_batch(r.get("batch_no")),
                "t_warehouse": target_warehouse,
                "batch_no":    r.get("batch_no"),
                "qty":         0.0,
                "uom":         r.get("uom"),
            })
            se_item["qty"] += float(r.get("qty") or 0)

        naming_series = "MT/26/" if pick_type == "To Work Order" else "BM/26/"

        se = frappe.new_doc("Stock Entry")
        se.naming_series         = naming_series
        se.stock_entry_type      = "Material Transfer"
        se.purpose               = "Material Transfer"
        se.company               = frappe.defaults.get_user_default("Company")
        # Explicitly set both posting_date AND posting_time (with
        # set_posting_time flagged on). Leaving posting_time unset here
        # used to crash with "combine() argument 2 must be datetime.time,
        # not None" — the auto-created Serial and Batch Bundle rows (from
        # use_serial_batch_fields=1 below) build a posting datetime via
        # datetime.combine(posting_date, posting_time) before Stock
        # Entry's own validate() gets a chance to default posting_time
        # to nowtime() for us.
        se.set_posting_time      = 1
        se.posting_date          = posting_date
        se.posting_time          = nowtime()
        se.custom_roll_wise_pick_list = pick_list.name

        # Stock Entry already ships with source_warehouse_address /
        # target_warehouse_address (standard fields, Link -> Address) —
        # normally auto-filled by the Desk form's JS when from_warehouse /
        # to_warehouse change. Since this Stock Entry is built server-side,
        # that JS never runs, so we fetch and set both explicitly here.
        # Applies to every pick_type — _get_warehouse_address() just returns
        # None when a warehouse has no linked Address, so this is harmless
        # for warehouses that don't have one set up.
        se.from_warehouse = source_warehouse
        se.to_warehouse   = target_warehouse
        se.source_warehouse_address = _get_warehouse_address(source_warehouse)
        se.target_warehouse_address = _get_warehouse_address(target_warehouse)

        for item in stock_entry_items.values():
            se.append("items", {
                "s_warehouse":  item["s_warehouse"],
                "t_warehouse":  item["t_warehouse"],
                "item_code":    item["item_code"],
                "qty":          item["qty"],
                "transfer_qty": item["qty"],
                "uom":          item["uom"],
                "stock_uom":    item["uom"],
                "conversion_factor": 1,
                "batch_no":     item["batch_no"],
                "use_serial_batch_fields": 1,
                "allow_zero_valuation_rate": 0,
            })

        for b in batch_wise.values():
            rolls_in_batch = [r for r in rolls if r.get("batch_no") == b["batch"]]
            se.append("custom_batch_wise_packing_summary", {
                "batch": b["batch"],
                "qty":   b["qty"],
                "no_of_rolls": 0 if is_batch_transfer else len(rolls_in_batch),
            })

        if pick_type and pick_type != "Manual Roll Pick" and document_name:
            if pick_type in ("From Work Order", "To Work Order"):
                se.work_order = document_name
                if pick_type == "To Work Order":
                    # Pull straight from the Work Order rather than trust
                    # whatever the caller passed through — the Work Order is
                    # the authoritative record of what's actually being
                    # manufactured (Roll Pick Assignment.project is set once
                    # at Assignment-creation time and can drift from it, and
                    # a caller isn't guaranteed to pass project at all).
                    wo_details = frappe.db.get_value(
                        "Work Order", document_name,
                        ["project", "commercial_name", "color", "required_dia"],
                        as_dict=True,
                    )
                    if wo_details:
                        if wo_details.project:
                            project = wo_details.project
                        se.fabric_name = wo_details.commercial_name
                        se.colour = wo_details.color
                        if wo_details.required_dia:
                            se.finishing_dia = str(wo_details.required_dia)
            elif pick_type == "From Purchase Order":
                se.purchase_order = document_name
            elif pick_type in ("To Subcontracting Order", "From Subcontracting Order"):
                se.subcontracting_order = document_name
            elif pick_type == "From Stock Entry":
                se.custom_reference_stock_entry = document_name
            elif pick_type == "From Batch":
                se.custom_reference_batch = document_name

        if project:
            se.project = project
        if from_work_order:
            se.custom_from_work_order = from_work_order
        if from_subcontracting:
            se.custom_from_subcontracting = from_subcontracting

        se.insert(ignore_permissions=True)
        if cint(submit_stock_entry):
            se.submit()

        # Trace this Stock Entry back to the Pick Order it fulfilled (if any)
        # and close the Order out. Reuses the same Stock Entry, same rules,
        # same warehouse-sync hook — this is not a separate code path, just
        # an extra reference stamped on afterward.
        #
        # Status only goes to "Completed" once the Stock Entry itself is
        # submitted — a draft Stock Entry means the material hasn't
        # actually moved yet, so the Assignment is still "In Progress"
        # (someone still needs to review and submit that Stock Entry
        # before this pick is truly done).
        if roll_pick_assignment:
            pick_list.db_set("roll_pick_assignment", roll_pick_assignment, update_modified=False)
            frappe.db.set_value(
                "Roll Pick Assignment", roll_pick_assignment, "status",
                "Completed" if cint(submit_stock_entry) else "In Progress",
            )

        frappe.db.commit()

        total_qty = sum(float(r.get("qty") or 0) for r in rolls)

        return {
            "success": True,
            "message": (
                "Roll Wise Pick List and Stock Entry created successfully"
                if cint(submit_stock_entry)
                else "Roll Wise Pick List created; Stock Entry saved as draft"
            ),
            "pick_list": pick_list.name,
            "stock_entry": se.name,
            "stock_entry_submitted": bool(cint(submit_stock_entry)),
            "transfer_type": "batch" if is_batch_transfer else "roll",
            "entry_type": "Material Transfer",
            "data": {
                "posting_date": posting_date,
                "pick_type": pick_type,
                "document": document_name,
                "project": project,
                "target_warehouse": target_warehouse,
                "source_warehouse": source_warehouse,
                "batch_no": primary_batch,
                "rolls_count": 0 if is_batch_transfer else len(rolls),
                "total_weight": round(total_qty, 2),
                "batches": len(batch_wise),
                "items": len(stock_entry_items),
            }
        }

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "create_roll_picking_entry")
        frappe.throw(str(e))
