from datetime import date

from fastapi import UploadFile
from pydantic import BaseModel, field_validator, ConfigDict

from database.models.accounts import GenderEnum
from validation import (
    validate_name,
    validate_image,
    validate_gender,
    validate_birth_date
)


class ProfileCreateSchema(BaseModel):
    first_name: str
    last_name: str
    gender: GenderEnum
    date_of_birth: date
    info: str
    avatar: UploadFile

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, value: str) -> str:
        validate_name(name=value)
        return value

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, value: str) -> str:
        validate_name(name=value)
        return value

    @field_validator("gender")
    @classmethod
    def validate_gender_field(cls, value: GenderEnum) -> GenderEnum:
        validate_gender(gender=value.value if hasattr(value, "value") else value)
        return value

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: date) -> date:
        validate_birth_date(birth_date=value)
        return value

    @field_validator("info")
    @classmethod
    def validate_info(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Info cannot be empty or consist only of spaces.")
        return value

    @field_validator("avatar")
    @classmethod
    def validate_avatar(cls, value: UploadFile) -> UploadFile:
        validate_image(avatar=value)
        return value


class ProfileResponseSchema(BaseModel):
    id: int # noqa
    user_id: int
    first_name: str
    last_name: str
    gender: GenderEnum
    date_of_birth: date
    info: str
    avatar: str

    model_config = ConfigDict(from_attributes=True)
