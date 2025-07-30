import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
import os
import json
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

vc_start_times = {}
LOG_CHANNEL_ID = int(os.environ["LOG_CHANNEL_ID"])
LOG_FILE = "vc_logs.json"

def save_log(user_id: int, join: datetime, leave: datetime):
    user_id = str(user_id)
    data = {}
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    data.setdefault(user_id, []).append({
        "join": join.strftime("%Y-%m-%d %H:%M:%S"),
        "leave": leave.strftime("%Y-%m-%d %H:%M:%S")
    })
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await tree.sync()
        print(f"🔧 Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    now = datetime.now()
    channel = bot.get_channel(LOG_CHANNEL_ID)

    if before.channel != after.channel:
        if before.channel is not None:
            start_time = vc_start_times.pop(member.id, None)
            if start_time:
                embed = discord.Embed(title="🛑 ボイスチャット退出", color=0xff5555)
                embed.add_field(name="ユーザー", value=member.display_name, inline=True)
                embed.add_field(name="チャンネル", value=before.channel.name, inline=True)
                embed.add_field(name="参加時間", value=start_time.strftime('%Y/%m/%d %H:%M:%S'), inline=False)
                embed.add_field(name="退出時間", value=now.strftime('%Y/%m/%d %H:%M:%S'), inline=False)
                duration = now - start_time
                h, m = divmod(duration.seconds // 60, 60)
                s = duration.seconds % 60
                embed.add_field(name="通話時間", value=f"{h:02}時間{m:02}分{s:02}秒", inline=False)
                await channel.send(embed=embed)
                save_log(member.id, start_time, now)

        if after.channel is not None:
            vc_start_times[member.id] = now
            embed = discord.Embed(title="🎧 ボイスチャット参加", color=0x00ffcc)
            embed.add_field(name="ユーザー", value=member.display_name, inline=True)
            embed.add_field(name="チャンネル", value=after.channel.name, inline=True)
            embed.add_field(name="参加時間", value=now.strftime('%Y/%m/%d %H:%M:%S'), inline=False)
            await channel.send(embed=embed)

@tree.command(name="voicetime", description="通話時間を集計します（他ユーザーも可）")
@app_commands.describe(
    from_date="集計開始日 (例: 2025-07-01)",
    to_date="集計終了日 (例: 2025-07-30)",
    target_user="（任意）通話時間を確認したい相手"
)
async def voicetime(
    interaction: discord.Interaction,
    from_date: str,
    to_date: str,
    target_user: discord.Member = None  # ← 任意引数を追加
):
    await interaction.response.defer()

    try:
        dt_from = datetime.strptime(from_date, "%Y-%m-%d")
        dt_to = datetime.strptime(to_date, "%Y-%m-%d")
    except ValueError:
        await interaction.followup.send("❌ 日付の形式が正しくありません。`YYYY-MM-DD` で入力してください。")
        return

    target = target_user or interaction.user
    user_id = str(target.id)

    total_seconds = 0
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            sessions = data.get(user_id, [])
            for s in sessions:
                j = datetime.strptime(s["join"], "%Y-%m-%d %H:%M:%S")
                l = datetime.strptime(s["leave"], "%Y-%m-%d %H:%M:%S")
                if dt_from <= j <= dt_to:
                    total_seconds += int((l - j).total_seconds())

    h, m = divmod(total_seconds // 60, 60)
    s = total_seconds % 60
    msg = (
        f"📊 **{target.display_name} の {from_date} 〜 {to_date} の通話時間**\n"
        f"{h:02}時間{m:02}分{s:02}秒"
    )
    await interaction.followup.send(msg)

@tree.command(name="voicetimer", description="指定期間の通話時間ランキングを表示します")
@app_commands.describe(from_date="開始日 (例: 2025-07-01)", to_date="終了日 (例: 2025-07-30)")
async def vctime_ranking(interaction: discord.Interaction, from_date: str, to_date: str):
    await interaction.response.defer()
    dt_from = datetime.strptime(from_date, "%Y-%m-%d")
    dt_to = datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)

    rankings = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for uid, sessions in data.items():
                total = 0
                for s in sessions:
                    j = datetime.strptime(s["join"], "%Y-%m-%d %H:%M:%S")
                    l = datetime.strptime(s["leave"], "%Y-%m-%d %H:%M:%S")
                    if dt_from <= j < dt_to:
                        total += int((l - j).total_seconds())
                if total > 0:
                    rankings.append((int(uid), total))

    rankings.sort(key=lambda x: x[1], reverse=True)
    lines = [f"📊 通話時間ランキング（{from_date}〜{to_date}）\n"]
    for i, (uid, secs) in enumerate(rankings, start=1):
        h, m = divmod(secs // 60, 60)
        s = secs % 60
        member = interaction.guild.get_member(uid)
        name = member.display_name if member else f"ユーザー{uid}"
        place = "🥇🥈🥉"[i - 1] if i <= 3 else f"{i}位"
        lines.append(f"{place} {name} — {h:02}時間{m:02}分{s:02}秒")

    await interaction.followup.send("\n".join(lines) if lines else "該当するログがありません。")

keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
