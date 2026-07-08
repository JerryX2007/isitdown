from pydantic import BaseModel, Field

class Monitor(BaseModel):
    website: str = Field(min_length=1)
    name: str | None = None
    timeout: float = Field(gt=0, default=3.0)

class TempCheck(BaseModel):
    website: str = Field(min_length=1)
    timeout: float = Field(gt=0, default=3.0)
