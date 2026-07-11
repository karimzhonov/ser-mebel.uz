0. Loyixani yaxshilap tahlil qil, kamchilik va biznes logikadagi hatoliklarni aniqla va ularni hal qil. Django adminga korinadigan barcha tekstlarni ruschanda qil. yozilgan component va templatelarni ham tahlil qil. qulayroq variantlar bolsa ularni iwlat va ozgartir va proektni production holatga keltir

1. Barcha zakazga (Order) oid modellarni admin qismida order.id, order.status va order.show_days atrubutlarini adminkada korsat

2. Zakaz sozdat qilganda count_days ni obezatilniy qil.bunda kelip chiqadiki end_date ham nullable boladi, agar end date bolmasa zakaz statusi ojidaniyada bolsin

3. Order.id ni adminkada editable qil

4. PriceAdminda metering nullable bolgan instancelani aloxida korsatip, wunaqa instance larni sozdat qiladigan qil. hozirda sozdat qilgan adminka orqali owibka chiqvotti

5. Harx chiqarish PriceAdminni yaxshilab test qil, hozirda dinamik inline bor uyerda wu dinamik inline mukammal iwlamayti. 

6. AssemblyAdminda ASSEMBLY_MANAGER_PERMISSION bolgan user hohlagan paytda user atributni ozgartiradigan qilip ber hozirda ogranicheniya bor.

7. Filer da imagelarni spiskasi ochilganda imageni bosa yangi oynaga otip ketvotti. shunga yangi template och. u teplateda misol uchun rasm tanlaganda Preview bolishi kerak va ongga chapga otkazip keyingi rasmlarni korish imkoni bolishi kerak

Bu topshiriqlarni hammasini bittada bajar keyin test qil keyin review qil