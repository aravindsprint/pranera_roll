// Shared html5-qrcode start/stop for every camera-scan page.
//
// Why this exists: each page used to `new Html5Qrcode(...).start()` with no
// guard. A double-tap on "Scan" (or reopening the modal while the previous
// start() was still waiting on getUserMedia) started a SECOND camera request.
// Chrome rejects that overlapping request with NotAllowedError ("Permission
// denied") while the first stream keeps running — so the worker saw a live
// preview with a permission error under it, and the first stream could never
// be stopped because the page had already overwritten its reference.
//
// Here there is only ever one instance app-wide: a new start waits for any
// in-flight start, stops whatever is running, then starts; a transient
// NotAllowed/NotReadable failure is retried once after the old stream has
// been released.
import { Html5Qrcode } from 'html5-qrcode'

let active = null      // the one running Html5Qrcode instance
let pending = null     // promise of an in-flight start/stop

const SCAN_CONFIG = { fps: 10, qrbox: { width: 250, height: 250 }, aspectRatio: 1.0 }

async function stopActive() {
  const inst = active
  active = null
  if (!inst) return
  try {
    if (inst.isScanning) await inst.stop()
    inst.clear()
  } catch (err) {
    console.warn('Failed to stop camera scanner:', err)
  }
}

function friendlyError(err) {
  const name = err?.name || ''
  const msg = String(err?.message || err || '')
  if (name === 'NotAllowedError' || /NotAllowedError|Permission denied/i.test(msg)) {
    return 'Camera permission is blocked for this app. Allow it (address-bar lock icon → '
      + 'Permissions → Camera → Allow, or for the installed app: long-press the icon → '
      + 'App info → Permissions → Camera), then tap Retry.'
  }
  if (name === 'NotReadableError' || /NotReadableError|Could not start video source/i.test(msg)) {
    return 'The camera is being used by another app or tab. Close it, then tap Retry.'
  }
  if (name === 'NotFoundError' || /NotFoundError|Requested device not found/i.test(msg)) {
    return 'No camera was found on this device.'
  }
  return 'Could not access the camera: ' + msg
}

function isRetryable(err) {
  const s = (err?.name || '') + ' ' + String(err?.message || err || '')
  return /NotAllowedError|NotReadableError|Permission denied|Could not start video source/i.test(s)
}

async function doStart(elementId, onScan) {
  await stopActive()
  for (let attempt = 0; attempt < 2; attempt++) {
    const inst = new Html5Qrcode(elementId)
    try {
      await inst.start({ facingMode: 'environment' }, SCAN_CONFIG, onScan, () => {})
      active = inst
      return
    } catch (err) {
      try { inst.clear() } catch (_) { /* element may already be gone */ }
      if (attempt === 0 && isRetryable(err)) {
        await new Promise(r => setTimeout(r, 400)) // let the OS release the old stream
        continue
      }
      throw new Error(friendlyError(err))
    }
  }
}

function enqueue(task) {
  const run = (pending || Promise.resolve()).catch(() => {}).then(task)
  const tracked = run.catch(() => {}).finally(() => { if (pending === tracked) pending = null })
  pending = tracked
  return run
}

/** Start scanning into the element with id `elementId`. Throws an Error with a
 *  worker-readable message on failure. Safe to call repeatedly. */
export function startCameraScanner(elementId, onScan) {
  return enqueue(() => doStart(elementId, onScan))
}

/** Stop the running scanner (if any). Safe to call repeatedly. */
export function stopCameraScanner() {
  return enqueue(stopActive)
}
