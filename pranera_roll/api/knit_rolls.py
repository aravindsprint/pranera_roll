"""
pranera_roll/api/knit_rolls.py
Python versions of the site-level Server Scripts the roll app used to call
(knit_get_csrf, knit_get_po_items, knit_get_so_items, knit_create_po_so_roll,
knit_cut_roll, knit_create_roll, knit_save_roll_data, knit_delete_roll).

Same arguments and the same response shapes as the Server Scripts on
erp.pranera.in, so the frontend only changes the method path. Differences:
  * every method except get_csrf needs a logged-in user (the Server Scripts
    allowed Guest, so anyone could create / cut / edit rolls);
  * new roll numbers are taken under a database lock (shared with
    roll_management's Receive Rolls), so two devices can't race for one number;
  * cut_roll also moves the cut qty in the Roll Ledger when roll_management
    is installed and enabled;
  * save_roll_data keeps fields the device didn't send instead of blanking them.
The Server Scripts stay on erp.pranera.in for pranera_knit; nothing here
touches them.
"""
import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime, today

ROLL_NO_LOCK = "roll_management_roll_no"  # same lock name as roll_management.receiving


# ── helpers ──────────────────────────────────────────────────────────────────
def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)


def _blank(v):
	return v is None or str(v) in ("", "null", "None", "undefined")


def _lock():
	frappe.db.sql("SELECT GET_LOCK(%s, 30)", ROLL_NO_LOCK)


def _unlock():
	frappe.db.sql("SELECT RELEASE_LOCK(%s)", ROLL_NO_LOCK)


def _next_roll_no():
	"""Next plain-numeric roll number (max + 1). Call while holding the lock."""
	max_no = cint(frappe.db.sql("SELECT MAX(CAST(name AS UNSIGNED)) FROM `tabRoll` WHERE name REGEXP '^[0-9]+$'")[0][0])
	while frappe.db.exists("Roll", str(max_no + 1)):
		max_no += 1
	return str(max_no + 1)


def _item_extras(item_code):
	# commercial_name / color / width are custom Item fields on erp.pranera.in; a new site may lack them
	meta = frappe.get_meta("Item")
	fields = [f for f in ("commercial_name", "color", "width", "stock_uom") if f == "stock_uom" or meta.has_field(f)]
	return frappe.db.get_value("Item", item_code, fields, as_dict=True) or {}


# ── CSRF (dev proxy) ─────────────────────────────────────────────────────────
@frappe.whitelist(allow_guest=True)
def get_csrf():
	"""CSRF token of the caller's own session ('' for Guest). Replaces knit_get_csrf, which
	parsed tabSessions by hand."""
	from frappe.sessions import get_csrf_token

	if frappe.session.user == "Guest":
		return ""
	return get_csrf_token()


# ── Create Rolls page: PO / Subcontracting Order tabs ───────────────────────
@frappe.whitelist()
def get_po_items(purchase_order=None):
	_require_login()
	if not purchase_order:
		frappe.throw(_("purchase_order is required"))
	rows = frappe.db.sql(
		"""SELECT poi.item_code, poi.item_name, poi.material_request AS project, poi.warehouse
		FROM `tabPurchase Order Item` poi WHERE poi.parent = %s ORDER BY poi.idx""",
		purchase_order, as_dict=True,
	)
	for r in rows:
		r.update(_item_extras(r.item_code))
	return rows


@frappe.whitelist()
def get_so_items(subcontracting_order=None):
	_require_login()
	if not subcontracting_order:
		frappe.throw(_("subcontracting_order is required"))
	rows = frappe.db.sql(
		"""SELECT soi.item_code, soi.item_name, soi.project AS project, soi.warehouse
		FROM `tabSubcontracting Order Item` soi WHERE soi.parent = %s ORDER BY soi.idx""",
		subcontracting_order, as_dict=True,
	)
	for r in rows:
		r.update(_item_extras(r.item_code))
	return rows


@frappe.whitelist(methods=["POST"])
def create_po_so_roll(item_code=None, purchase_order="", subcontracting_order="", item_name="",
		commercial_name="", color="", width="", actual_width="", project="", stock_uom="", batch="",
		roll_weight=0, total_qty=0, mistake_qty=0, ok_qty=0, avg_weight_per_pcs=0, **kwargs):
	_require_login()
	if not item_code:
		frappe.throw(_("item_code is required"))
	if not purchase_order and not subcontracting_order:
		frappe.throw(_("purchase_order or subcontracting_order is required"))
	_lock()
	try:
		roll = frappe.new_doc("Roll")
		roll.roll_no = _next_roll_no()
		roll.update({
			"purchase_order": purchase_order or None, "subcontracting_order": subcontracting_order or None,
			"item_code": item_code, "item_name": item_name, "commercial_name": commercial_name, "color": color,
			"width": width, "actual_width": actual_width, "project": project or None, "stock_uom": stock_uom,
			"batch": batch or None, "roll_weight": flt(roll_weight), "total_qty": cint(flt(total_qty)),
			"mistake_qty": cint(flt(mistake_qty)), "correct_qty": cint(flt(ok_qty)),
			"avg_weight_per_pcs": flt(avg_weight_per_pcs), "name_of_the_operator": frappe.session.user,
			"datetime": now_datetime(),
		})
		roll.insert(ignore_permissions=True)
	finally:
		_unlock()
	return {"name": roll.name, "roll_no": roll.roll_no}


# ── Cut Rolls ────────────────────────────────────────────────────────────────
@frappe.whitelist(methods=["POST"])
def cut_roll(source_roll=None, qty=None, roll_weight=None, avg_weight_per_pcs=None,
		knit_machine_no="", knit_shift_no="", **kwargs):
	_require_login()
	if not source_roll:
		frappe.throw(_("source_roll is required"))
	if _blank(qty):
		frappe.throw(_("qty is required"))
	qty = flt(qty)
	if qty <= 0:
		frappe.throw(_("Qty must be greater than 0"))

	src = frappe.get_doc("Roll", source_roll, for_update=True)
	is_pcs = (src.stock_uom or "").strip().lower() == "pcs"
	available = flt(src.total_qty) if is_pcs else flt(src.roll_weight)
	if qty > available:
		frappe.throw(_("Qty {0} exceeds available qty {1} on roll {2}").format(qty, available, source_roll))

	cut_weight = 0.0
	if is_pcs:
		if _blank(roll_weight):
			frappe.throw(_("roll_weight is required when cutting a Pcs roll"))
		cut_weight = flt(roll_weight)
		if cut_weight <= 0:
			frappe.throw(_("roll_weight must be greater than 0"))
		if cut_weight > flt(src.roll_weight):
			frappe.throw(_("Roll Weight {0} exceeds available weight {1} on roll {2}").format(
				cut_weight, flt(src.roll_weight), source_roll))

	# Cut rolls are <root>-<n>, always numbered from the original root roll
	# (cutting 33631-1 gives 33631-2, 33631-3, ...).
	root = source_roll.split("-")[0]
	_lock()
	try:
		max_suffix = 0
		for name in frappe.db.sql_list("SELECT name FROM `tabRoll` WHERE name LIKE %s", (root + "-%",)):
			suffix = name[len(root) + 1:]
			if suffix.isdigit():
				max_suffix = max(max_suffix, int(suffix))
		while frappe.db.exists("Roll", f"{root}-{max_suffix + 1}"):
			max_suffix += 1

		new = frappe.new_doc("Roll")
		new.roll_no = f"{root}-{max_suffix + 1}"
		for f in ("item_code", "item_name", "commercial_name", "color", "width", "actual_width", "stock_uom",
				"project", "batch", "work_order", "purchase_order", "subcontracting_order", "job_card",
				"warehouse", "knit_operator", "knit_operator_name"):
			new.set(f, src.get(f))
		new.name_of_the_operator = frappe.session.user
		new.knitting_machine_no = knit_machine_no or src.knitting_machine_no
		new.shift = knit_shift_no or src.shift
		new.datetime = now_datetime()
		if is_pcs:
			new.total_qty = qty
			new.roll_weight = cut_weight
			if not _blank(avg_weight_per_pcs):
				new.avg_weight_per_pcs = flt(avg_weight_per_pcs)
		else:
			new.roll_weight = qty
		new.insert(ignore_permissions=True)
	finally:
		_unlock()

	remaining = available - qty
	if is_pcs:
		frappe.db.set_value("Roll", source_roll, {
			"total_qty": remaining, "roll_weight": max(0.0, flt(src.roll_weight) - cut_weight)})
	else:
		frappe.db.set_value("Roll", source_roll, "roll_weight", remaining)

	# keep roll_management's Roll Ledger in step (qty in stock UOM: pcs or kg)
	if "roll_management" in frappe.get_installed_apps():
		from roll_management.controllers.ledger import record_roll_split
		record_roll_split(source_roll, new.name, qty, cut_weight if is_pcs else qty)

	return {"name": new.name, "roll_no": new.roll_no, "remaining_qty": remaining, "source_roll": source_roll}


# ── Rolls page (knitting production) ─────────────────────────────────────────
@frappe.whitelist(methods=["POST"])
def create_roll(job_card=None, batch_no="", **kwargs):
	_require_login()
	if not job_card:
		frappe.throw(_("job_card is required"))
	jc = frappe.get_doc("Job Card", job_card)
	_lock()
	try:
		roll = frappe.new_doc("Roll")
		roll.roll_no = _next_roll_no()
		roll.update({"job_card": job_card, "work_order": jc.work_order, "item_code": jc.production_item,
			"item_name": jc.item_name or "", "batch": batch_no or None, "start_time": now_datetime()})
		roll.insert(ignore_permissions=True)
	finally:
		_unlock()
	return [{"name": roll.name, "idx": roll.name, "start_time": str(roll.start_time), "batch_no": batch_no}]


def _parse_dt(val):
	if _blank(val):
		return None
	s = str(val).strip().replace("T", " ").replace("Z", "")
	for ch in ("+", "-"):
		i = s.rfind(ch)
		if i > 10:
			s = s[:i]
	s = s.split(".")[0].strip()
	try:
		return get_datetime(s)
	except Exception:
		return None


def _hms(secs):
	secs = cint(secs) if not _blank(secs) else 0
	return f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"


@frappe.whitelist(methods=["POST"])
def save_roll_data(job_card=None, roll_no=None, **fd):
	_require_login()
	fd = frappe._dict(fd)
	if not job_card:
		frappe.throw(_("job_card is required"))

	# Reuse a roll only when it belongs to the SAME job card: a device that numbered a roll
	# offline (or raced another machine) can send a roll_no now owned by another job card.
	existing, reassigned_from = None, None
	if roll_no:
		try:
			rno = str(int(str(roll_no)))
			if frappe.db.exists("Roll", rno):
				if frappe.db.get_value("Roll", rno, "job_card") == job_card:
					existing = rno
				else:
					reassigned_from = rno
		except Exception:
			pass
	# idempotent replay of a reassigned roll: same job card + same weight -> update it
	if not existing and reassigned_from and flt(fd.roll_weight) > 0:
		existing = frappe.db.get_value("Roll", {"job_card": job_card, "roll_weight": flt(fd.roll_weight)}, "name")

	if existing:
		roll = frappe.get_doc("Roll", existing)
	else:
		_lock()
		try:
			roll = frappe.new_doc("Roll")
			roll.roll_no = _next_roll_no()
			roll.job_card = job_card
			roll.work_order = fd.work_order
			roll.insert(ignore_permissions=True)  # reserve the number while locked
		finally:
			_unlock()

	# Fields the device didn't send keep their current value. (The Server Script blanked them,
	# so a roll made with the Rolls page "Create Roll" button lost the item create_roll set.)
	for f in ("work_order", "item_code", "item_name", "commercial_name", "color", "width", "batch", "shift",
			"project", "knitting_machine_no"):
		if not _blank(fd.get(f)):
			roll.set(f, fd.get(f))
	roll.stock_uom = fd.stock_uom or roll.stock_uom or "Kgs"
	if not _blank(fd.knit_operator_name):
		roll.name_of_the_operator = fd.knit_operator_name
		roll.knit_operator_name = fd.knit_operator_name
	roll.roll_weight = 0.0 if _blank(fd.roll_weight) else flt(fd.roll_weight)
	roll.total_qty = 0 if _blank(fd.total_qty) else cint(flt(fd.total_qty))
	roll.mistake_qty = 0 if _blank(fd.mistake_qty) else cint(flt(fd.mistake_qty))
	roll.correct_qty = roll.total_qty - roll.mistake_qty
	if roll.total_qty > 0:
		roll.avg_weight_per_pcs = roll.roll_weight / roll.total_qty

	# start: keep the EARLIER of the frontend value and the creation stamp (older PWA builds
	# sent the End Roll tap as start_time)
	st, et = _parse_dt(fd.start_time), _parse_dt(fd.end_time)
	existing_st = get_datetime(roll.start_time) if roll.get("start_time") else None
	if st and existing_st:
		roll.start_time = min(st, existing_st)
	elif st:
		roll.start_time = st
	roll.end_time = et or now_datetime()
	roll.datetime = today()
	roll.total_breakdown = _hms(fd.breakdown_time_seconds)
	roll.net_production_time = _hms(fd.net_production_time_seconds)
	roll.efficiency = "0.0%" if _blank(fd.efficiency_percentage) else f"{fd.efficiency_percentage}%"
	roll.warehouse = (frappe.db.get_value("Work Order", roll.work_order, "fg_warehouse") if roll.work_order else None) or ""

	# Batch IDs are computed on the device ({project}/{work_order}); make sure it exists
	if roll.batch and not frappe.db.exists("Batch", roll.batch):
		try:
			frappe.get_doc({"doctype": "Batch", "batch_id": roll.batch, "item": roll.item_code}).insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			pass

	roll.save(ignore_permissions=True)
	return {"success": True, "name": roll.name, "reassigned_from": reassigned_from}


@frappe.whitelist(methods=["POST"])
def delete_roll(roll_name=None, **kwargs):
	_require_login()
	if not roll_name:
		return {"success": False, "error": "roll_name is required"}
	roll = frappe.db.get_value("Roll", roll_name, ["name", "roll_weight", "docstatus"], as_dict=True)
	if not roll:
		return {"success": True, "deleted": roll_name, "note": "already gone"}
	if roll.docstatus == 1:
		return {"success": False, "error": "Cannot delete submitted roll"}
	if flt(roll.roll_weight) > 0:
		return {"success": False, "error": "Roll has weight, cannot delete"}
	frappe.delete_doc("Roll", roll_name, ignore_permissions=True, force=True)
	return {"success": True, "deleted": roll_name}
