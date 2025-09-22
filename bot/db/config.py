import os

TIME_ZONE = 'Asia/Tashkent'

TORTOISE_ORM = {
    "connections": {
        "default": {
            "engine": "tortoise.backends.asyncpg",
            "credentials": {
                "database": os.getenv('POSTGRES_DB'),
                "host": os.getenv('POSTGRES_HOST'),
                "user": os.getenv('POSTGRES_USER'),
                "password": os.getenv('POSTGRES_PASSWORD'),
                "port": 5432,
            }
        }
    },
    "apps": {
        "oauth": {
            "models": ["db.models.oauth"],
            "default_connection": "default",
        }
    }
}