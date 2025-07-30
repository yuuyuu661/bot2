import discord
from discord.ext import commands
from datetime import datetime
import os
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ユーザーIDをキーに、参加時刻を記録
vc_start_times = {}

LOG_CHANNEL_ID = int(os.environ["LOG_CHANNEL_ID"])

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name}")

@bot.event
async def on_voice_state_update(member, before, after):
    now = datetime.now()

    # 参加（VCがNone → 何か）
    if before.channel is None and after.channel is not None:
        vc_start_times[member.id] = now
        embed = discord.Embed(title="🎧 ボイスチャット参加", color=0x00ffcc)
        embed.add_field(name="ユーザー", value=member.display_name, inline=True)
        embed.add_field(name="チャンネル", value=after.channel.name, inline=True)
        embed.add_field(name="参加時間", value=now.strftime('%Y/%m/%d %H:%M:%S'), inline=False)
        embed.set_footer(text=f"ID: {member.id}")
        channel = bot.get_channel(LOG_CHANNEL_ID)
        await channel.send(embed=embed)

    # 退出（何か → None）
    elif before.channel is not None and after.channel is None:
        start_time = vc_start_times.pop(member.id, None)
        end_time = now
        channel = bot.get_channel(LOG_CHANNEL_ID)

        embed = discord.Embed(title="🛑 ボイスチャット退出", color=0xff5555)
        embed.add_field(name="ユーザー", value=member.display_name, inline=True)
        embed.add_field(name="チャンネル", value=before.channel.name, inline=True)

        if start_time:
            embed.add_field(name="参加時間", value=start_time.strftime('%Y/%m/%d %H:%M:%S'), inline=False)
            embed.add_field(name="退出時間", value=end_time.strftime('%Y/%m/%d %H:%M:%S'), inline=False)
            duration = end_time - start_time
            minutes, seconds = divmod(duration.seconds, 60)
            hours, minutes = divmod(minutes, 60)
            embed.add_field(name="通話時間", value=f"{hours:02}時間{minutes:02}分{seconds:02}秒", inline=False)
        else:
            embed.add_field(name="※注意", value="参加時間が記録されていませんでした", inline=False)

        embed.set_footer(text=f"ID: {member.id}")
        await channel.send(embed=embed)

keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
