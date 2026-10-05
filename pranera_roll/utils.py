import frappe


def knit_app_owns_hooks():
	"""True while pranera_knit is installed on this site.

	pranera_knit already registers the exact same doc_events this app
	carries (Roll Pick Assignment.validate, Roll Wise Pick List.validate,
	Stock Entry on_submit/on_cancel). Running both copies would just do the
	same work twice on every save, so this app's handlers stand down while
	pranera_knit is present and take over automatically if it is ever
	uninstalled — no hooks.py edit needed either way.
	"""
	return "pranera_knit" in frappe.get_installed_apps()
