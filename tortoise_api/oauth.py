from datetime import timedelta, datetime
from enum import IntEnum
from typing import Annotated
from aiogram.utils.web_app import WebAppUser, safe_parse_webapp_init_data
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, SecurityScopes, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from pydantic import BaseModel, ValidationError
from starlette import status
from starlette.authentication import AuthCredentials, SimpleUser, AuthenticationError, AuthenticationBackend
from starlette.requests import HTTPConnection
from tortoise_api_model.enum import Scope, UserRole, UserStatus
from tortoise_api_model.model import Model
from tortoise_api_model.pydantic import UserReg, UserSchema
from xync_schema.models import User

from tortoise_api.loader import TOKEN, user_upsert


class AuthFailReason(IntEnum):
    username = 1
    password = 2
    signature = 3


class AuthType(IntEnum):
    pwd = 1
    tg = 2


class TokenData(BaseModel):
    id: int
    username: str | None = None
    scopes: list[str] = []


class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserSchema


class AuthUser(SimpleUser):
    id: int

    def __init__(self, uid: int, username: str) -> None:
        super().__init__(username)
        self.id = uid


class OAuth(AuthenticationBackend):
    EXPIRES = timedelta(days=7)

    def __init__(self, secret: str, db_user_model: type[User] = User, auth_type: AuthType = AuthType.pwd):
        self.secret: str = secret
        self.db_user_model: type[User] = db_user_model
        self.auth_type: AuthType = auth_type

    oauth2_scheme = OAuth2PasswordBearer(
        tokenUrl="token",
        scopes={
            Scope.Read.name: "Read own items",
            Scope.Write.name: "Write own items",
            Scope.All.name: "Access for not only own items"
        }
    )

    async def get_token_for_tg(self, tg_user: WebAppUser) -> Token:
        user: User
        user, cr = await user_upsert(tg_user)
        access_token = self.gen_access_token(
            data={"sub": tg_user.username or str(tg_user.id), "id": tg_user.id,
                  "scopes": self.role_scopes_map[user.role]},
            expires_delta=self.EXPIRES,
        )
        auth_user: UserSchema = UserSchema.model_validate(user, from_attributes=True)
        return Token.model_validate(
            {"access_token": access_token, "token_type": "bearer", "user": auth_user},
            from_attributes=True
        )

    async def authenticate(self, conn: HTTPConnection) -> tuple[AuthCredentials, SimpleUser] | None:
        if "Authorization" not in conn.headers or not (auth := conn.headers["Authorization"]):
            return

        # try:
        scheme, credentials = auth.split()
        if scheme.lower() == 'tgdata':
            tgData = safe_parse_webapp_init_data(TOKEN, credentials)
            scheme = 'bearer'
            credentials = (await self.get_token_for_tg(tgData.user)).access_token
        if scheme.lower() == 'bearer':
            try:
                payload = jwt.decode(credentials, self.secret, algorithms=["HS256"])
            except (JWTError, ValidationError) as e:
                raise AuthenticationError()
            uid: int = payload.get("id")
            username: str = payload.get("sub")
            token_scopes = payload.get("scopes", [])
            return AuthCredentials(token_scopes), AuthUser(uid, username)
        # except Exception as exc:
        #     print(exc)
        #     raise AuthenticationError('Invalid auth credentials')

    # dependency
    async def check_token(self, security_scopes: SecurityScopes, token: Annotated[str | None, Depends(oauth2_scheme)]):  # , tg_data: [str, ]
        auth_val = "Bearer"
        if security_scopes.scopes:
            auth_val += f' scope="{security_scopes.scope_str}"'
        cred_exc = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": auth_val},
        )
        try:
            payload = jwt.decode(token, self.secret, algorithms=["HS256"])
        except (JWTError, ValidationError) as e:
            cred_exc.detail += f': {e}'
            raise cred_exc
        username: str = payload.get("sub")
        uid: int = payload.get("id")
        if not username or not uid:
            cred_exc.detail += 'token'
            raise cred_exc
        token_scopes = payload.get("scopes", [])
        token_data = TokenData(id=uid, scopes=token_scopes, username=username)
        # noinspection PyTypeChecker
        user_status: UserStatus | None = await self.db_user_model.get_or_none(username=token_data.username).values_list('status', flat=True)
        if not user_status:
            cred_exc.detail = 'User not found'
            raise cred_exc
        elif user_status < UserStatus.test:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
        for scope in security_scopes.scopes:
            if scope not in token_data.scopes:
                cred_exc.detail = f"Not enough permissions. Need `{scope}`"
                raise cred_exc

    role_scopes_map = {
        UserRole.Client: [Scope.Read.name],  # read only own
        UserRole.Agent: [Scope.Read.name, Scope.Write.name],  # read/write only own
        UserRole.Manager: [Scope.Read.name, Scope.All.name],  # read all
        UserRole.Admin: [Scope.Read.name, Scope.Write.name, Scope.All.name],  # all
    }

    # api reg endpoint
    async def reg_user(self, user_reg_input: UserReg) -> Token:
        data = user_reg_input.model_dump()
        try:
            await self.db_user_model.create(**data)
        except Exception as e:
            raise HTTPException(status.HTTP_406_NOT_ACCEPTABLE, detail=e.__repr__())
        tok = await self.login_for_access_token(OAuth2PasswordRequestForm(username=user_reg_input.username, password=user_reg_input.password))
        return tok

    class AuthException(HTTPException):
        detail: AuthFailReason

        def __init__(
            self,
            detail: AuthFailReason,
        ) -> None:
            super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail.name)

    async def authenticate_user(self, username: str, password: str) -> tuple[TokenData, Model]:
        if user_db := await self.db_user_model.get_or_none(username=username):
            td = TokenData.model_validate(user_db, from_attributes=True)
            td.scopes = self.role_scopes_map[user_db.role]
            if user_db.pwd_vrf(password):
                return td, user_db
            reason = AuthFailReason.password
        else:
            reason = AuthFailReason.username
        raise self.AuthException(detail=reason)

    def gen_access_token(self, data: dict, expires_delta: timedelta = EXPIRES) -> str:
        return jwt.encode({"exp": datetime.utcnow() + expires_delta, **data}, self.secret)

    # api login endpoint
    async def login_for_access_token(self, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
        token, user_db = await self.authenticate_user(form_data.username, form_data.password)
        if isinstance(token, TokenData):
            access_token = self.gen_access_token(
                data={"id": token.id, "sub": token.username, "scopes": token.scopes},
                expires_delta=self.EXPIRES,
            )
            r = Token.model_validate({"access_token": access_token, "token_type": "bearer", "user": user_db}, from_attributes=True)
            return r
