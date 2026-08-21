# 오라클 클라우드 "Always Free" 봇 설치 가이드

완전 무료(카드 청구 없음)로 봇을 24시간 돌리는 방법입니다. 오라클 무료 서버(리눅스) 하나를 만들어 그 안에서 봇을 계속 실행합니다.

> 카드는 가입 시 신원확인용으로만 필요하고, 직접 "유료 전환(Upgrade)"을 누르지 않는 한 요금이 청구되지 않습니다.

크게 4단계예요: ① 계정 만들기 → ② 무료 서버 만들기 → ③ 서버 접속 → ④ 봇 설치·자동실행.

---

## 0단계 — 코드를 GitHub에 올리기 (권장)

서버로 코드를 가져오는 가장 쉬운 방법이라 먼저 해두면 편합니다. 이미 올렸으면 건너뛰세요.

- `.env`, `study_bot.db` 는 **올리지 않습니다** (`.gitignore`가 막아줌). 그래서 저장소는 공개(Public)로 둬도 안전합니다.
- 아직 안 올렸다면: GitHub → New repository(Public) → 이 폴더 파일들을 업로드. 저장소 주소(예: `https://github.com/내아이디/worktime-bot.git`)를 기억해 두세요.

---

## 1단계 — 오라클 클라우드 계정 만들기

1. https://www.oracle.com/kr/cloud/free/ 접속 → **무료로 시작하기 / Start for free**.
2. 이메일·국가(South Korea)·이름 입력 → 이메일 인증.
3. 휴대폰 번호 인증(SMS).
4. 신원확인용 카드 등록(청구 안 됨). 결제 방식은 "무료(Always Free)"로 둡니다.
5. 홈 지역(Home Region)은 **South Korea Central (Chuncheon)** 또는 **Japan (Tokyo)** 처럼 가까운 곳 선택. (한 번 정하면 못 바꾸니 신중히)
6. 가입 완료 후 콘솔(대시보드)에 로그인.

---

## 2단계 — 무료 서버(VM) 만들기

1. 콘솔 왼쪽 위 **☰ 메뉴 → Compute → Instances** → **Create instance**.
2. **Name**: `worktime-bot` (아무거나).
3. **Image and shape**:
   - Image: **Canonical Ubuntu** (버전 22.04 또는 24.04).
   - Shape: **Change shape** → **Ampere (ARM)** 의 `VM.Standard.A1.Flex` 선택 후 1 OCPU / 6GB 정도로. 만약 "out of capacity" 라고 나오면, **Specialty and previous generation → VM.Standard.E2.1.Micro** (x86, 항상 무료·항상 여유 있음)로 바꾸세요. 이 봇엔 Micro로도 충분합니다.
   - "Always Free eligible" 표시가 있는 옵션인지 확인하세요.
4. **SSH keys** (서버 접속 열쇠 — 중요):
   - **Generate a key pair for me** 선택 → **Save private key** 로 개인키 파일(`.key`)을 컴퓨터에 다운로드해 잘 보관. (이게 서버 들어가는 열쇠예요. 잃어버리면 못 들어감)
5. 나머지는 기본값 그대로 → **Create**. 잠시 후 상태가 **Running** 이 되고 **Public IP address**(예: `140.238.xxx.xxx`)가 표시됩니다. 이 IP를 기억하세요.

---

## 3단계 — 서버에 접속하기 (SSH)

Mac 터미널에서. (다운로드한 개인키 파일이 `~/Downloads/ssh-key.key` 라고 가정)

```bash
chmod 600 ~/Downloads/ssh-key.key
ssh -i ~/Downloads/ssh-key.key ubuntu@서버_IP주소
```

`ubuntu@...` 로 프롬프트가 바뀌면 서버 안에 들어온 거예요. (처음 접속 시 yes 입력)

> "Connection timed out" 이 나면 방화벽 문제입니다. 오라클 콘솔의 그 인스턴스 → 아래 **Virtual Cloud Network** 관련 메뉴가 아니라, 대부분 SSH(22번)는 기본 허용돼 있어요. 봇은 서버 밖에서 들어오는 포트를 안 쓰니 추가 방화벽 설정은 필요 없습니다.

---

## 4단계 — 봇 설치하고 24시간 자동 실행

서버 안에서 순서대로 입력하세요.

### (1) 필요한 것 설치
```bash
sudo apt update
sudo apt install -y python3 python3-pip git
```

### (2) 봇 코드 가져오기
GitHub에 올렸다면:
```bash
cd ~
git clone https://github.com/내아이디/worktime-bot.git
cd worktime-bot
```
(GitHub을 안 썼다면, 로컬에서 `scp -i 개인키 -r ~/worktime-bot ubuntu@서버IP:~/` 로 폴더를 통째로 올려도 됩니다.)

### (3) 파이썬 라이브러리 설치
```bash
pip3 install -r requirements.txt --break-system-packages
```

### (4) 토큰·채널 설정 (.env 파일 만들기)
```bash
nano .env
```
편집기가 열리면 아래 두 줄을 입력(값은 본인 것으로):
```
DISCORD_TOKEN=봇_토큰_붙여넣기
REPORT_CHANNEL_ID=정산올릴_채널_ID
```
저장: `Ctrl+O` → Enter → `Ctrl+X`.

### (5) 한 번 실행해서 되는지 확인
```bash
python3 bot.py
```
`로그인됨: ...` 이 뜨면 성공. 확인했으면 `Ctrl+C` 로 멈춥니다. (이 상태로 두면 터미널 닫을 때 봇도 꺼지므로, 아래에서 자동 실행으로 등록)

### (6) 24시간 자동 실행 등록 (systemd)
봇 폴더에 있는 `worktime-bot.service` 파일을 시스템에 등록합니다.
```bash
sudo cp ~/worktime-bot/worktime-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable worktime-bot
sudo systemctl start worktime-bot
```
상태 확인:
```bash
systemctl status worktime-bot
```
초록색 `active (running)` 이면 성공이에요. 이제 서버가 켜져 있는 한(항상 켜져 있음) 봇도 24시간 돌아가고, 봇이 죽어도 자동으로 다시 켜집니다. 터미널을 닫거나 컴퓨터를 꺼도 봇은 서버에서 계속 실행됩니다.

---

## 자주 쓰는 관리 명령어 (서버 안에서)

```bash
systemctl status worktime-bot        # 상태 보기
sudo systemctl restart worktime-bot  # 재시작
sudo systemctl stop worktime-bot     # 잠시 멈춤
journalctl -u worktime-bot -n 50     # 최근 로그 50줄 (Ctrl+C로 나옴)
```

## 코드를 고쳤을 때 (설정 변경 등)
```bash
cd ~/worktime-bot
git pull                              # GitHub에서 최신 코드 받기
sudo systemctl restart worktime-bot   # 재시작해서 반영
```

## 데이터 백업
기록은 서버의 `~/worktime-bot/study_bot.db` 에 저장됩니다. 내 컴퓨터로 백업하려면(내 컴퓨터 터미널에서):
```bash
scp -i ~/Downloads/ssh-key.key ubuntu@서버IP:~/worktime-bot/study_bot.db ./study_bot_backup.db
```

## 문제 해결
- **봇이 응답 안 함** → `systemctl status worktime-bot` 와 `journalctl -u worktime-bot -n 50` 로 오류 확인. 인텐트 3개(포털) 켜졌는지, `.env` 토큰이 맞는지 점검.
- **`git clone` 이 인증을 물음** → 저장소가 Private이면 그래요. Public으로 바꾸거나 scp 방식으로 올리세요.
- **서버 접속(ssh) 안 됨** → 개인키 경로/권한(`chmod 600`)과 IP를 확인.
