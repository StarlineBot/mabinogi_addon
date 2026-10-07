"""빌드 시 번들되는 비밀값(개발 땐 빈 값).

배포 exe는 넥슨 API 키·문의 웹훅을 '앱이 보관'해야 하므로, CI(릴리스 빌드)가
GitHub Secrets에서 이 파일을 채워 PyInstaller로 번들한다. 개발 체크아웃에는 빈
값으로 커밋돼 있고, config의 로더가 .env/환경변수 → config.local.json → (여기)
순서로 폴백한다. exe에 박히면 문자열 추출이 가능하다는 트레이드오프는 수용한다.
"""

NEXON_API_KEY = ""
INQUIRY_WEBHOOK_URL = ""
