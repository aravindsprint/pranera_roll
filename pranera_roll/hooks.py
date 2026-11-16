from . import __version__ as app_version

app_name        = "pranera_roll"
app_title       = "Pranera Roll"
app_publisher   = "Pranera Services & Solutions"
app_description = "Roll picking & roll management floor app for ERPNext"
app_email       = "admin@pranera.in"
app_license     = "MIT"
app_version     = "1.0.0"

# Roll, Roll Pick Assignment, Roll Wise Pick List and Roll Packing List are
# owned by the Textiles And Garments app; this app only adds a front-end and
# the worker-side pick-order API on top of them.
required_apps = ["erpnext"]

add_to_apps_screen = [
    {
        "name": "pranera_roll",
        "logo": "/assets/pranera_roll/images/logo.svg",
        "title": "Roll App",
        "route": "/roll-app",
    }
]

website_route_rules = [
    {"from_route": "/roll-app/<path:app_path>", "to_route": "roll-app"},
]

# ── Document event hooks ──────────────────────────────────────────────────────
# Same handlers as pranera_knit. Each one returns immediately while
# pranera_knit is installed on the site (see utils.knit_app_owns_hooks), so
# the two apps never double-process a save; if pranera_knit is ever
# uninstalled, these take over with no config change.
doc_events = {
    "Stock Entry": {
        "on_submit": [
            "pranera_roll.roll_wise_pick_list_events.on_stock_entry_submit",
            "pranera_roll.outward_request_events.on_stock_entry_change",
        ],
        "on_cancel": [
            "pranera_roll.roll_wise_pick_list_events.on_stock_entry_cancel",
            "pranera_roll.outward_request_events.on_stock_entry_change",
        ],
    },
    "Roll Pick Assignment": {
        "validate": "pranera_roll.pick_qty_summary.set_pick_qty_summary",
        # Outward Request status tracking (stands down while pranera_knit
        # is installed — see outward_request_events.py).
        "on_submit": "pranera_roll.outward_request_events.on_roll_pick_assignment_change",
        "on_cancel": "pranera_roll.outward_request_events.on_roll_pick_assignment_change",
        "on_update_after_submit": "pranera_roll.outward_request_events.on_roll_pick_assignment_change",
    },
    "Roll Wise Pick List": {
        "validate": "pranera_roll.roll_wise_pick_list_events.set_batch_wise_weight",
        "on_submit": "pranera_roll.outward_request_events.on_roll_wise_pick_list_change",
        "on_cancel": "pranera_roll.outward_request_events.on_roll_wise_pick_list_change",
    },
    # Outward Request — one request per Work Order, From building, row
    # warehouses (always on); base validation / on_trash only when
    # pranera_knit isn't installed.
    "Outward Request": {
        "validate": "pranera_roll.outward_request_events.validate_outward_request",
        "on_trash": "pranera_roll.outward_request_events.on_trash_outward_request",
    },
}

fixtures = [
    # Shared worker role for the Roll Pick Assignment flow (same record
    # pranera_knit ships — syncing it from both apps is harmless).
    {"doctype": "Role", "filters": [["name", "in", ["Roll Picker"]]]},
]
