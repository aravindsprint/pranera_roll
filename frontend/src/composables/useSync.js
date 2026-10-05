// src/composables/useSync.js — Pranera Roll App
// Connectivity detection + lookup-table caching.
//
// Trimmed from pranera_knit: the Knit app's offline mutation queue (offline
// roll / QI / job-card writes) belongs to pages that aren't in this app, so
// it's gone. What's kept:
//   * the real-reachability probe (navigator.onLine is unreliable both ways)
//   * self-healing on any successful API answer ('roll:api-ok')
//   * caching the Warehouse list into IndexedDB for the pick-order store
import { ref, onMounted, onUnmounted } from 'vue'
import { db } from '@/db'
import { syncWarehouses } from '@/api/frappe'

export const isOnline   = ref(navigator.onLine)
export const isSyncing  = ref(false)
export const lastSyncAt = ref(null)

let reachTimer = null

const PROBE_URL              = '/api/method/ping'
const PROBE_TIMEOUT_MS       = 8000
const PROBE_EVERY_ONLINE_MS  = 15_000
const PROBE_EVERY_OFFLINE_MS = 4_000

let probeInFlight = null

function normalizeRows(res) {
  if (Array.isArray(res)) return res
  if (Array.isArray(res?.data)) return res.data
  if (Array.isArray(res?.data?.data)) return res.data.data
  if (Array.isArray(res?.message)) return res.message
  return []
}

function setOnline(next) {
  if (isOnline.value === next) return
  isOnline.value = next
  if (next) syncLookupTables()
}

async function probeOnce() {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS)
  try {
    const r = await fetch(`${PROBE_URL}?_=${Date.now()}`, {
      method: 'GET', credentials: 'include', cache: 'no-store', signal: ctrl.signal,
    })
    return !(r.status === 502 || r.status === 503 || r.status === 504)
  } catch {
    return false
  } finally {
    clearTimeout(t)
  }
}

export function checkReachable() {
  if (probeInFlight) return probeInFlight
  probeInFlight = probeOnce()
    .then(reachable => { setOnline(reachable); return reachable })
    .finally(() => { probeInFlight = null })
  return probeInFlight
}

function onApiOk() { if (!isOnline.value) setOnline(true) }

function scheduleProbe() {
  clearTimeout(reachTimer)
  reachTimer = setTimeout(async () => {
    await checkReachable()
    scheduleProbe()
  }, isOnline.value ? PROBE_EVERY_ONLINE_MS : PROBE_EVERY_OFFLINE_MS)
}

export async function syncLookupTables() {
  if (!isOnline.value || isSyncing.value) return
  isSyncing.value = true
  try {
    const rows = normalizeRows(await syncWarehouses())
    await db.warehouses.bulkPut(rows.map(r => ({ ...r, id: r.name })))
    lastSyncAt.value = new Date().toISOString()
    console.log(`Synced ${rows.length} Warehouses`)
  } catch (err) {
    console.warn('Sync failed for Warehouses:', err.message)
  } finally {
    isSyncing.value = false
  }
}

export function useSync() {
  function onOnlineHandler()  { checkReachable() }
  function onOfflineHandler() { checkReachable() }
  function onWake() { if (document.visibilityState === 'visible') checkReachable() }

  onMounted(() => {
    window.addEventListener('online', onOnlineHandler)
    window.addEventListener('offline', onOfflineHandler)
    window.addEventListener('focus', onWake)
    document.addEventListener('visibilitychange', onWake)
    window.addEventListener('roll:api-ok', onApiOk)
    checkReachable()
    scheduleProbe()
    if (isOnline.value) syncLookupTables()
  })

  onUnmounted(() => {
    window.removeEventListener('online', onOnlineHandler)
    window.removeEventListener('offline', onOfflineHandler)
    window.removeEventListener('focus', onWake)
    document.removeEventListener('visibilitychange', onWake)
    window.removeEventListener('roll:api-ok', onApiOk)
    clearTimeout(reachTimer)
  })

  return { isOnline, isSyncing, lastSyncAt, syncLookupTables }
}
