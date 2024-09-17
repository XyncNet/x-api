from datetime import timedelta, datetime
from enum import IntEnum
from typing import Annotated
from aiogram.utils.web_app import WebAppUser, safe_parse_webapp_init_data
from fastapi import Depends, HTTPException, Security
from fastapi.security import OAuth2PasswordBearer, SecurityScopes, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from pydantic import BaseModel, ValidationError
from starlette import status
from starlette.authentication import AuthCredentials, SimpleUser, AuthenticationError, AuthenticationBackend
from starlette.requests import HTTPConnection
from starlette.responses import Response
from tortoise_api_model.enum import Scope, UserRole, UserStatus
from tortoise_api_model.model import Model
from tortoise_api_model.pydantic import UserReg, UserSchema
from xync_schema.models import User

from tortoise_api.loader import TOKEN, user_upsert


class AuthFailReason(IntEnum):
    username = 1
    password = 2
    signature = 3
    expired = 4


class AuthException(AuthenticationError, HTTPException):
    detail: AuthFailReason

    def __init__(
        self,
        detail: AuthFailReason,
        clear_cookie: str | None = 'access_token'
    ) -> None:
        hdrs = {'set-cookie': clear_cookie+'=; expires=Thu, 01 Jan 1970 00:00:00 GMT'} if clear_cookie else None  # path=/;
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail.name, headers=hdrs)


def on_error(_: HTTPConnection, exc: AuthException) -> Response:
    hdr = {"Location": "/login", } if exc.status_code == 303 and '/login' in (r.path for r in _.app.routes) else {}
    resp = Response(str(exc), status_code=exc.status_code, headers=hdr)
    resp.delete_cookie('access_token')
    return resp


class AuthType(IntEnum):
    pwd = 1
    tg = 2


class TokenData(BaseModel):
    id: int
    username: str | None = None
    scopes: list[str] = []


class AuthUser(SimpleUser):
    id: int

    def __init__(self, uid: int, username: str) -> None:
        super().__init__(username)
        self.id = uid


class OAuth(AuthenticationBackend):
    EXPIRES = timedelta(days=7)

    class Token(BaseModel):
        access_token: str
        token_type: str
        user: UserSchema

    def __init__(self, secret: str, db_user_model: type[User] = User, auth_type: AuthType = AuthType.pwd):
        self.secret: str = secret
        self.db_user_model: type[User] = db_user_model
        self.auth_type: AuthType = auth_type

        self.read = Security(self.check_token, scopes=[Scope.Read.name])
        self.write = Security(self.check_token, scopes=[Scope.Write.name])
        self.my = Security(self.check_token, scopes=[Scope.All.name])
        self.active = Depends(self.check_token)

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
        return self.Token.model_validate(
            {"access_token": access_token, "token_type": "bearer", "user": auth_user},
            from_attributes=True
        )

    def get_data_from_jwt(self, jwtoken: str) -> tuple[AuthCredentials, AuthUser]:
        payload = jwt.decode(jwtoken, self.secret, algorithms=["HS256"])
        uid: int = payload.get("id")
        username: str = payload.get("sub")
        scopes = payload.get("scopes", [])
        return AuthCredentials(scopes), AuthUser(uid, username)

    async def authenticate(self, conn: HTTPConnection) -> tuple[AuthCredentials, AuthUser] | None:
        if not (auth := conn.headers.get("Authorization")):
            return
        # try:
        scheme, credentials = auth.split()
        if scheme.lower() == 'tgdata':
            tgData = safe_parse_webapp_init_data(TOKEN, credentials)
            scheme = 'bearer'
            credentials = (await self.get_token_for_tg(tgData.user)).access_token
        if scheme.lower() == 'bearer':
            try:
                return self.get_data_from_jwt(credentials)
            except JWTError as e:
                print(e)
                raise AuthException(AuthFailReason.expired, 'access_token')
            except ValidationError as e:
                print(e)
                raise AuthException(AuthFailReason.signature, 'access_token')
            # except Exception as exc:
            #     raise AuthenticationError(exc, 'Invalid auth credentials')

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
            creds, user = self.get_data_from_jwt(token)
        except (JWTError, ValidationError) as e:
            cred_exc.detail += f': {e}'
            raise cred_exc
        if not user.username or not user.id:
            cred_exc.detail += 'token'
            raise cred_exc
        # noinspection PyTypeChecker
        user_status: UserStatus | None = await self.db_user_model.get_or_none(username=user.username).values_list('status', flat=True)
        if not user_status:
            cred_exc.detail = 'User not found'
            raise cred_exc
        elif user_status < UserStatus.test:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
        for scope in security_scopes.scopes:
            if scope not in creds.scopes:
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

    async def authenticate_user(self, username: str, password: str) -> tuple[TokenData, Model]:
        if user_db := await self.db_user_model.get_or_none(username=username):
            td = TokenData.model_validate(user_db, from_attributes=True)
            td.scopes = self.role_scopes_map[user_db.role]
            if user_db.pwd_vrf(password):
                return td, user_db
            reason = AuthFailReason.password
        else:
            reason = AuthFailReason.username
        raise AuthException(detail=reason)

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
            r = self.Token.model_validate({"access_token": access_token, "token_type": "bearer", "user": user_db}, from_attributes=True)
            return r
