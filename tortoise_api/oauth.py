from datetime import timedelta, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import OAuth2PasswordBearer, SecurityScopes, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from pydantic import BaseModel, ValidationError
from starlette import status
from tortoise.contrib.pydantic import pydantic_model_creator
from tortoise_api_model.model import User, UserStatus, Model

# to get a string like this run: openssl rand -hex 32
SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
ALGORITHM = "HS256"
EXPIRES = timedelta(hours=1)

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None
    scopes: list[str] = []

class UserCred(BaseModel):
    username: str
    password: str
    # email: str|None = None
    # phone: int|None = None

user_model: Model.__class__ = User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="token",
    scopes={"my": "Access only myself created items", "read": "Read items", "write": "Write items"}
)


async def reg_user(new_user: UserCred):
    data = new_user.model_dump(exclude_none=True)
    try:
        user: User = await user_model.create(**data)
    except Exception as e:
        return e
    if user:
        pyd_user_model = pydantic_model_creator(user_model)
        serialized_user = await pyd_user_model.from_tortoise_orm(user)
        return serialized_user

async def authenticate_user(username: str, password: str) -> UserCred | dict:
    if user := await user_model.get_or_none(username=username):
        pyd_user = UserCred.model_validate(user, from_attributes=True)
        if user.vrf_pwd(password):
            return pyd_user
        return {'error': 'password'}
    return {'error': 'login'}


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(security_scopes: SecurityScopes, token: Annotated[str, Depends(oauth2_scheme)]) -> user_model:
    if security_scopes.scopes:
        authenticate_value = f'Bearer scope="{security_scopes.scope_str}"'
    else:
        authenticate_value = "Bearer"
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": authenticate_value},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_scopes = payload.get("scopes", [])
        token_data = TokenData(scopes=token_scopes, username=username)
    except (JWTError, ValidationError):
        raise credentials_exception
    user = await user_model.get_or_none(username=token_data.username)
    if user is None:
        raise credentials_exception
    for scope in security_scopes.scopes:
        if scope not in token_data.scopes:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not enough permissions",
                headers={"WWW-Authenticate": authenticate_value},
            )
    return user


async def get_current_active_user(current_user: Annotated[user_model, Security(get_current_user, scopes=["my"])]) -> user_model:
    if current_user.status == UserStatus.Inactive:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


my = Security(get_current_active_user, scopes=["my"])
read = Security(get_current_active_user, scopes=["read"])
write = Security(get_current_active_user, scopes=["write"])


async def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Annotated[dict, Token]:
    user: UserCred = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token = create_access_token(
        data={"sub": user.username, "scopes": form_data.scopes},
        expires_delta=EXPIRES,
    )
    return {"access_token": access_token, "token_type": "bearer"}
