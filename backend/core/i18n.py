"""Uzbek (Latin) labels for everything the REST API shows that the models label in
Russian / Uzbek-Cyrillic. The models, their choices and the admin stay as they are —
only what the API returns to the React panel is translated here.

User-entered data (client names, addresses, categories, product names …) is never
translated.
"""

ORDER_STATUS = {
    "waiting": "Kutilmoqda",
    "created": "Yaratildi",
    "detailing": "Detalirovka",
    "working": "Xomashyo buyurtmasi",
    "assembly": "Yig'ish",
    "installing": "O'rnatish",
    "done": "Tayyor",
}

METERING_STATUS = {
    "created": "Ariza olindi",
    "dont_need": "Bekor qilindi",
    "other_day": "Boshqa kunga ko'chirildi",
    "metering_done": "O'lchovga borildi",
    "done": "Bajarildi",
    "sold_out": "Sotildi",
}

SOLUTION = {
    -1: "Sotuv amalga oshmadi",
    0: "Kerak emas",
    1: "Qayta qo'ng'iroq qilish",
    2: "Telegramda ma'lumot berildi",
    3: "Mijozdan lokatsiya olish",
    4: "Narxi qoniqtirmadi",
    5: "O'lchovga boriladi",
    6: "Sotildi",
}

INVENTORY_KIND = {1: "Kv. / pog. m", 2: "Soni"}
COUNT_NAME = {"kv": "Kv. m", "pog": "Pog. m"}

BOARD_LABEL = {"orders": "Buyurtmalar", "meterings": "O'lchovlar", "callcenter": "Call-markaz"}

# Kanban column titles by board and column key (core.kanban.Column.key).
BOARD_COLUMN = {
    "orders": {
        "waiting": "Kutilmoqda",
        "created": "Yaratildi",
        "detailing": "Detalirovka",
        "rover": "Rover",
        "painter": "Molyar",
        "working": "Xomashyo buyurtmasi",
        "assembly": "Yig'ish",
        "installing": "O'rnatish",
        "done": "Tayyor",
    },
    "meterings": {
        "created": "Ariza olindi",
        "other_day": "Boshqa kunga",
        "measured": "O'lchovga borildi",
        "design": "Dizayn",
        "price": "Narx hisoblash",
        "done": "Bajarildi",
        "sold_out": "Sotildi",
        "dont_need": "Bekor qilindi",
    },
    "callcenter": {
        "new": "Yangi",
        "re_phone": SOLUTION[1],
        "given_info": SOLUTION[2],
        "given_location": SOLUTION[3],
        "go_for_measured": SOLUTION[5],
        "sold_out": SOLUTION[6],
        "price_problem": SOLUTION[4],
        "dont_need": SOLUTION[0],
        "declined": SOLUTION[-1],
    },
}


def order_status(value) -> str:
    return ORDER_STATUS.get(str(value), str(value))


def metering_status(value) -> str:
    return METERING_STATUS.get(str(value), str(value))


def solution(value):
    return None if value is None else SOLUTION.get(int(value), str(value))


# Messages DRF / Django / simplejwt produce in Russian (LANGUAGE_CODE = "ru"),
# by ErrorDetail code. api/exceptions.py swaps a Cyrillic library message for these.
ERROR_CODE = {
    "required": "Bu maydonni to'ldirish shart.",
    "null": "Bu maydon bo'sh bo'lishi mumkin emas.",
    "blank": "Bu maydon bo'sh bo'lishi mumkin emas.",
    "invalid": "Noto'g'ri qiymat.",
    "invalid_choice": "Noto'g'ri tanlov.",
    "incorrect_type": "Noto'g'ri qiymat turi.",
    "does_not_exist": "Tanlangan yozuv topilmadi.",
    "max_length": "Qiymat juda uzun.",
    "min_length": "Qiymat juda qisqa.",
    "max_value": "Qiymat ruxsat etilganidan katta.",
    "min_value": "Qiymat ruxsat etilganidan kichik.",
    "max_digits": "Raqamlar soni juda ko'p.",
    "max_decimal_places": "Kasr qismi juda uzun.",
    "unique": "Bunday qiymat allaqachon mavjud.",
    "date": "Sana noto'g'ri.",
    "datetime": "Sana va vaqt noto'g'ri.",
    "not_a_list": "Ro'yxat kutilgan edi.",
    "empty": "Bu ro'yxat bo'sh bo'lishi mumkin emas.",
    "not_authenticated": "Tizimga kirilmagan.",
    "authentication_failed": "Avtorizatsiya xatosi — qayta kiring.",
    "token_not_valid": "Sessiya muddati tugagan — qayta kiring.",
    "user_not_found": "Foydalanuvchi topilmadi.",
    "user_inactive": "Foydalanuvchi faol emas.",
    "no_active_account": "Telefon yoki parol noto'g'ri.",
    "permission_denied": "Bu amal uchun huquq yetarli emas.",
    "not_found": "Topilmadi.",
    "method_not_allowed": "Bu amalga ruxsat yo'q.",
    "throttled": "Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring.",
    "unsupported_media_type": "Fayl formati qo'llab-quvvatlanmaydi.",
    "parse_error": "So'rov noto'g'ri tuzilgan.",
    "invalid_phone_number": "Telefon raqami noto'g'ri.",
    "unique_together": "Bunday yozuv allaqachon mavjud.",
    "invalid_image": "Rasm fayli noto'g'ri.",
    "no_name": "Fayl nomi aniqlanmadi.",
    "max_upload_size": "Fayl hajmi juda katta.",
}
DEFAULT_ERROR = "Noto'g'ri qiymat."
