# 봇 클라우드 호스팅 가이드 (24시간 자동 실행)

봇을 클라우드에 올려서 내 PC를 끄더라도 24시간 돌아가게 만드는 방법입니다.

## 먼저 알아둘 것 (중요)

이 봇은 시간·벌금 기록을 `study_bot.db` 라는 파일에 계속 쌓습니다. 그런데 대부분의 무료 호스팅은 **재배포하거나 재시작하면 파일이 초기화**됩니다. 그래서 반드시 **영구 볼륨(persistent volume)** 을 붙여서 그 안(`/data`)에 DB를 저장해야 기록이 안 날아갑니다. 아래 가이드에는 이 볼륨 설정이 포함돼 있습니다. (봇 코드는 이미 `DATA_DIR=/data` 를 읽도록 준비돼 있어요.)

## 어떤 걸 고를까

| 방식 | 비용 | 난이도 | 특징 |
|---|---|---|---|
| **Fly.io** | 사실상 무료 (카드 등록 필요) | 중 | 완전 무료로 24시간 가능. 명령어(CLI) 몇 줄 필요 |
| **Railway** | $5 크레딧 후 월 2~3천원 정도 | 하 (제일 쉬움) | 웹 화면만으로 배포. CLI·Docker 몰라도 됨 |

돈을 한 푼도 안 쓰고 싶으면 **Fly.io**, 몇천 원 내더라도 제일 쉽게 하고 싶으면 **Railway** 를 추천합니다. 둘 다 아래에 정리했습니다. 팀원 여러 명이 나눠 내면 Railway 도 부담이 거의 없어요.

---

## 공통 0단계 — GitHub에 코드 올리기

두 방식 모두 코드를 GitHub에 올려두면 가장 편합니다.

1. https://github.com 가입 → 로그인.
2. 오른쪽 위 `+` → **New repository** → 이름(예: `study-time-bot`) 입력 → **Private** 선택 → **Create**.
3. 이 폴더의 파일들(`bot.py`, `requirements.txt`, `Dockerfile`, `fly.toml`, `Procfile`, `.gitignore`, `README.md`)을 업로드.
   - 쉬운 방법: 새 저장소 화면의 **uploading an existing file** 링크 클릭 → 파일들을 드래그 → **Commit**.
   - ⚠️ **`.env` 파일과 `study_bot.db` 는 절대 올리지 마세요.** (`.gitignore` 가 막아주지만 수동 업로드 시 주의)

> 봇 토큰(비밀번호)은 코드가 아니라 각 호스팅의 **환경변수(Secrets)** 에 따로 넣습니다. 코드에 직접 쓰거나 GitHub에 올리면 안 됩니다.

---

## 방법 A — Railway (가장 쉬움)

1. https://railway.com 접속 → **Login with GitHub** 로 가입.
2. **New Project** → **Deploy from GitHub repo** → 방금 만든 저장소 선택.
   - Railway가 Python 프로젝트를 자동 인식해서 `Procfile`(`worker: python bot.py`)대로 실행합니다.
3. 배포된 서비스 클릭 → 상단 **Variables** 탭 → **New Variable**:
   - `DISCORD_TOKEN` = (봇 토큰 붙여넣기)
   - `DATA_DIR` = `/data`
4. **Variables 옆 ⋯ 또는 서비스 설정에서 Volume 추가**: **+ Volume** 클릭 → Mount path 를 `/data` 로 지정 → 생성.
   - 이게 기록을 영구 저장하는 부분입니다. 꼭 하세요.
5. 오른쪽 위 **Deploy**(또는 자동 재배포). **Logs** 탭에서 `로그인됨: ...` 이 보이면 성공.
6. 디스코드에서 `!도움` 을 쳐서 반응하는지 확인.

이후 코드를 고치면 GitHub에 다시 올리기만 하면 Railway가 자동으로 재배포합니다.

---

## 방법 B — Fly.io (완전 무료)

명령어를 몇 줄 입력해야 하지만 그대로 따라 하면 됩니다. (Windows는 PowerShell, Mac은 터미널)

### 1. flyctl 설치
- **Mac**: `brew install flyctl`
- **Windows(PowerShell)**: `pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"`

### 2. 가입 & 로그인
```bash
fly auth signup     # 또는 이미 계정 있으면: fly auth login
```
(무료지만 남용 방지용 신용/체크카드 등록을 요구할 수 있습니다. 이 봇 사용량은 무료 범위 안입니다.)

### 3. 봇 파일이 있는 폴더로 이동 후 앱 생성
이 폴더(`bot.py`, `Dockerfile`, `fly.toml` 이 있는 곳)에서:
```bash
fly launch --no-deploy
```
- 앱 이름을 물어보면 원하는 이름 입력(전세계에서 유일해야 함, 예: `sogang-study-bot`).
- 지역은 **Tokyo (nrt)** 선택.
- "기존 fly.toml을 쓸까요?" 물으면 **Yes**.
- 데이터베이스/Redis 추가 여부는 **No**.

### 4. 영구 볼륨 만들기 (기록 저장용)
```bash
fly volumes create botdata --size 1 --region nrt
```
(`botdata` 라는 이름은 `fly.toml` 의 `source = "botdata"` 와 같아야 합니다.)

### 5. 봇 토큰을 비밀값으로 등록
```bash
fly secrets set DISCORD_TOKEN=여기에_봇_토큰
```

### 6. 배포
```bash
fly deploy
```
로그 확인:
```bash
fly logs
```
`로그인됨: ...` 이 보이면 성공. 디스코드에서 `!도움` 으로 확인하세요.

이후 코드를 고치면 같은 폴더에서 `fly deploy` 만 다시 실행하면 됩니다.

---

## 잘 안 될 때

- **봇이 응답 안 함** → 디스코드 개발자 포털 Bot 설정에서 인텐트 3개(PRESENCE / SERVER MEMBERS / MESSAGE CONTENT)를 켰는지, `DISCORD_TOKEN` 을 정확히 넣었는지 확인.
- **기록이 재배포 후 사라짐** → 볼륨이 `/data` 에 마운트됐는지, `DATA_DIR=/data` 환경변수가 있는지 확인.
- **정산 메시지가 안 올라옴** → `bot.py` 의 `REPORT_CHANNEL_ID` 를 정산 결과를 올릴 채널 ID로 지정하고 재배포. (봇이 그 채널에 글쓰기 권한 필요)
- **로그 보기** → Railway: Logs 탭 / Fly.io: `fly logs`

## 참고

기록 파일을 백업하고 싶으면:
- Fly.io: `fly ssh console` 로 접속해 `/data/study_bot.db` 를 내려받기.
- 학기말에 봇을 내리면 볼륨/앱을 삭제하면 됩니다.
