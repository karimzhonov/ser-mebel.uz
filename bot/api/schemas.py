from pydantic import BaseModel


class MessageSchema(BaseModel):
    text: str
    url: str
    chat_id: str | int