from fastapi import APIRouter, status, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError
from pydantic import HttpUrl, TypeAdapter

from database import get_db, UserModel, UserProfileModel
from database.models.accounts import UserGroupEnum
from schemas.profiles import ProfileResponseSchema, UserProfileSchema
from config.dependencies import get_s3_storage_client, get_jwt_auth_manager
from storages import S3StorageInterface
from security.token_manager import JWTAuthManager
from security.http import get_token
from exceptions.security import TokenExpiredError

router = APIRouter()


ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png"}


@router.post(
    "/users/{user_id}/profile/",
    response_model=ProfileResponseSchema,
    summary="User profile creation",
    description="Implement logic for token validation, authorization, "
                "database storage, and avatar loading.",
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {
            "description": "Bad Request - Profile Already Exists",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "User already has a profile."
                    }
                }
            },

        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {
                        "missing_token": {
                            "summary": "Missing Token",
                            "value": {
                                "detail": "Authorization header is missing"
                            },
                        },
                        "invalid_token_format": {
                            "summary": "Invalid Token Format",
                            "value": {
                                "detail": "Invalid Authorization header format. "
                                          "Expected 'Bearer <token>'"
                            },
                        },
                        "expired_token": {
                            "summary": "Expired Token",
                            "value": {
                                "detail": "Token has expired."
                            },
                        },
                        "not_exist_or_not_active_user": {
                            "summary": "User Not Found or Not Active",
                            "value": {
                                "detail": "User not found or not active."
                            },
                        },
                    }
                }
            },
        },
        403: {
            "description": "Forbidden - User has elevated permissions",
            "content": {
                "application/json": {
                    "example": {
                        "elevated_permissions": {
                            "summary": "Unauthorized Profile Creation",
                            "value": {
                                "detail": "You don't have permission to edit this profile."
                            },
                        },
                    }
                }
            },

        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {
                        "not_load_avatar": {
                            "summary": "Avatar Upload Failed",
                            "value": {
                                "detail": "Failed to upload avatar. Please try again later."
                            },
                        },
                    }
                }
            },

        },
    }
)
async def create_profile(
        user_id: int,
        token: str = Depends(get_token),
        user_data: UserProfileSchema = Depends(UserProfileSchema.as_form),
        db: AsyncSession = Depends(get_db),
        s3_client: S3StorageInterface = Depends(get_s3_storage_client),
        jwt_manager: JWTAuthManager = Depends(get_jwt_auth_manager),
):
    try:
        payload = jwt_manager.decode_access_token(token)
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired."
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'"
        )

    stmt = select(UserModel).where(UserModel.id == user_id)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or not active."
        )
    try:
        current_user_id = payload["user_id"]
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: 'user_id' is missing."
        )

    if user_id != current_user_id:
        stmt = select(UserModel).where(UserModel.id == current_user_id)
        result = await db.execute(stmt)
        current_user = result.scalars().first()
        if not current_user or current_user.group_id != UserGroupEnum.ADMIN.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to edit this profile."
            )

    stmt = select(UserProfileModel).where(UserProfileModel.user_id == user_id)
    result = await db.execute(stmt)
    existing_profile = result.scalars().first()

    if existing_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already has a profile."
        )

    await user_data.avatar.seek(0)
    file_bytes = await user_data.avatar.read()

    avatar_file: UploadFile = user_data.avatar

    if avatar_file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid avatar file type. Only JPEG and PNG are allowed."
        )

    extension = ALLOWED_IMAGE_TYPES[avatar_file.content_type]

    avatar_key = f"avatars/{user.id}_avatar{extension}"

    try:
        await s3_client.upload_file(file_name=avatar_key, file_data=file_bytes)

        avatar_db_value = avatar_key

        avatar_url = await s3_client.get_file_url(file_name=avatar_key)

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload avatar. Please try again later."
        )

    profile = UserProfileModel(
        user_id=user_id,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        gender=user_data.gender,
        date_of_birth=user_data.date_of_birth,
        info=user_data.info.strip(),
        avatar=avatar_db_value
    )

    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    return ProfileResponseSchema(
        id=profile.id,
        user_id=profile.user_id,
        first_name=profile.first_name or "",
        last_name=profile.last_name or "",
        gender=profile.gender,
        date_of_birth=profile.date_of_birth,
        info=profile.info or "",
        avatar = TypeAdapter(HttpUrl).validate_python(avatar_url)
    )
