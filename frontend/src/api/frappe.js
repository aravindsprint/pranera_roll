// src/api/frappe.js — Pranera Roll App
// Trimmed copy of pranera_knit's API layer: only what My Pick Orders,
// Pick Order Execution, Create Rolls and Rolls actually use.
//
// Shared site-level Server Scripts still called from here (they live on
// erp.pranera.in, not in either app): knit_get_csrf, knit_cut_roll,
// knit_create_po_so_roll, knit_get_po_items, knit_get_so_items — and, from
// RollsPage, knit_create_roll / knit_save_roll_data / knit_delete_roll.

// ── Connectivity signal ───────────────────────────────────────────────────
// Any HTTP answer from the server (other than a gateway error) proves the
// network path works. useSync listens for this and flips the app back online
// even if its own probe failed/timed out — so a real request can never be
// blocked by a stale "offline" flag.
function signalServerReachable(res) {
  const s = res && res.status
  if (s && s !== 502 && s !== 503 && s !== 504) {
    try { window.dispatchEvent(new Event('roll:api-ok')) } catch { /* ignore */ }
  }
}

// ── CSRF ──────────────────────────────────────────────────────────────────
let _csrf = ''

function getCookieValue(name) {
  return document.cookie
    .split('; ')
    .find(r => r.startsWith(name + '='))
    ?.split('=')[1] || ''
}

export async function ensureCSRF() {
  // 1. Already cached
  if (_csrf) return _csrf
  // 2. Injected by Jinja (production)
  if (window.csrf_token) { _csrf = window.csrf_token; return _csrf }
  // 3. Cookie fallback
  const cookie = getCookieValue('csrftoken') || getCookieValue('X-Frappe-CSRF-Token')
  if (cookie) { _csrf = cookie; return _csrf }
  // 4. Fetch from Server Script (dev proxy)
  try {
    const r = await fetch('/api/method/knit_get_csrf', { credentials: 'include' })
    if (r.ok) {
      const d = await r.json()
      if (d?.message) { _csrf = d.message; window.csrf_token = d.message }
      else console.warn('ensureCSRF: knit_get_csrf returned no token (no session/sid cookie?)')
    } else {
      console.warn('ensureCSRF: knit_get_csrf HTTP', r.status)
    }
  } catch(e) {
    console.warn('ensureCSRF: knit_get_csrf failed', e)
  }
  return _csrf
}

// Forget the cached CSRF token so the next ensureCSRF() call re-fetches it.
// Required after login/logout, since both actions issue a brand new session
// (and therefore a brand new token) — reusing the old one causes silent
// CSRFTokenError 403s on the very next authenticated request.
export function resetCSRF() {
  _csrf = ''
  window.csrf_token = ''
}

export async function initCSRF() {
  window.__FRAPPE_SESSION__ = {
    user: decodeURIComponent(getCookieValue('user_id') || '') || 'Guest',
    base_url: ''
  }
  // Pre-warm the token so first API call doesn't need to fetch it
  await ensureCSRF()
  // Keep csrf_token on the session object too — logout()/other callers read
  // it from here, and previously this field was silently dropped because
  // this function replaces window.__FRAPPE_SESSION__ wholesale.
  window.__FRAPPE_SESSION__.csrf_token = _csrf
  console.log('Session user:', window.__FRAPPE_SESSION__.user, '| CSRF:', _csrf ? '✓' : '✗')
}

// True once we've established the browser holds a real (non-Guest) Frappe
// session. Call initCSRF() first so window.__FRAPPE_SESSION__ is current.
export function isLoggedIn() {
  const user = window.__FRAPPE_SESSION__?.user
  return !!user && user !== 'Guest'
}

// ── Core fetch helpers ────────────────────────────────────────────────────
export async function call(method, args = {}) {
  const token = await ensureCSRF()
  const body = new URLSearchParams()
  for (const [k, v] of Object.entries(args)) {
    // Skip omitted/absent params entirely rather than letting
    // URLSearchParams.append coerce `undefined`/`null` into the literal
    // string "undefined"/"null" — that string then reaches the Python
    // method as a real (invalid) value instead of the missing arg its
    // `=None` default expects, which for a Link field trips validation
    // with a confusing "Could not find <Field>: undefined" error.
    if (v === undefined || v === null) continue
    body.append(k, typeof v === 'object' ? JSON.stringify(v) : v)
  }
  const res = await fetch(`/api/method/${method}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-Frappe-CSRF-Token': token
    },
    body: body.toString(),
    credentials: 'include'
  })
  signalServerReachable(res)
  const data = await res.json()
  if (!res.ok || data.exc) throw new Error(extractServerError(data, res.statusText))
  return data
}

// Turn Frappe's error payload into a short human-readable message
// instead of dumping the entire Python traceback into the UI.
function extractServerError(data, fallback = 'Request failed') {
  // 1. _server_messages: JSON array of JSON strings, last one is most relevant
  try {
    const msgs = JSON.parse(data._server_messages || '[]')
    if (msgs.length) {
      const last = JSON.parse(msgs[msgs.length - 1])
      const text = String(last.message || last)
        .replace(/<[^>]+>/g, '')   // strip HTML tags
        .trim()
      if (text) return text
    }
  } catch { /* fall through */ }
  // 2. data.exception: "module.path.ErrorClass: message" — keep the message part
  if (data.exception) {
    const parts = String(data.exception).split(':')
    return (parts.length > 1 ? parts.slice(1).join(':') : parts[0]).trim()
  }
  // 3. Last line of the traceback, if that's all we have
  if (data.exc) {
    try {
      const tb = JSON.parse(data.exc)
      const lines = String(tb[0] || '').trim().split('\n')
      return lines[lines.length - 1].trim()
    } catch { /* fall through */ }
  }
  return fallback
}

export async function getList(doctype, { filters = [], orFilters = [], fields = ['name'], limit = 200, orderBy } = {}) {
  const params = new URLSearchParams({
    filters: JSON.stringify(filters),
    fields: JSON.stringify(fields),
    limit_page_length: limit,
    ...(orFilters && orFilters.length ? { or_filters: JSON.stringify(orFilters) } : {}),
    ...(orderBy ? { order_by: orderBy } : {})
  })
  const res = await fetch(`/api/resource/${encodeURIComponent(doctype)}?${params}`, {
    credentials: 'include'
  })
  signalServerReachable(res)
  const data = await res.json()
  if (!res.ok) throw new Error(data.exc || res.statusText)
  return data.data || []
}

// Paginated variant of getList — fetches EVERY matching row, not just the
// first page. Frappe's REST list endpoint silently truncates at whatever
// limit_page_length you pass, and with no explicit order_by it sorts by
// "modified desc" across the WHOLE doctype (not just this app's records) —
// so a plain single-request limit can drop rows in an unpredictable way
// (e.g. an entire warehouse building missing from the dropdown because its
// records happen to be older than 500 other, unrelated warehouses site-wide).
// Pages through with limit_start until a page comes back short.
export async function getAllList(doctype, { filters = [], orFilters = [], fields = ['name'], pageSize = 500, orderBy = 'name asc', maxPages = 40 } = {}) {
  const all = []
  let start = 0
  for (let page = 0; page < maxPages; page++) {
    const params = new URLSearchParams({
      filters: JSON.stringify(filters),
      fields: JSON.stringify(fields),
      limit_page_length: pageSize,
      limit_start: start,
      order_by: orderBy,
      ...(orFilters && orFilters.length ? { or_filters: JSON.stringify(orFilters) } : {})
    })
    const res = await fetch(`/api/resource/${encodeURIComponent(doctype)}?${params}`, {
      credentials: 'include'
    })
    signalServerReachable(res)
    const data = await res.json()
    if (!res.ok) throw new Error(data.exc || res.statusText)
    const rows = data.data || []
    all.push(...rows)
    if (rows.length < pageSize) break // last page reached
    start += pageSize
  }
  return all
}

export async function getDoc(doctype, name) {
  const res = await fetch(
    `/api/resource/${encodeURIComponent(doctype)}/${encodeURIComponent(name)}`,
    { credentials: 'include' }
  )
  const data = await res.json()
  if (!res.ok) throw new Error(data.exc || res.statusText)
  return data.data
}

export async function createDoc(doctype, doc) {
  const token = await ensureCSRF()
  const res = await fetch(`/api/resource/${encodeURIComponent(doctype)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Frappe-CSRF-Token': token },
    body: JSON.stringify(doc),
    credentials: 'include'
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.exc || res.statusText)
  return data.data
}

export async function updateDoc(doctype, name, doc) {
  const token = await ensureCSRF()
  const res = await fetch(
    `/api/resource/${encodeURIComponent(doctype)}/${encodeURIComponent(name)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-Frappe-CSRF-Token': token },
      body: JSON.stringify(doc),
      credentials: 'include'
    }
  )
  const data = await res.json()
  if (!res.ok) throw new Error(data.exc || res.statusText)
  return data.data
}

// ── Domain helpers ────────────────────────────────────────────────────────
export const getEmployeeDetails = (username) =>
  getList('Employee', {
    filters: [['Employee', 'user_id', '=', username]],
    fields: ['*'],
    limit: 1
  })

// ── Lookup syncs (cached in IndexedDB by useSync / used by Create Rolls) ──
export const syncWarehouses = () => getAllList('Warehouse', { fields: ['name', 'warehouse_name', 'modified'],      pageSize: 500, orderBy: 'name asc' })

// Purchase Orders / Subcontracting Orders — used by the Roll-wise Pick List's
// "From Purchase Order" / "To|From Subcontracting Order" pick types. These were
// missing entirely before, so those pick types always showed "No matches".
export const syncPurchaseOrders = () =>
  getAllList('Purchase Order', {
    filters: [['Purchase Order', 'docstatus', '!=', 2]],
    fields: ['name', 'supplier', 'status', 'transaction_date', 'modified'],
    pageSize: 500,
    orderBy: 'modified desc'
  })

export const syncSubcontractingOrders = () =>
  getAllList('Subcontracting Order', {
    filters: [['Subcontracting Order', 'docstatus', '!=', 2]],
    fields: ['name', 'supplier', 'status', 'transaction_date', 'modified', 'purchase_order'],
    pageSize: 500,
    orderBy: 'modified desc'
  })

// ── Pick Order (supervisor-assigned pick tasks) ──────────────────────────────
export const getMyPickOrders = () =>
  call('pranera_roll.api.pick_order.get_my_pick_orders').then(r => r.message || [])

export const getPickOrderDetail = (name) =>
  call('pranera_roll.api.pick_order.get_pick_order_detail', { name }).then(r => r.message)

export const scanPickOrderRoll = (pickOrder, rollNo, sourceWarehouse) =>
  call('pranera_roll.api.pick_order.scan_pick_order_roll', {
    pick_order: pickOrder, roll_no: rollNo, source_warehouse: sourceWarehouse
  }).then(r => r.message)

export const removeScannedRoll = (pickOrder, rollNo) =>
  call('pranera_roll.api.pick_order.remove_scanned_roll', {
    pick_order: pickOrder, roll_no: rollNo
  }).then(r => r.message)

// Persists the worker's Source/Target Warehouse choice for this execution
// session, independent of scanning — so a resumed session (refresh, next
// shift, different device) shows the same choice instead of snapping back
// to the Assignment's original warehouses. Pass only the one(s) that changed.
export const updatePickOrderExecution = (pickOrder, { sourceWarehouse, targetWarehouse } = {}) =>
  call('pranera_roll.api.pick_order.update_pick_order_execution', {
    pick_order: pickOrder,
    source_warehouse: sourceWarehouse,
    target_warehouse: targetWarehouse,
  }).then(r => r.message)

// submitStockEntry: true (default) submits the Stock Entry immediately —
// "Create Pick Entry - Submit". false leaves it as a draft for later
// review — "Create Pick Entry - Draft". The Roll Wise Pick List is always
// submitted either way; this only affects the Stock Entry's docstatus.
export const submitPickOrder = (pickOrder, postingDate, submitStockEntry = true) =>
  call('pranera_roll.api.pick_order.submit_pick_order', {
    pick_order: pickOrder, posting_date: postingDate,
    submit_stock_entry: submitStockEntry ? 1 : 0,
  }).then(r => r.message)

// ── Create Rolls page (Cut Rolls / Purchase Order / Subcontract Order) ──────
// Backed by Server Scripts already live on erp.pranera.in:
// knit_cut_roll, knit_create_po_so_roll, knit_get_po_items, knit_get_so_items.
// All three roll-creation paths share the same "next numeric roll_no, not a
// KCC-prefixed one" sequence (MAX(CAST(name AS UNSIGNED)) WHERE name REGEXP
// '^[0-9]+$'), enforced server-side — nothing to duplicate here.

export const getPOItems = (purchaseOrder) =>
  call('knit_get_po_items', { purchase_order: purchaseOrder }).then(r => r.message || [])

export const getSOItems = (subcontractingOrder) =>
  call('knit_get_so_items', { subcontracting_order: subcontractingOrder }).then(r => r.message || [])

export const createPOSORoll = (payload) =>
  call('knit_create_po_so_roll', payload).then(r => r.message)

export const cutRoll = (payload) =>
  call('knit_cut_roll', payload).then(r => r.message)

// Search rolls by roll no / item code / commercial name for the Cut Rolls
// picker on the Create Rolls page. Excludes cancelled rolls.
export const searchRollsForCut = (txt) =>
  getList('Roll', {
    filters: [['Roll', 'docstatus', '!=', 2]],
    orFilters: [
      ['Roll', 'name', 'like', `%${txt}%`],
      ['Roll', 'item_code', 'like', `%${txt}%`],
      ['Roll', 'commercial_name', 'like', `%${txt}%`]
    ],
    fields: [
      'name', 'item_code', 'item_name', 'commercial_name', 'color', 'width',
      'stock_uom', 'batch', 'roll_weight', 'total_qty', 'project',
      'work_order', 'purchase_order', 'subcontracting_order', 'job_card',
      'warehouse', 'knit_operator', 'knit_operator_name'
    ],
    limit: 25,
    orderBy: 'creation desc'
  })

// Batches for a given item — used by the Purchase Order / Subcontract Order
// tabs on the Create Rolls page (batch is optional there).
export const getBatchesForItemCode = (itemCode) =>
  getList('Batch', {
    filters: [['Batch', 'item', '=', itemCode]],
    fields: ['name', 'batch_id', 'item'],
    limit: 200,
    orderBy: 'creation desc'
  })

// ── Verify Rolls page ───────────────────────────────────────────────────────
// Backed by textiles_and_garments/api/verify_rolls.py (Textiles And Garments
// app). The put-away Stock Entry, its duplicate guard and the Roll.warehouse
// sync all live there.
const VR = 'textiles_and_garments.api.verify_rolls'

export const searchMaterialTransfers = (txt) =>
  call(`${VR}.search_material_transfers`, { txt }).then(r => r.message || [])

// scanned may be the raw 2D-barcode text (name, desk URL, print URL…) —
// the server works out the Stock Entry name.
export const getTransferForVerification = (scanned) =>
  call(`${VR}.get_transfer_for_verification`, { stock_entry: scanned }).then(r => r.message)

export const searchBins = (txt, nearWarehouse, company) =>
  call(`${VR}.search_bins`, { txt, near_warehouse: nearWarehouse, company }).then(r => r.message || [])

// rolls: [{ roll_no, bin }] — must cover every roll on the transfer.
export const createVerifiedTransfer = (stockEntry, rolls, postingDate, submit = true) =>
  call(`${VR}.create_verified_transfer`, {
    stock_entry: stockEntry, rolls, posting_date: postingDate, submit: submit ? 1 : 0,
  }).then(r => r.message)
