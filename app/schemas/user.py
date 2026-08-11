from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserCreate(BaseModel):
    login: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    repeat_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_passwords_match(self) -> "UserCreate":
        if self.password != self.repeat_password:
            raise ValueError("Passwords do not match")
        return self


class UserLogin(BaseModel):
    login: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    login: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
