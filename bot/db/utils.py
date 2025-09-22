import re
from contextlib import asynccontextmanager
from types import ModuleType
from typing import Iterable

from tortoise import Tortoise
from tortoise.contrib.fastapi import RegisterTortoise
from tortoise.exceptions import DoesNotExist, IntegrityError, ValidationError

from db.config import TIME_ZONE, TORTOISE_ORM


def tortoise_exception_handlers() -> dict:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    patterns = {
        r"Key \((?P<field>.+?)\)=\((?P<value>.+?)\) already exists\.": 'Такой {field} уже существует ({value})',
        r'null value in column "(?P<field>\w+)" violates not-null constraint': "{field} не может быть пустым",
    }

    async def does_not_exist_exception_handler(request: Request, exc: DoesNotExist):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    async def integrity_error_exception_handler(request: Request, exc: IntegrityError):
        for pattern, message in patterns.items():
            match = re.match(pattern, str(exc).split('DETAIL:  ')[-1])
            if match:
                data = match.groupdict()
                return JSONResponse(
                    status_code=422,
                    content={"detail": [{"loc": [match.group("field")],
                                         "msg": message.format(field=data.get("field"), value=data.get("value")),
                                         "type": "IntegrityError"}]},
                )
            match = re.match(pattern, str(exc).split('DETAIL:  ')[0])
            if match:
                data = match.groupdict()
                return JSONResponse(
                    status_code=422,
                    content={"detail": [{"loc": [data.get("field")],
                                         "msg": message.format(field=data.get("field"), value=data.get("value")),
                                         "type": "IntegrityError"}]},
                )
        return JSONResponse(
            status_code=422,
            content={"detail": [{"loc": [], "msg": str(exc), "type": "IntegrityError"}]},
        )

    async def validation_error_exception_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": [{"loc": [], "msg": str(exc), "type": "ValidationError"}]},
        )

    return {
        DoesNotExist: does_not_exist_exception_handler,
        IntegrityError: integrity_error_exception_handler,
        ValidationError: validation_error_exception_handler
    }



def register_tortoise(
        app,
        config=TORTOISE_ORM,
        generate_schemas=False,
        add_exception_handlers=True,
        use_tz=True, timezone=TIME_ZONE,
        config_file: str | None = None,
        db_url: str | None = None,
        modules: dict[str, Iterable[str | ModuleType]] | None = None,
        _create_db: bool = False,
) -> None:

    from fastapi.routing import _merge_lifespan_context

    # Leave this function here to compare with old versions
    # So people can upgrade tortoise-orm in running project without changing any code

    @asynccontextmanager
    async def orm_lifespan(app_instance):
        async with RegisterTortoise(
                app_instance,
                config,
                config_file,
                db_url,
                modules,
                generate_schemas,
                add_exception_handlers,
                use_tz, timezone, _create_db
        ):
            yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _merge_lifespan_context(orm_lifespan, original_lifespan)

    if add_exception_handlers:
        for exp_type, endpoint in tortoise_exception_handlers().items():
            app.exception_handler(exp_type)(endpoint)


async def init_tortoise():
    await Tortoise.init(
        config=TORTOISE_ORM,
        use_tz = True,
        timezone = TIME_ZONE,
    )