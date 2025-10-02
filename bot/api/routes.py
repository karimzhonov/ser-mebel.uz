from fastapi import APIRouter, Request, HTTPException
from bot.webhook import feed_update
from bot import send_message
from .schemas import MessageSchema

router = APIRouter()

@router.post("/webhook")
async def webhook(request: Request) -> None:
    print("Received webhook request")
    update = await request.json()  # Получаем данные из запроса
    # Обрабатываем обновление через диспетчер (dp) и передаем в бот
    await feed_update(update)
    print("Update processed")


@router.post("/user/{chat_id}/message")
async def message(chat_id: str, data: MessageSchema):
    try:
        return await send_message(chat_id=chat_id, **data.model_dump())
    except ConnectionError as e:
        raise HTTPException(400, {'status': 'error', 'message': str(e)})
