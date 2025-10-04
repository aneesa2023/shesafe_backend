from pydantic import BaseModel

class IncidentCreate(BaseModel):
    user_id: str
    text: str