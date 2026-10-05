// src/db/index.js — Pranera Roll App
// Separate IndexedDB database from the Knit app ("PraneraKnitDB") so the two
// PWAs never share or clobber each other's cache on the same device.
//
// The only offline lookup the Roll app pages need is the Warehouse list
// (Source/Target Warehouse pickers on Pick Order Execution). Create Rolls and
// Rolls talk to ERPNext live.
import Dexie from 'dexie'

export const db = new Dexie('PraneraRollDB')

db.version(1).stores({
  warehouses: '&id, warehouse_name, modified',
})

export default db
