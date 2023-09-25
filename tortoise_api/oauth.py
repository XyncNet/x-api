from datetime import timedelta, datetime
from enum import IntEnum
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import OAuth2PasswordBearer, SecurityScopes, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from pydantic import BaseModel, ValidationError
from starlette import status
from tortoise.contrib.pydantic import pydantic_model_creator, PydanticModel
from tortoise_api_model.model import User, UserStatus, Model

# to get a string like this run: openssl rand -hex 32
SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
ALGORITHM = "HS256"
EXPIRES = timedelta(hours=1)

class AuthFailReason(IntEnum):
    username: 1
    password: 2

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None
    scopes: list[str] = []

class UserCred(BaseModel):
    username: str
    password: str

class NewUser(UserCred):
    email: str|None = None
    phone: int|None = None

user_model: Model.__class__ = User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="token",
    scopes={"my": "Access only myself created items", "read": "Read items", "write": "Write items"}
)

# api reg endpoint
async def reg_user(new_user: UserCred) -> PydanticModel:
    data = new_user.model_dump(exclude_none=True)
    try:
        user: User = await user_model.create(**data)
    except Exception as e:
        raise HTTPException(status.HTTP_406_NOT_ACCEPTABLE, detail=e.__repr__())
    if user:
        pyd_user_model = pydantic_model_creator(user_model)
        serialized_user = await pyd_user_model.from_tortoise_orm(user)
        return serialized_user

# api login endpoint
async def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Annotated[dict, Token]:
    user: UserCred = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token = gen_access_token(
        data={"sub": user.username, "scopes": form_data.scopes},
        expires_delta=EXPIRES,
    )
    return {"access_token": access_token, "token_type": "bearer"}


async def authenticate_user(username: str, password: str) -> UserCred|AuthFailReason:
    if user := await user_model.get_or_none(username=username):
        pyd_user = UserCred.model_validate(user, from_attributes=True)
        if user.vrf_pwd(password):
            return pyd_user
        return AuthFailReason.password
    return AuthFailReason.username


def gen_access_token(data: dict, expires_delta: timedelta = EXPIRES) -> str:
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + expires_delta})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# dependency
async def get_current_user(security_scopes: SecurityScopes, token: Annotated[str, Depends(oauth2_scheme)]) -> user_model:
    auth_val = "Bearer"
    if security_scopes.scopes:
        auth_val += f' scope="{security_scopes.scope_str}"'
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": auth_val},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise cred_exc
        token_scopes = payload.get("scopes", [])
        token_data = TokenData(scopes=token_scopes, username=username)
    except (JWTError, ValidationError) as e:
        raise cred_exc
    user = await user_model.get_or_none(username=token_data.username)
    if not user:
        cred_exc.detail = 'User not found'
        raise cred_exc
    for scope in security_scopes.scopes:
        if scope not in token_data.scopes:
            cred_exc.detail = f'Not enough permissions. Need "{scope}"'
            raise cred_exc
    return user

# dependency
async def get_current_active_user(current_user: Annotated[user_model, Security(get_current_user, scopes=["my"])]) -> user_model:
    if current_user.status == UserStatus.Inactive:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return current_user


my = Security(get_current_active_user, scopes=["my"])
read = Security(get_current_active_user, scopes=["read"])
write = Security(get_current_active_user, scopes=["write"])
