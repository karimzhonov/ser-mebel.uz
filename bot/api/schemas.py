from pydantic import BaseModel


class MessageSchema(BaseModel):
    text: str
    url: str


class NotifyEnvelope(BaseModel):
    id: str
    event: str
    data: dict
