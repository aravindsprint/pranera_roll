import os
import frappe

no_cache = 1
no_breadcrumbs = 1
no_sitemap = 1


def get_context(context):
	"""Serves the Roll App SPA shell.

	csrf_token is injected so the Vue app's POST calls work on first load.
	asset_version is a cache-buster for index.css / index.js — Vite always
	gives those two the same filename, so without ?v=<mtime> browsers keep
	serving an old build after a redeploy.
	"""
	context.no_cache = 1
	context.csrf_token = frappe.sessions.get_csrf_token()
	bundle_path = frappe.get_app_path("pranera_roll", "public", "roll_app", "index.js")
	try:
		context.asset_version = int(os.path.getmtime(bundle_path))
	except OSError:
		context.asset_version = ""
