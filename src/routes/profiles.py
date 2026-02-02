from typing import Annotated
from urllib.request import Request

from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks, Form, File, UploadFile
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError

from schemas import (
    ProfileResponseSchema,
    ProfileCreateSchema
)
from database import (
    get_db,
    UserModel,
    UserProfileModel,
    GenderEnum
)
from config import get_s3_storage_client, get_jwt_auth_manager
from notifications import EmailSenderInterface, EmailSender
from exceptions import BaseSecurityError, S3ConnectionError, S3FileUploadError
from security.interfaces import JWTAuthManagerInterface
from config.settings import TestingSettings, Settings
from security.token_manager import JWTAuthManager
from storages import S3StorageInterface


router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/accounts/login/", auto_error=False)


async def get_current_user(
        request: Request,
        token: Annotated[str | None, Depends(oauth2_scheme)],
        db: Annotated[AsyncSession, Depends(get_db)],
        jwt_manager: Annotated[JWTAuthManagerInterface, Depends(get_jwt_auth_manager)]
) -> UserModel:
    authorization_header = request.headers.get("Authorization")
    if not authorization_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is missing"
        )

    if not authorization_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'"
        )

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'"
        )
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        payload = jwt_manager.decode_access_token(token)
        user_id: int = payload.get("user_id")
        if user_id is None:
            raise
    except BaseSecurityError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired."
        )
    except Exception:
        raise credentials_exception

    stmt = select(UserModel).where(UserModel.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or not active."
        )

    return user


@router.post(
    "/users/{user_id}/profile/",
    response_model=ProfileResponseSchema,
    status_code=status.HTTP_201_CREATED
)
async def create_user_profile(
        user_id: int,
        current_user: Annotated[UserModel, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
        s3_client: Annotated[S3StorageInterface, Depends(get_s3_storage_client)],
        first_name: str = Form(...),
        last_name: str = Form(...),
        gender: GenderEnum = Form(...),
        date_of_birth: str = Form(...),
        info: str = Form(...),
        avatar: UploadFile = File(...),
) -> ProfileResponseSchema:
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to edit this profile."
        )

    query = select(UserProfileModel).where(UserProfileModel.user_id == user_id)
    result = await db.execute(query)
    user_profile = result.scalar_one_or_none()

    if user_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already has a profile."
        )

    try:
        profile_data = ProfileCreateSchema(
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            date_of_birth=date_of_birth,
            info=info,
            avatar=avatar
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    file_data = await profile_data.avatar.read()
    file_name = f"user_{user_id}"
    file_url = await s3_client.get_file_url(file_name=file_name)
    try:
        await s3_client.upload_file(
            file_name=file_name,
            file_data=file_data
        )
    except (S3ConnectionError, S3FileUploadError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload avatar. Please try again later."
        )

    new_profile = UserProfileModel(
        **profile_data.model_dump(exclude={"avatar"}),
        user_id=user_id,
        avatar=file_url
    )
    try:
        db.add(new_profile)
        await db.commit()
        await db.refresh(new_profile)

        return new_profile

    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during user creation."
        )
