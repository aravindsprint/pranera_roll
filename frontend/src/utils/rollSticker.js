// Roll stickers — same markup and 60×75 mm thermal layout as RollsPage / CreateRollsPage
// printSticker(), but prints any number of rolls in one window (one sticker per page).
import QRCode from 'qrcode'

const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))

async function stickerHtml(roll) {
  const weight = Number(roll.roll_weight ?? 0).toFixed(3)
  const qty = Number(roll.total_qty) > 0 ? Number(roll.total_qty) : null
  const mistakeQty = Number(roll.mistake_qty) > 0 ? Number(roll.mistake_qty) : null
  const refNo = roll.work_order || roll.purchase_order || roll.subcontracting_order || ''
  const qrData = `${roll.item_code}#${refNo}#${roll.name}`
  const itemCode = roll.item_code || ''
  const itemFontSize = itemCode.length > 28 ? '6.5pt' : (itemCode.length > 20 ? '7.5pt' : '8.5pt')
  const weightLine = `${weight} kg${qty !== null ? ` · Qty: ${qty}` : ''}${mistakeQty !== null ? ` · Mistake: ${mistakeQty}` : ''}`
  const weightFontSize = weightLine.length > 26 ? '6.5pt' : (weightLine.length > 20 ? '7.5pt' : '8.5pt')
  let qrImg = ''
  try { qrImg = await QRCode.toDataURL(qrData, { width: 200, margin: 1 }) } catch (e) { console.error('QR generation failed:', e) }
  return `<div class="sticker">
  <div class="qr-cell">${qrImg ? `<img src="${qrImg}" style="width:24mm;height:24mm" alt="QR"/>` : ''}</div>
  <table>
    <tr><td class="item-code" style="font-size:${itemFontSize}">${esc(itemCode)}</td></tr>
    <tr><td>${esc(roll.commercial_name)}</td></tr>
    <tr><td>${esc(refNo)}</td></tr>
    <tr><td>${esc(roll.name)}</td></tr>
    <tr><td class="weight-line" style="font-size:${weightFontSize}">${esc(weightLine)}</td></tr>
    ${roll.batch ? `<tr><td>${esc(roll.batch)}</td></tr>` : ''}
  </table>
</div>`
}

/** Open one print window with a sticker per roll. Call from a click handler (pop-up rules). */
export async function printRollStickers(rolls) {
  const list = (rolls || []).filter(Boolean)
  if (!list.length) return
  const w = window.open('', '_blank')
  if (!w) { alert('Allow pop-ups to print.'); return }
  const stickers = (await Promise.all(list.map(stickerHtml))).join('\n')
  w.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Roll Stickers (${list.length})</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:Arial,sans-serif; }
  .sticker { width:50mm; min-height:65mm; border:1px solid #000; display:flex;
             margin:2mm auto 4mm; flex-direction:column; }
  .qr-cell { display:flex; align-items:center; justify-content:center; padding:2mm;
             border-bottom:1px solid #000; flex:0 0 auto; }
  table { width:calc(100% - 0.5cm); margin-left:0.5cm; border-collapse:collapse; flex:1; }
  td { padding:1.1mm 3mm; border-bottom:1px solid #000; font-size:8.5pt; font-weight:800;
       font-family:Arial,Helvetica,sans-serif; color:#000; line-height:1.15;
       word-break:break-word; white-space:normal; overflow-wrap:break-word; }
  td.weight-line { white-space:nowrap; }
  tr:last-child td { border-bottom:none; padding-bottom:1.5mm; }
  .noprint { text-align:center; padding:10px; position:sticky; top:0; background:#fff; }
  .noprint button { padding:7px 18px; margin:0 4px; border-radius:5px; border:none;
    cursor:pointer; font-size:12px; font-weight:600; }
  .btn-p { background:#000; color:#fff; }
  .btn-c { background:#eee; color:#333; }
  @media print {
    .noprint { display:none; }
    .sticker { margin:2mm auto 0; max-height:73mm; overflow:hidden; page-break-after:always; break-after:page; }
    .sticker:last-child { page-break-after:auto; break-after:auto; }
    @page { size:60mm 75mm; margin:0; }
  }
</style>
</head><body>
<div class="noprint">
  <b>${list.length} sticker${list.length > 1 ? 's' : ''}</b>
  <button class="btn-p" onclick="window.print()">🖨 Print</button>
  <button class="btn-c" onclick="window.close()">Close</button>
</div>
${stickers}
</body></html>`)
  w.document.close()
}
