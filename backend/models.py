from pydantic import BaseModel, Field

class Monitor(BaseModel):
    website: str = Field(min_length=1, max_length=500)
    timeout: float = Field(gt=0, le=15, default=7.0)

class OutageReport(BaseModel):
    reporter_id: str = Field(min_length=8, max_length=100)
