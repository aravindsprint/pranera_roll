# Pranera Roll

Roll picking & roll management floor app for ERPNext — a trimmed duplicate of
`pranera_knit` containing only:

| Side menu        | Route                                   | What it does |
|------------------|-----------------------------------------|--------------|
| My Pick Orders   | `/roll-app/my-pick-orders`              | Roll Pick Assignments assigned to the logged-in user → opens **Pick Order Execution** (`/roll-app/roll-wise-pick-order-execution`): QR scan rolls, ±3% tolerance, per-UOM progress, change source/target warehouse, submit as Draft/Submitted Stock Entry |
| Create Rolls     | `/roll-app/create-rolls`                | Cut Rolls / Purchase Order / Subcontract Order tabs, QR label printing |
| Rolls            | `/roll-app/rolls`                       | Search, view, edit, create, delete rolls; Roll Packing List; QR |

## Layout

```
pranera_roll/
├── frontend/                     Vue 3 + Vite PWA source  (npm run build → pranera_roll/public/roll_app)
└── pranera_roll/
    ├── hooks.py                  /roll-app route, doc_events (guarded), Roll Picker role fixture
    ├── utils.py                  knit_app_owns_hooks() guard
    ├── api/pick_order.py         6 worker-side pick-order endpoints
    ├── api/roll_pick.py          create_roll_picking_entry + helpers (from knit.py)
    ├── pick_qty_summary.py       Roll Pick Assignment.validate
    ├── roll_wise_pick_list_events.py   Stock Entry submit/cancel + Roll Wise Pick List.validate
    ├── patches/                  idempotent schema patches (copied from pranera_knit)
    ├── www/roll-app.{html,py}    SPA shell
    └── public/roll_app/          built PWA (committed)
```

## Running side-by-side with pranera_knit

Both apps can live on the same site (erp.pranera.in):

* Separate URL (`/roll-app` vs `/knit-app`), service-worker scope, IndexedDB
  (`PraneraRollDB`) and localStorage keys (`ROLL_*`), so the two PWAs never
  share or clobber cache.
* The doc_event handlers return immediately while `pranera_knit` is
  installed (it already runs the identical logic) and take over automatically
  if it's ever uninstalled.
* Patches are idempotent — no-ops where pranera_knit already applied them.
* Login access uses the same Employee flag as the Knit app
  (`custom_can_access_knitting_app`).

Still depends on the shared site Server Scripts: `knit_get_csrf`,
`knit_cut_roll`, `knit_create_po_so_roll`, `knit_get_po_items`,
`knit_get_so_items`, `knit_create_roll`, `knit_save_roll_data`,
`knit_delete_roll`.
