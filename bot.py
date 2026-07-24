"""
디스코드 음성채널 공부시간 추적 봇
--------------------------------
- 등록된 팀원이 음성 채널에 머무는 시간을 하루 단위로 집계
- 하루 목표(기본 6시간)를 채웠는지 매일 오전 6시에 정산
- 목표 미달 시 부족한 시간만큼 벌금을 누적 계산 (사유를 미리 적으면 면제)
- 데이터는 SQLite 파일(study_bot.db)에 저장

하루의 기준: 오전 6시 ~ 다음날 오전 6시 (새벽 늦게까지 한 시간도 그날에 포함)
설정 값은 아래 CONFIG 부분에서 바꿀 수 있습니다.
"""

import os
import sqlite3
import math
import datetime as dt
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────
# CONFIG (필요하면 여기 값만 바꾸면 됩니다)
# ─────────────────────────────────────────────────────────────
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")                 # .env 파일에 봇 토큰 입력
TZ = ZoneInfo("Asia/Seoul")                        # 시간대 (한국)

TARGET_HOURS = 6.0                                 # 하루 목표 시간
DAY_START_HOUR = 6                                 # 하루 기준 시각(정산 시각), 오전 6시
FINE_PER_HOUR = 1000                               # 부족한 1시간당 벌금(원)

# 정산 결과를 올릴 텍스트 채널 ID (0 이면 첫 번째로 찾은 텍스트 채널 사용)
REPORT_CHANNEL_ID = 0

# 시간을 인정할 음성 채널 ID 목록. 비워두면 AFK 채널을 뺀 모든 음성 채널 인정
TRACKED_CHANNEL_IDS: set[int] = set()              # 예: {123456789012345678}

# True 로 두면 '헤드셋 종료(귀 막음)' 상태일 땐 시간을 인정하지 않음
IGNORE_WHEN_DEAFENED = False

# 저장 위치: 클라우드에서는 DATA_DIR 환경변수로 '영구 볼륨' 경로(예: /data)를 지정.
# 로컬에서는 지정 안 하면 이 파일과 같은 폴더에 저장됩니다.
DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "study_bot.db")
COMMAND_PREFIX = "!"

# ─────────────────────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────────────────────
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS members (
                user_id INTEGER PRIMARY KEY,
                name    TEXT
            );
            CREATE TABLE IF NOT EXISTS daily (
                user_id INTEGER,
                date    TEXT,      -- 기준일 YYYY-MM-DD
                seconds REAL DEFAULT 0,
                PRIMARY KEY (user_id, date)
            );
            CREATE TABLE IF NOT EXISTS excuses (
                user_id INTEGER,
                date    TEXT,
                reason  TEXT,
                PRIMARY KEY (user_id, date)
            );
            CREATE TABLE IF NOT EXISTS settlements (
                user_id INTEGER,
                date    TEXT,
                seconds REAL,
                met     INTEGER,   -- 목표 달성 1 / 미달 0
                excused INTEGER,   -- 사유 인정 1 / 아님 0
                fine    INTEGER,   -- 그날 부과된 벌금(원)
                PRIMARY KEY (user_id, date)
            );
            CREATE TABLE IF NOT EXISTS todos (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date    TEXT,
                content TEXT,
                done    INTEGER DEFAULT 0
            );
            """
        )


# ─────────────────────────────────────────────────────────────
# 시간 헬퍼
# ─────────────────────────────────────────────────────────────
def now_kst() -> dt.datetime:
    return dt.datetime.now(TZ)


def study_date(when: dt.datetime | None = None) -> str:
    """오전 6시 기준의 '기준일'을 YYYY-MM-DD 로 반환."""
    when = when or now_kst()
    if when.hour < DAY_START_HOUR:
        when = when - dt.timedelta(days=1)
    return when.strftime("%Y-%m-%d")


def fmt_hm(seconds: float) -> str:
    seconds = int(seconds)
    h, m = seconds // 3600, (seconds % 3600) // 60
    return f"{h}시간 {m}분"


def todo_progress(user_id: int, date: str) -> tuple[int, int]:
    """(완료 개수, 전체 개수) 반환."""
    with db() as conn:
        r = conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(done),0) AS done "
            "FROM todos WHERE user_id=? AND date=?",
            (user_id, date),
        ).fetchone()
    return int(r["done"]), int(r["total"])


# ─────────────────────────────────────────────────────────────
# 봇
# ─────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)

_last_tick: dt.datetime | None = None


def is_counted(member: discord.Member) -> bool:
    """이 멤버의 현재 상태를 시간으로 인정할지 판단."""
    if member.bot:
        return False
    vs = member.voice
    if vs is None or vs.channel is None:
        return False
    ch = vs.channel
    guild = member.guild
    if guild.afk_channel and ch.id == guild.afk_channel.id:
        return False
    if TRACKED_CHANNEL_IDS and ch.id not in TRACKED_CHANNEL_IDS:
        return False
    if IGNORE_WHEN_DEAFENED and (vs.self_deaf or vs.deaf):
        return False
    return True


def add_seconds(user_id: int, seconds: float, date: str):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO daily (user_id, date, seconds) VALUES (?, ?, ?)
            ON CONFLICT(user_id, date) DO UPDATE SET seconds = seconds + excluded.seconds
            """,
            (user_id, date, seconds),
        )


@tasks.loop(seconds=60)
async def tick():
    """1분마다 음성 채널에 있는 인원의 시간을 실제 경과 초만큼 적립."""
    global _last_tick
    now = now_kst()
    if _last_tick is None:
        _last_tick = now
        return
    elapsed = (now - _last_tick).total_seconds()
    _last_tick = now
    # 비정상적으로 크면(재시작·절전 등) 최대 90초까지만 인정
    if elapsed <= 0 or elapsed > 90:
        elapsed = 60
    date = study_date(now)
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if is_counted(member):
                    add_seconds(member.id, elapsed, date)


@tick.before_loop
async def before_tick():
    await bot.wait_until_ready()


@tasks.loop(time=dt.time(hour=DAY_START_HOUR, minute=0, tzinfo=TZ))
async def daily_settle():
    """매일 오전 6시: 방금 끝난 하루를 정산."""
    ended = study_date(now_kst() - dt.timedelta(minutes=5))
    await run_settlement(ended)


@daily_settle.before_loop
async def before_settle():
    await bot.wait_until_ready()


async def run_settlement(date: str) -> discord.Embed:
    """지정한 기준일을 정산하고 결과 임베드를 반환·게시."""
    target_sec = TARGET_HOURS * 3600
    rows = []
    with db() as conn:
        members = conn.execute("SELECT user_id, name FROM members").fetchall()
        for m in members:
            uid = m["user_id"]
            d = conn.execute(
                "SELECT seconds FROM daily WHERE user_id=? AND date=?", (uid, date)
            ).fetchone()
            sec = d["seconds"] if d else 0.0
            ex = conn.execute(
                "SELECT reason FROM excuses WHERE user_id=? AND date=?", (uid, date)
            ).fetchone()
            excused = ex is not None
            met = sec >= target_sec
            if met or excused:
                fine = 0
            else:
                short_hours = (target_sec - sec) / 3600
                fine = int(math.ceil(short_hours * FINE_PER_HOUR))
            conn.execute(
                """
                INSERT INTO settlements (user_id, date, seconds, met, excused, fine)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, date) DO UPDATE SET
                    seconds=excluded.seconds, met=excluded.met,
                    excused=excluded.excused, fine=excluded.fine
                """,
                (uid, date, sec, int(met), int(excused), fine),
            )
            rows.append((m["name"], sec, met, excused, fine,
                         ex["reason"] if ex else None))

    rows.sort(key=lambda r: r[1], reverse=True)
    embed = discord.Embed(
        title=f"📊 {date} 공부시간 정산 (목표 {TARGET_HOURS:g}시간)",
        color=0x5865F2,
    )
    if not rows:
        embed.description = "등록된 팀원이 없습니다. `!가입` 으로 등록하세요."
    else:
        lines = []
        total_fine = 0
        for name, sec, met, excused, fine, reason in rows:
            if met:
                mark = "✅"
            elif excused:
                mark = "📝"
            else:
                mark = "❌"
            line = f"{mark} **{name}** — {fmt_hm(sec)}"
            if excused and not met:
                line += f" (사유: {reason})"
            elif fine > 0:
                line += f" → 벌금 +{fine:,}원"
                total_fine += fine
            lines.append(line)
        embed.description = "\n".join(lines)
        if total_fine:
            embed.set_footer(text=f"오늘 발생한 벌금 합계: {total_fine:,}원")

    channel = None
    if REPORT_CHANNEL_ID:
        channel = bot.get_channel(REPORT_CHANNEL_ID)
    if channel is None:
        for g in bot.guilds:
            for c in g.text_channels:
                if c.permissions_for(g.me).send_messages:
                    channel = c
                    break
            if channel:
                break
    if channel:
        await channel.send(embed=embed)
    return embed


# ─────────────────────────────────────────────────────────────
# 명령어
# ─────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    init_db()
    if not tick.is_running():
        tick.start()
    if not daily_settle.is_running():
        daily_settle.start()
    print(f"로그인됨: {bot.user} | 기준일 {study_date()}")


@bot.command(name="가입", aliases=["등록"])
async def register(ctx):
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO members (user_id, name) VALUES (?, ?)",
            (ctx.author.id, ctx.author.display_name),
        )
    await ctx.send(f"✅ {ctx.author.display_name} 님, 추적 대상으로 등록됐어요.")


@bot.command(name="탈퇴")
async def unregister(ctx):
    with db() as conn:
        conn.execute("DELETE FROM members WHERE user_id=?", (ctx.author.id,))
    await ctx.send(f"👋 {ctx.author.display_name} 님을 추적 대상에서 제외했어요.")


@bot.command(name="내시간", aliases=["시간"])
async def my_time(ctx):
    date = study_date()
    with db() as conn:
        d = conn.execute(
            "SELECT seconds FROM daily WHERE user_id=? AND date=?",
            (ctx.author.id, date),
        ).fetchone()
    sec = d["seconds"] if d else 0.0
    remain = max(0, TARGET_HOURS * 3600 - sec)
    msg = f"⏱️ 오늘({date}) **{fmt_hm(sec)}** 했어요."
    if remain > 0:
        msg += f" 목표까지 {fmt_hm(remain)} 남음."
    else:
        msg += " 목표 달성! 🎉"
    await ctx.send(msg)


@bot.command(name="현황", aliases=["순위"])
async def today_board(ctx):
    date = study_date()
    target_sec = TARGET_HOURS * 3600
    with db() as conn:
        members = conn.execute("SELECT user_id, name FROM members").fetchall()
        rows = []
        for m in members:
            d = conn.execute(
                "SELECT seconds FROM daily WHERE user_id=? AND date=?",
                (m["user_id"], date),
            ).fetchone()
            sec = d["seconds"] if d else 0.0
            ex = conn.execute(
                "SELECT 1 FROM excuses WHERE user_id=? AND date=?",
                (m["user_id"], date),
            ).fetchone()
            done, total = todo_progress(m["user_id"], date)
            rows.append((m["name"], sec, ex is not None, done, total))
    if not rows:
        await ctx.send("등록된 팀원이 없어요. `!가입` 으로 등록하세요.")
        return
    rows.sort(key=lambda r: r[1], reverse=True)
    lines = []
    for name, sec, excused, done, total in rows:
        mark = "✅" if sec >= target_sec else ("📝" if excused else "❌")
        line = f"{mark} **{name}** — {fmt_hm(sec)}"
        if total:
            line += f"  · 할일 {done}/{total}"
        lines.append(line)
    embed = discord.Embed(
        title=f"📋 오늘({date}) 현황 · 목표 {TARGET_HOURS:g}시간",
        description="\n".join(lines),
        color=0x57F287,
    )
    await ctx.send(embed=embed)


@bot.command(name="사유")
async def excuse(ctx, *, text: str = ""):
    """오늘 사유 등록:  !사유 병원 예약
    특정 날짜:        !사유 2026-07-25 가족 행사"""
    if not text.strip():
        await ctx.send("사유 내용을 적어주세요. 예) `!사유 병원 예약`")
        return
    parts = text.split(maxsplit=1)
    date = study_date()
    reason = text
    if len(parts) == 2:
        try:
            dt.datetime.strptime(parts[0], "%Y-%m-%d")
            date, reason = parts[0], parts[1]
        except ValueError:
            pass
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO excuses (user_id, date, reason) VALUES (?, ?, ?)",
            (ctx.author.id, date, reason),
        )
    await ctx.send(f"📝 {date} 사유가 등록됐어요: “{reason}” (그날 벌금 면제)")


@bot.command(name="할일", aliases=["투두", "todo"])
async def todo(ctx, *, content: str = ""):
    """할일 추가:  !할일 알고리즘 3문제
    목록 보기:   !할일"""
    date = study_date()
    if not content.strip():
        # 목록 표시
        with db() as conn:
            rows = conn.execute(
                "SELECT id, content, done FROM todos WHERE user_id=? AND date=? ORDER BY id",
                (ctx.author.id, date),
            ).fetchall()
        if not rows:
            await ctx.send("오늘 등록한 할일이 없어요. `!할일 내용` 으로 추가하세요.")
            return
        lines = []
        for i, r in enumerate(rows, 1):
            box = "☑️" if r["done"] else "⬜"
            lines.append(f"{box} `{i}` {r['content']}")
        done, total = todo_progress(ctx.author.id, date)
        embed = discord.Embed(
            title=f"📝 {ctx.author.display_name} 오늘 할일 ({done}/{total})",
            description="\n".join(lines),
            color=0x5865F2,
        )
        await ctx.send(embed=embed)
        return
    with db() as conn:
        conn.execute(
            "INSERT INTO todos (user_id, date, content, done) VALUES (?, ?, ?, 0)",
            (ctx.author.id, date, content.strip()),
        )
    done, total = todo_progress(ctx.author.id, date)
    await ctx.send(f"➕ 할일 추가: “{content.strip()}”  (오늘 {done}/{total})")


def _nth_todo_id(user_id: int, date: str, n: int):
    with db() as conn:
        rows = conn.execute(
            "SELECT id FROM todos WHERE user_id=? AND date=? ORDER BY id",
            (user_id, date),
        ).fetchall()
    if 1 <= n <= len(rows):
        return rows[n - 1]["id"]
    return None


@bot.command(name="완료", aliases=["체크"])
async def todo_done(ctx, number: int = None):
    """할일 완료 체크:  !완료 2"""
    if number is None:
        await ctx.send("완료할 항목 번호를 적어주세요. 예) `!완료 2`  (번호는 `!할일` 로 확인)")
        return
    date = study_date()
    tid = _nth_todo_id(ctx.author.id, date, number)
    if tid is None:
        await ctx.send("그 번호의 할일이 없어요. `!할일` 로 번호를 확인하세요.")
        return
    with db() as conn:
        conn.execute("UPDATE todos SET done=1 WHERE id=?", (tid,))
    done, total = todo_progress(ctx.author.id, date)
    await ctx.send(f"✅ 완료! (오늘 {done}/{total})")


@bot.command(name="할일삭제", aliases=["투두삭제"])
async def todo_delete(ctx, number: int = None):
    """할일 삭제:  !할일삭제 2"""
    if number is None:
        await ctx.send("삭제할 항목 번호를 적어주세요. 예) `!할일삭제 2`")
        return
    date = study_date()
    tid = _nth_todo_id(ctx.author.id, date, number)
    if tid is None:
        await ctx.send("그 번호의 할일이 없어요.")
        return
    with db() as conn:
        conn.execute("DELETE FROM todos WHERE id=?", (tid,))
    await ctx.send("🗑️ 삭제했어요.")


@bot.command(name="벌금")
async def my_fine(ctx):
    with db() as conn:
        r = conn.execute(
            "SELECT COALESCE(SUM(fine),0) AS total FROM settlements WHERE user_id=?",
            (ctx.author.id,),
        ).fetchone()
    await ctx.send(f"💸 {ctx.author.display_name} 님 누적 벌금: **{r['total']:,}원**")


@bot.command(name="벌금전체", aliases=["벌금현황"])
async def all_fines(ctx):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT m.name AS name, COALESCE(SUM(s.fine),0) AS total
            FROM members m
            LEFT JOIN settlements s ON s.user_id = m.user_id
            GROUP BY m.user_id ORDER BY total DESC
            """
        ).fetchall()
    if not rows:
        await ctx.send("등록된 팀원이 없어요.")
        return
    lines = [f"**{r['name']}** — {r['total']:,}원" for r in rows]
    total = sum(r["total"] for r in rows)
    embed = discord.Embed(
        title="💸 누적 벌금 현황",
        description="\n".join(lines),
        color=0xED4245,
    )
    embed.set_footer(text=f"전체 합계: {total:,}원")
    await ctx.send(embed=embed)


@bot.command(name="주간")
async def weekly(ctx):
    today = now_kst()
    dates = [study_date(today - dt.timedelta(days=i)) for i in range(7)]
    with db() as conn:
        d = conn.execute(
            f"SELECT date, seconds FROM daily WHERE user_id=? AND date IN ({','.join('?'*7)})",
            (ctx.author.id, *dates),
        ).fetchall()
    m = {r["date"]: r["seconds"] for r in d}
    lines = [f"{dd} — {fmt_hm(m.get(dd, 0))}" for dd in dates]
    total = sum(m.get(dd, 0) for dd in dates)
    embed = discord.Embed(
        title=f"🗓️ {ctx.author.display_name} 최근 7일",
        description="\n".join(lines),
        color=0xFEE75C,
    )
    embed.set_footer(text=f"합계 {fmt_hm(total)}")
    await ctx.send(embed=embed)


@bot.command(name="정산")
@commands.has_permissions(administrator=True)
async def manual_settle(ctx, date: str = None):
    """관리자용 수동 정산:  !정산  또는  !정산 2026-07-23"""
    if date is None:
        date = study_date(now_kst() - dt.timedelta(minutes=5))
    embed = await run_settlement(date)
    await ctx.send("수동 정산 완료.", embed=embed)


@bot.command(name="도움", aliases=["명령어", "help"])
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🤖 공부시간 봇 명령어",
        color=0x5865F2,
        description=(
            f"목표: 하루 **{TARGET_HOURS:g}시간** (오전 {DAY_START_HOUR}시 기준 정산)\n"
            f"미달 시 부족한 1시간당 **{FINE_PER_HOUR:,}원** 벌금 (사유 등록 시 면제)\n\n"
            "`!가입` 추적 대상으로 등록 (처음에 꼭 하기)\n"
            "`!탈퇴` 추적 대상에서 제외\n"
            "`!내시간` 오늘 내 누적 시간\n"
            "`!현황` 오늘 팀 전체 현황\n"
            "`!주간` 최근 7일 내 기록\n"
            "`!할일 내용` 오늘 할일 추가 (내용 없이 `!할일` 은 목록)\n"
            "`!완료 번호` 할일 완료 체크\n"
            "`!할일삭제 번호` 할일 삭제\n"
            "`!사유 내용` 오늘 벌금 면제 사유 등록\n"
            "`!벌금` 내 누적 벌금\n"
            "`!벌금전체` 전체 누적 벌금\n"
            "`!정산 [날짜]` (관리자) 수동 정산"
        ),
    )
    await ctx.send(embed=embed)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN 이 없습니다. .env 파일을 확인하세요.")
    init_db()
    bot.run(TOKEN)
