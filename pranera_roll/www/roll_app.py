import re

import frappe

# Frappe v15 maps www/roll-app.html to the controller roll_app.py — hyphens
# in the template name become underscores when it looks for the .py module
# (frappe/website/page_renderers/template_page.py, set_pymodule). A file
# named roll-app.py is never loaded.
no_cache = 1
no_breadcrumbs = 1
no_sitemap = 1

# The <script type="module"> entry and the stylesheets exactly as Vite wrote
# them into the built index.html (hashed filenames, no query string).
_ASSET_TAG = re.compile(
	r'<script\b[^>]*\btype="module"[^>]*></script>'
	r'|<link\b[^>]*\brel="(?:stylesheet|modulepreload)"[^>]*>'
)


def get_context(context):
	"""Serves the Roll App SPA shell.

	csrf_token: injected so the app's POST calls are accepted. Without this
	controller running, Frappe's Jinja (DebugUndefined) printed the literal
	"{{ csrf_token }}" into the page and every POST failed "Invalid Request".

	app_assets: copied from the build's own index.html. Vite names the entry
	index-<hash>.js and the lazy page chunks import that same file, so the
	page must load it by exactly that URL — adding ?v=... made the browser
	evaluate the entry twice (two Vue apps). The hash changes on every build,
	which is also what busts the browser cache after a deploy.
	"""
	context.no_cache = 1
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.app_assets = _built_asset_tags()


def _built_asset_tags():
	path = frappe.get_app_path("pranera_roll", "public", "roll_app", "index.html")
	try:
		with open(path, encoding="utf-8") as f:
			html = f.read()
	except OSError:
		return ""
	return "\n  ".join(m.group(0) for m in _ASSET_TAG.finditer(html))
