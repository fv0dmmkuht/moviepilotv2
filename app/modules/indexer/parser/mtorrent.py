from typing import Optional, Tuple
from app.core.config import settings
from app.helper.mirror_key import mirror_slug, token_from_cookie
from app.log import logger
from app.modules.indexer.parser import SiteParserBase, SiteSchema
from app.utils.http import RequestUtils

class MTorrentSiteUserInfo(SiteParserBase):
    schema = SiteSchema.MTorrent
    request_mode = 'cookie'

    def _origin(self) -> str:
        candidate = self._api_url or self._base_url or self._site_url
        return str(candidate or '').rstrip('/')

    def _token(self) -> str:
        return str(self.apikey or '').strip() or token_from_cookie(self._site_cookie)

    def _legacy(self) -> bool:
        text = f"{self._site_url or ''} {self._api_url or ''}".lower()
        if any((host in text for host in ('m-team.io', 'm-team.cc', 'm-team.vip'))):
            return True
        if self._slug():
            return False
        return 'mt_session=' in str(self._site_cookie or '')

    def _slug(self) -> str:
        return mirror_slug(self._site_url)

    def _headers(self) -> dict:
        headers = {'Accept': 'application/json'}
        if self._ua:
            headers['User-Agent'] = self._ua
        token = self._token()
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return headers

    def _get(self, url: str):
        return RequestUtils(headers=self._headers(), cookies=self._site_cookie, proxies=settings.PROXY if self._proxy else None, timeout=20).get_res(url)

    def parse(self):
        origin = self._origin()
        if not origin:
            self.err_msg = '站点地址为空'
            logger.warning(f'{self._site_name} {self.err_msg}')
            return
        if self._legacy():
            self._parse_legacy(origin)
            return
        slug = self._slug()
        if not slug:
            self.err_msg = '站点标识为空'
            logger.warning(f'{self._site_name} {self.err_msg}')
            return
        if self._apply_site(origin, slug):
            self._apply_me(origin)

    def _apply_site(self, origin: str, slug: str) -> bool:
        res = self._get(f'{origin}/api/v1/sites')
        if res is None:
            self.err_msg = f'无法连接 {origin}'
            logger.warning(f'{self._site_name} 站点数据获取失败：{self.err_msg}')
            return False
        if res.status_code != 200:
            self.err_msg = self._error_text(res.status_code)
            logger.warning(f'{self._site_name} {self.err_msg}')
            return False
        try:
            payload = res.json() or {}
        except Exception as err:
            self.err_msg = '站点数据不是合法 JSON'
            logger.error(f'{self._site_name} {self.err_msg}：{err}')
            return False
        site = next((s for s in payload.get('sites') or [] if s.get('slug') == slug), None)
        if not site:
            self.err_msg = '站点未开通或已到期'
            logger.warning(f'{self._site_name} {self.err_msg}')
            return False
        display = site.get('display') or {}
        self.upload = int(display.get('uploaded_bytes') or 0)
        self.download = int(display.get('downloaded_bytes') or 0)
        self.ratio = self._ratio(display.get('ratio'))
        self.bonus = 0.0
        self.seeding = 0
        self.leeching = 0
        self.seeding_size = 0
        self.leeching_size = 0
        self.user_level = str(site.get('alias') or '')
        return True

    def _apply_me(self, origin: str) -> None:
        res = self._get(f'{origin}/api/v1/me')
        if res is None or res.status_code != 200:
            return
        try:
            me = res.json() or {}
        except Exception:
            return
        self.userid = me.get('user_id')
        self.username = me.get('display_name') or me.get('login_name')
        self.join_at = me.get('created_at')

    def _parse_legacy(self, origin: str) -> None:
        res = self._get(f'{origin}/api/local/mp/userdata')
        if res is None:
            self.err_msg = f'无法连接 {origin}'
            logger.warning(f'{self._site_name} 站点数据获取失败：{self.err_msg}')
            return
        if res.status_code != 200:
            self.err_msg = self._error_text(res.status_code)
            logger.warning(f'{self._site_name} {self.err_msg}')
            return
        try:
            payload = res.json() or {}
        except Exception as err:
            self.err_msg = '站点数据不是合法 JSON'
            logger.error(f'{self._site_name} {self.err_msg}：{err}')
            return
        data = payload.get('data') or payload
        if not data:
            self.err_msg = '站点数据为空'
            logger.warning(f'{self._site_name} {self.err_msg}')
            return
        self.userid = data.get('uid')
        self.username = data.get('username')
        self.user_level = data.get('role_label')
        self.join_at = data.get('created_at')
        self.upload = int(data.get('uploaded_bytes') or 0)
        self.download = int(data.get('downloaded_bytes') or 0)
        self.ratio = self._ratio(data.get('ratio'))
        self.bonus = 0.0
        self.seeding = int(data.get('seeding') or 0)
        self.leeching = int(data.get('leeching') or 0)
        self.seeding_size = int(data.get('seeding_size_bytes') or 0)
        self.leeching_size = int(data.get('leeching_size_bytes') or 0)
        self.message_unread = int(data.get('unread_messages') or 0) + int(data.get('unread_notices') or 0)

    @staticmethod
    def _ratio(raw) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 0.0
        if value < 0 or value == float('inf'):
            return 0.0
        return value

    @staticmethod
    def _error_text(status_code: int) -> str:
        if status_code == 401:
            return 'API 密钥无效或已撤销（401）'
        if status_code == 403:
            return '站点未授权、已到期或额度用尽（403）'
        return f'站点数据获取失败（HTTP {status_code}）'

    def _parse_logged_in(self, html_text) -> bool:
        return True

    def _parse_site_page(self, html_text: str) -> None:
        pass

    def _parse_user_base_info(self, html_text: str) -> None:
        pass

    def _parse_user_traffic_info(self, html_text: str) -> None:
        pass

    def _parse_user_detail_info(self, html_text: str) -> None:
        pass

    def _parse_user_torrent_seeding_info(self, html_text: str, multi_page: bool=False) -> Optional[str]:
        return None

    def _parse_message_unread_links(self, html_text: str, msg_links: list) -> Optional[str]:
        return None

    def _parse_message_content(self, html_text) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        return (None, None, None)
