import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
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

    # ユーザーが新しいVCに参加（入室 or 移動）
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

@tree.command(name="voicetime", description="通話時間を集計します")
@app_commands.describe(from_date="集計開始日 (例: 2025-07-01)", to_date="集計終了日 (例: 2025-07-30)")
async def voicetime(interaction: discord.Interaction, from_date: str, to_date: str):
    await interaction.response.defer()
    user_id = str(interaction.user.id)

    try:
        dt_from = datetime.strptime(from_date, "%Y-%m-%d")
        dt_to = datetime.strptime(to_date, "%Y-%m-%d")
    except ValueError:
        await interaction.followup.send("❌ 日付の形式が正しくありません。`YYYY-MM-DD` 形式で入力してください。")
        return

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
        f"📊 **{from_date} 〜 {to_date} の通話時間**\n"
        f"{h:02}時間{m:02}分{s:02}秒"
    )
    await interaction.followup.send(msg)

keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
