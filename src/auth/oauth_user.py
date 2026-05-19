import json
from collections.abc import Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from src.auth.token_store import TokenStore


CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


class OAuthUserAuth:
    def __init__(
        self,
        token_store: TokenStore,
        client_secrets_path: str,
        redirect_port: int = 8765,
        scopes: Sequence[str] = (CALENDAR_READONLY_SCOPE,),
    ) -> None:
        self.token_store = token_store
        self.client_secrets_path = client_secrets_path
        self.redirect_port = redirect_port
        self.scopes = list(scopes)

    def get_credentials(self) -> Credentials:
        credentials = self._load_credentials()
        if credentials and credentials.valid:
            return credentials
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self._save_credentials(credentials)
            return credentials
        credentials = self._run_first_login()
        self._save_credentials(credentials)
        return credentials

    def _load_credentials(self) -> Credentials | None:
        if not self.token_store.exists():
            return None
        payload = self.token_store.load()
        return Credentials.from_authorized_user_info(payload, self.scopes)

    def _run_first_login(self) -> Credentials:
        flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_path, self.scopes)
        return flow.run_local_server(port=self.redirect_port, open_browser=True)

    def _save_credentials(self, credentials: Credentials) -> None:
        payload = json.loads(credentials.to_json())
        self.token_store.save(payload)
