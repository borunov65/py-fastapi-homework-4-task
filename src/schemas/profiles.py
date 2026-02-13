from datetime import date

from fastapi import UploadFile, Form, File, HTTPException
from pydantic import BaseModel, field_validator, HttpUrl, ValidationError

from database.models.accounts import GenderEnum
from validation import (
    validate_name,
    validate_image,
    validate_gender,
    validate_birth_date
)


class UserProfileSchema(BaseModel):
    first_name: str
    last_name: str
    gender: str
    date_of_birth: date
    info: str
    avatar: UploadFile

    @classmethod
    def as_form(
            cls,
            first_name: str = Form(...),
            last_name: str = Form(...),
            gender: str = Form(...),
            date_of_birth: date = Form(...),
            info: str = Form(...),
            avatar: UploadFile = File(...)
    ):
        try:
            return cls(
                first_name=first_name,
                last_name=last_name,
                gender=gender,
                date_of_birth=date_of_birth,
                info=info,
                avatar=avatar
            )
        except ValidationError as e:
            cleaned_errors = [
                {
                    "loc": err["loc"],
                    "msg": err["msg"],
                    "type": err["type"],
                }
                for err in e.errors()
            ]
            raise HTTPException(status_code=422, detail=cleaned_errors)

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, value: str) -> str:
        validate_name(value)
        return value.lower()

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, value: str) -> str:
        validate_name(value)
        return value.lower()

    @field_validator("gender")
    @classmethod
    def validate_gender_field(cls, value: str) -> str:
        validate_gender(value)
        return value

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: date) -> date:
        validate_birth_date(value)
        return value

    @field_validator("info")
    @classmethod
    def validate_info(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Info field cannot be empty or contain only spaces.")
        return v.strip()

    @field_validator("avatar")
    @classmethod
    def validate_avatar(cls, value: UploadFile) -> UploadFile:

        if not value:
            raise HTTPException(status_code=400, detail="Avatar is required")

        validate_image(value)

        return value


class ProfileResponseSchema(BaseModel):
    id: int
    user_id: int
    first_name: str
    last_name: str
    gender: GenderEnum
    date_of_birth: date
    info: str
    avatar: HttpUrl

    model_config = {"from_attributes": True}
