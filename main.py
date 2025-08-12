import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import json
import re
from typing import Optional

from keep_alive import keep_alive

# ====== 定数・設定 ======
JST = ZoneInfo("Asia/Tokyo")
LOG_FILE = "vc_logs.json"
ADJUST_FILE = "vc_adjust.json"  # 手動調整(秒)を保存
ALLOWED_ADJUSTERS = {716667546241335328, 440893662701027328}  # 増減コマンド許可ユーザー

# ギルド（サーバー）限定：即反映用
GUILD_ID = 1398607685158440991
GUILD_OBJ = discord.Object(id=GUILD_ID)

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True  # 開発者ポータルで有効化を忘れずに
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ユーザーID(int) -> 参加開始 datetime(JST)
vc_start_times: dict[int, datetime] = {}

# 環境変数（ログ送信先チャンネル）
LOG_CHANNEL_ID: Optional[int] = None
_env_val = os.environ.get("LOG_CHANNEL_ID")
if _env_val and _env_val.isdigit():
    LOG_CHANNEL_ID = int(_env_val)

# ====== ユーティリティ ======
def now_jst() -> datetime:
    return datetime.now(tz=JST)

def load_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_logs() -> dict:
    return load_json(LOG_FILE)

def save_logs(data: dict) -> None:
    save_json(LOG_FILE, data)

def load_adjust() -> dict:
    return load_json(ADJUST_FILE)

def save_adjust(data: dict) -> None:
    save_json(ADJUST_FILE, data)

def add_adjust_seconds(user_id: int, delta_sec: int) -> int:
    """調整秒数を加算し、新しい合計(秒)を返す"""
    adj = load_adjust()
    uid = str(user_id)
    adj[uid] = int(adj.get(uid, 0)) + int(delta_sec)
    save_adjust(adj)
    return adj[uid]

def get_adjust_seconds(user_id: int) -> int:
    return int(load_adjust().get(str(user_id), 0))

def append_session(user_id: int, join_dt: datetime, leave_dt: datetime) -> None:
    """ログに1セッション追記（全てJSTで保存）"""
    data = load_logs()
    uid = str(user_id)
    data.setdefault(uid, []).append({
        "join": join_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "leave": leave_dt.strftime("%Y-%m-%d %H:%M:%S")
    })
    save_logs(data)

def fmt_hms(total_seconds: int) -> str:
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02}時間{m:02}分{s:02}秒"

def overlap_seconds(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> int:
    """[a_start, a_end] と [b_start, b_end] の重なり秒数を返す"""
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end <= start:
        return 0
    return int((end - start).total_seconds())

async def send_log_embed(channel: Optional[discord.TextChannel], embed: discord.Embed):
    if channel is None:
        return
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass

_DURATION_RE = re.compile(r"(?P<val>\d+)\s*(?P<unit>[hmsHMS])")

def parse_duration_to_seconds(text: str) -> Optional[int]:
    """
    "1h30m", "45m", "90s", "2H10M5S" のような表記を秒に変換。
    単位無しの裸数字は不可（h/m/sを付けてください）。
    """
    total = 0
    for m in _DURATION_RE.finditer(text):
        v = int(m.group("val"))
        u = m.group("unit").lower()
        if u == "h":
            total += v * 3600
        elif u == "m":
            total += v * 60
        elif u == "s":
            total += v
    return total if total > 0 else None

def is_allowed_adjuster(interaction: discord.Interaction) -> bool:
    return interaction.user.id in ALLOWED_ADJUSTERS

# ====== イベント ======
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        # ギルド限定で同期 → 即反映
        synced = await tree.sync(guild=GUILD_OBJ)
        print(f"🔧 Synced {len(synced)} guild command(s) for {GUILD_ID}")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

    # 起動時、既にVCにいるメンバーを開始セット（再起動の穴埋め）
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                vc_start_times.setdefault(member.id, now_jst())

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if before.channel == after.channel:
        return

    jst_now = now_jst()
    log_channel: Optional[discord.TextChannel] = None
    if LOG_CHANNEL_ID:
        ch = bot.get_channel(LOG_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            log_channel = ch

    # 退出 or 移動元
    if before.channel is not None:
        start_time = vc_start_times.pop(member.id, None)
        if start_time is None:
            start_time = jst_now - timedelta(seconds=1)
        leave_time = jst_now
        duration_sec = int((leave_time - start_time).total_seconds())

        embed = discord.Embed(title="🛑 ボイスチャット退出", color=0xff5555, timestamp=jst_now)
        embed.add_field(name="ユーザー", value=member.display_name, inline=True)
        embed.add_field(name="チャンネル", value=before.channel.name, inline=True)
        embed.add_field(name="参加時間", value=start_time.strftime('%Y/%m/%d %H:%M:%S JST'), inline=False)
        embed.add_field(name="退出時間", value=leave_time.strftime('%Y/%m/%d %H:%M:%S JST'), inline=False)
        embed.add_field(name="通話時間", value=fmt_hms(duration_sec), inline=False)
        await send_log_embed(log_channel, embed)

        append_session(member.id, start_time, leave_time)

    # 入室 or 移動先
    if after.channel is not None:
        vc_start_times[member.id] = jst_now
        embed = discord.Embed(title="🎧 ボイスチャット参加", color=0x00ffcc, timestamp=jst_now)
        embed.add_field(name="ユーザー", value=member.display_name, inline=True)
        embed.add_field(name="チャンネル", value=after.channel.name, inline=True)
        embed.add_field(name="参加時間", value=jst_now.strftime('%Y/%m/%d %H:%M:%S JST'), inline=False)
        await send_log_embed(log_channel, embed)

# ====== コマンド（ギルド限定） ======
@tree.command(name="voicetime", description="通話時間を集計します（他ユーザーも可）", guild=GUILD_OBJ)
@app_commands.describe(
    from_date="集計開始日 (例: 2025-07-01)",
    to_date="集計終了日 (例: 2025-07-30)",
    target_user="（任意）通話時間を確認したい相手"
)
async def voicetime(
    interaction: discord.Interaction,
    from_date: str,
    to_date: str,
    target_user: Optional[discord.Member] = None
):
    await interaction.response.defer(ephemeral=False)

    try:
        dt_from = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=JST)
        dt_to = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=JST) + timedelta(days=1)
    except ValueError:
        await interaction.followup.send("❌ 日付の形式が正しくありません。`YYYY-MM-DD` で入力してください。")
        return

    target = target_user or interaction.user
    user_id = str(target.id)

    total_seconds = 0
    data = load_logs()
    for s in data.get(user_id, []):
        j = datetime.strptime(s["join"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
        l = datetime.strptime(s["leave"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
        total_seconds += overlap_seconds(j, l, dt_from, dt_to)

    # 手動調整を加味（期間に関係なく合算で加算）
    total_seconds += get_adjust_seconds(int(user_id))

    msg = (
        f"📊 **{target.display_name} の {from_date} 〜 {to_date} の通話時間**\n"
        f"{fmt_hms(total_seconds)}"
    )
    await interaction.followup.send(msg)

@tree.command(name="voicetimer", description="指定期間の通話時間ランキングを表示（上位20名）", guild=GUILD_OBJ)
@app_commands.describe(from_date="開始日 (例: 2025-07-01)", to_date="終了日 (例: 2025-07-30)")
async def voicetimer(interaction: discord.Interaction, from_date: str, to_date: str):
    await interaction.response.defer(ephemeral=False)

    try:
        dt_from = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=JST)
        dt_to = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=JST) + timedelta(days=1)
    except ValueError:
        await interaction.followup.send("❌ 日付の形式が正しくありません。`YYYY-MM-DD` で入力してください。")
        return

    data = load_logs()
    adj = load_adjust()
    rankings: list[tuple[int, int]] = []  # (user_id, seconds)

    for uid_str, sessions in data.items():
        uid = int(uid_str)
        total = 0
        for s in sessions:
            j = datetime.strptime(s["join"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
            l = datetime.strptime(s["leave"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
            total += overlap_seconds(j, l, dt_from, dt_to)
        total += int(adj.get(uid_str, 0))  # 調整分
        if total > 0:
            rankings.append((uid, total))

    rankings.sort(key=lambda x: x[1], reverse=True)
    rankings = rankings[:20]  # 上位20名に制限

    if not rankings:
        await interaction.followup.send(f"該当するログがありません。（{from_date}〜{to_date}）")
        return

    lines = [f"📊 通話時間ランキング（{from_date}〜{to_date}）上位20名"]
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, secs) in enumerate(rankings, start=1):
        member = interaction.guild.get_member(uid)
        name = member.display_name if member else f"ユーザー{uid}"
        place = medals[i - 1] if i <= 3 else f"{i}位"
        lines.append(f"{place} {name} — {fmt_hms(secs)}")

    await interaction.followup.send("\n".join(lines))

@tree.command(name="voicetime_add", description="通話時間を手動で加算します（許可ユーザー限定）", guild=GUILD_OBJ)
@app_commands.describe(
    target_user="加算する相手",
    duration="加算量（例: 1h30m, 45m, 90s, 1h15m30s）",
    reason="任意の理由メモ"
)
async def voicetime_add(
    interaction: discord.Interaction,
    target_user: discord.Member,
    duration: str,
    reason: Optional[str] = None
):
    if not is_allowed_adjuster(interaction):
        await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
        return

    sec = parse_duration_to_seconds(duration)
    if not sec:
        await interaction.response.send_message("❌ duration は `1h30m`, `45m`, `90s` などの形式で指定してください。", ephemeral=True)
        return

    new_total = add_adjust_seconds(target_user.id, sec)
    await interaction.response.send_message(
        f"✅ {target_user.display_name} に **{fmt_hms(sec)}** を加算しました。"
        + (f"\n📝 理由: {reason}" if reason else "")
        + f"\n（累計調整: {fmt_hms(new_total)}）",
        ephemeral=False
    )

@tree.command(name="voicetime_sub", description="通話時間を手動で減算します（許可ユーザー限定）", guild=GUILD_OBJ)
@app_commands.describe(
    target_user="減算する相手",
    duration="減算量（例: 30m, 120s, 1h15m）",
    reason="任意の理由メモ"
)
async def voicetime_sub(
    interaction: discord.Interaction,
    target_user: discord.Member,
    duration: str,
    reason: Optional[str] = None
):
    if not is_allowed_adjuster(interaction):
        await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
        return

    sec = parse_duration_to_seconds(duration)
    if not sec:
        await interaction.response.send_message("❌ duration は `30m`, `120s` などの形式で指定してください。", ephemeral=True)
        return

    new_total = add_adjust_seconds(target_user.id, -sec)
    await interaction.response.send_message(
        f"✅ {target_user.display_name} から **{fmt_hms(sec)}** を減算しました。"
        + (f"\n📝 理由: {reason}" if reason else "")
        + f"\n（累計調整: {fmt_hms(new_total)}）",
        ephemeral=False
    )

# ====== 起動 ======
keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
