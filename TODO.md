1. Barcha zakazga (Order) oid modellarni admin qismida order.id, order.status va order.show_days atrubutlarini adminkada korsat changelistda (PriceAdmin,DesignAdmin, DetailngAdmin, RoverAdmin, PainterAdmin, AssemblyAdmin larda )

2. Zakaz sozdat qilganda count_days ni obezatilniy qil.bunda kelip chiqadiki end_date ham nullable boladi, agar end date bolmasa zakaz statusi ojidaniyada bolsin

3. Order.id ni adminkada editable qil

4. PriceAdminda metering nullable bolgan instancelani aloxida korsatip, wunaqa instance larni sozdat qiladigan qil. hozirda sozdat qilgan adminka orqali owibka chiqvotti

5. Harx chiqarish PriceAdminni yaxshilab test qil, hozirda dinamik inline bor uyerda wu dinamik inline mukammal iwlamayti. 

6. Filer da imagelarni spiskasi ochilganda imageni bosa yangi oynaga otip ketvotti. shunga yangi template och. u teplateda misol uchun rasm tanlaganda Preview bolishi kerak va ongga chapga otkazip keyingi rasmlarni korish imkoni bolishi kerak, stilizatsiyasini ham chiroyli qil

Bu topshiriqlarni hammasini bittada bajar keyin test qil keyin review qil

hozirdagi errorlar

-----------------------------

KeyError at /admin/order/order/add/
'order_number'
Request Method:	GET
Request URL:	https://ser-mebel.uz/admin/order/order/add/?client=%2B998909868887&address=%D0%AD%D0%A8%D0%9E%D0%9D%D0%93%D0%A3%D0%97%D0%90%D0%A0&address_link=https%3A%2F%2Fwww.google.com%2Fmaps%2Fplace%2F41%25C2%25B014%2753.9%2522N%2B69%25C2%25B008%2727.1%2522E%2F%4041.248291%2C69.140872%2C16z%2Fdata%3D%214m4%213m3%218m2%213d41.248291%214d69.140872%3Fentry%3Dttu%26g_ep%3DEgoyMDI2MDcwNS4wIKXMDSoASAFQAw%253D%253D&reception_date=08.07.2026&metering=123&price=
Django Version:	5.2.4

---------------------------


TypeError at /admin/price/price/add/
the JSON object must be str, bytes or bytearray, not list
Request Method:	POST
Request URL:	https://ser-mebel.uz/admin/price/price/add/?_changelist_filters=done%3DFalse
Django Version:	5.2.4


---------------------------


TypeError at /admin/price/price/99/change/
the JSON object must be str, bytes or bytearray, not list
Request Method:	POST
Request URL:	https://ser-mebel.uz/admin/price/price/99/change/
Django Version:	5.2.4
Exception Type:	TypeError
Exception Value:	
the JSON object must be str, bytes or bytearray, not list
Exception Location:	/usr/local/lib/python3.10/json/__init__.py, line 339, in loads
Raised during:	django.contrib.admin.options.change_view
Python Executable:	/usr/local/bin/python3.10