/**
 * DAVOMAT — bir martalik eksport (saytga ko'chirish uchun).
 *
 * Davomatning xodimlar ro'yxati, ish vaqtlari, dam kunlari, bayramlar, ta'tillar,
 * qo'shimcha ballar, oy/yil xodimlari, guruhlar va sozlamalari jadvalda emas,
 * skript xotirasida (ScriptProperties) saqlanadi. Bu funksiya ularni «DavomatExport»
 * varag'iga yozadi — keyin jadvalni .xlsx qilib yuklab, saytga import qilasiz.
 *
 * Qanday ishlatiladi:
 *   1) Jadval → Kengaytmalar → Apps Script → yangi fayl (+) → shu kodni joylang → Saqlash
 *   2) Yuqoridagi ro'yxatdan «davomatExport» ni tanlab ▶ Ishga tushirish
 *   3) Jadvalda «DavomatExport» varag'i paydo bo'ladi. Hech narsa o'chirilmaydi.
 */
function davomatExport() {
  var props = PropertiesService.getScriptProperties().getProperties();
  var rows = Object.keys(props)
    .filter(function (k) { return k.indexOf('dv_') === 0 && k.indexOf('dv_f_') !== 0; }) // dv_f_ — kunlik eslatma belgilari, kerak emas
    .sort()
    .map(function (k) { return [k, props[k]]; });
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName('DavomatExport') || ss.insertSheet('DavomatExport');
  sh.clear();
  sh.getRange(1, 1, 1, 2).setValues([['Kalit', 'Qiymat']]);
  if (rows.length) sh.getRange(2, 1, rows.length, 2).setNumberFormat('@').setValues(rows);
  SpreadsheetApp.getUi().alert("✅ " + rows.length + " ta yozuv «DavomatExport» varag'iga yozildi.");
}
