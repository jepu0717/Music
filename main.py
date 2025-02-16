import discord
from discord import app_commands
from discord.ext import commands
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import youtube_dl
import asyncio
import json
import random
from async_timeout import timeout
import os

# 토큰 가져오기
TOKEN = os.getenv('DISCORD_TOKEN')

# Selenium 설정
options = webdriver.ChromeOptions()
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.binary_location = os.getenv('CHROME_BINARY_LOCATION')
driver = webdriver.Chrome(
    executable_path=os.getenv('CHROME_DRIVER_PATH'),
    options=options
)

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Music bot class
class MusicBot:
    def __init__(self):
        self.queues = {}  # 서버별 대기열
        self.now_playing = {}  # 현재 재생 중인 노래
        self.favorites = {}  # 사용자 즐겨찾기
        self.loop_mode = {}  # 반복 재생 상태
        
        # YouTube DL 설정
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
        }

    async def join_voice_channel(self, interaction):
        if interaction.user.voice:
            channel = interaction.user.voice.channel
            if not interaction.guild.voice_client:
                await channel.connect()
            else:
                await interaction.guild.voice_client.move_to(channel)
            return True
        return False

    async def search_youtube(self, query):
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        driver = webdriver.Chrome(options=options)
        
        try:
            driver.get(f"https://www.youtube.com/results?search_query={query}")
            wait = WebDriverWait(driver, 10)
            video = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ytd-video-renderer")))
            
            title = video.find_element(By.CSS_SELECTOR, "#video-title").text
            url = video.find_element(By.CSS_SELECTOR, "#video-title").get_attribute("href")
            
            return {
                'title': title,
                'url': url
            }
        finally:
            driver.quit()

    async def play_song(self, interaction, url):
        try:
            with youtube_dl.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                url2 = info['formats'][0]['url']
                source = await discord.FFmpegOpusAudio.from_probe(url2)
                interaction.guild.voice_client.play(source)
                
                self.now_playing[interaction.guild_id] = {
                    'title': info['title'],
                    'url': url,
                    'duration': info['duration']
                }
                
                # 자동 퇴장
                while interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
                    await asyncio.sleep(1)
                if not self.queues.get(interaction.guild_id):
                    await asyncio.sleep(300)  # 5분 대기
                    if interaction.guild.voice_client and not interaction.guild.voice_client.is_playing():
                        await interaction.guild.voice_client.disconnect()

        except Exception as e:
            await interaction.response.send_message(f"에러가 발생했습니다: {str(e)}", ephemeral=True)

@bot.event
async def on_ready():
    print(f"{bot.user}로 로그인했습니다")
    music_bot = MusicBot()
    bot.music_bot = music_bot
    try:
        synced = await bot.tree.sync()
        print(f"슬래시 커맨드 {len(synced)}개가 동기화되었습니다")
    except Exception as e:
        print(e)

@bot.tree.command(name="join", description="음성 채널에 봇을 참가시킵니다")
async def join(interaction: discord.Interaction):
    await interaction.response.defer()
    if await bot.music_bot.join_voice_channel(interaction):
        await interaction.followup.send("음성 채널에 참가했습니다!")
    else:
        await interaction.followup.send("먼저 음성 채널에 입장해주세요!")

@bot.tree.command(name="play", description="음악을 재생하거나 대기열에 추가합니다")
@app_commands.describe(query="노래 제목이나 URL을 입력하세요")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    
    if not interaction.guild.voice_client:
        if not await bot.music_bot.join_voice_channel(interaction):
            await interaction.followup.send("먼저 음성 채널에 입장해주세요!")
            return

    song_info = await bot.music_bot.search_youtube(query)
    
    if interaction.guild.voice_client.is_playing():
        if interaction.guild_id not in bot.music_bot.queues:
            bot.music_bot.queues[interaction.guild_id] = []
        bot.music_bot.queues[interaction.guild_id].append(song_info)
        await interaction.followup.send(f"대기열에 추가됨: {song_info['title']}")
    else:
        await interaction.followup.send(f"재생중: {song_info['title']}")
        await bot.music_bot.play_song(interaction, song_info['url'])

@bot.tree.command(name="pause", description="현재 재생중인 음악을 일시정지합니다")
async def pause(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.pause()
        await interaction.response.send_message("일시정지되었습니다")
    else:
        await interaction.response.send_message("재생 중인 음악이 없습니다", ephemeral=True)

@bot.tree.command(name="resume", description="일시정지된 음악을 다시 재생합니다")
async def resume(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
        interaction.guild.voice_client.resume()
        await interaction.response.send_message("다시 재생합니다")
    else:
        await interaction.response.send_message("일시정지된 음악이 없습니다", ephemeral=True)

@bot.tree.command(name="queue", description="현재 대기열을 보여줍니다")
async def queue(interaction: discord.Interaction):
    if interaction.guild_id not in bot.music_bot.queues or not bot.music_bot.queues[interaction.guild_id]:
        await interaction.response.send_message("대기열이 비어있습니다", ephemeral=True)
        return

    queue_list = "\n".join([f"{i+1}. {song['title']}" 
                           for i, song in enumerate(bot.music_bot.queues[interaction.guild_id])])
    await interaction.response.send_message(f"**대기열:**\n{queue_list}")

@bot.tree.command(name="favorite", description="즐겨찾기에 노래를 추가하거나 목록을 봅니다")
@app_commands.describe(song_name="추가할 노래 제목 (비워두면 목록 확인)")
async def favorite(interaction: discord.Interaction, song_name: str = None):
    user_id = str(interaction.user.id)
    
    if song_name is None:
        if user_id not in bot.music_bot.favorites or not bot.music_bot.favorites[user_id]:
            await interaction.response.send_message("즐겨찾기가 비어있습니다", ephemeral=True)
            return
        
        fav_list = "\n".join([f"{i+1}. {song}" 
                             for i, song in enumerate(bot.music_bot.favorites[user_id])])
        await interaction.response.send_message(f"**즐겨찾기:**\n{fav_list}")
    else:
        if user_id not in bot.music_bot.favorites:
            bot.music_bot.favorites[user_id] = []
        
        if song_name not in bot.music_bot.favorites[user_id]:
            bot.music_bot.favorites[user_id].append(song_name)
            await interaction.response.send_message(f"즐겨찾기에 추가됨: {song_name}")
        else:
            await interaction.response.send_message("이미 즐겨찾기에 있는 노래입니다", ephemeral=True)

@bot.tree.command(name="loop", description="현재 노래를 반복 재생합니다")
async def loop(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    bot.music_bot.loop_mode[guild_id] = not bot.music_bot.loop_mode.get(guild_id, False)
    status = "설정" if bot.music_bot.loop_mode[guild_id] else "해제"
    await interaction.response.send_message(f"반복 재생이 {status}되었습니다")

@bot.tree.command(name="shuffle", description="대기열을 랜덤으로 섞습니다")
async def shuffle(interaction: discord.Interaction):
    if interaction.guild_id in bot.music_bot.queues and bot.music_bot.queues[interaction.guild_id]:
        random.shuffle(bot.music_bot.queues[interaction.guild_id])
        await interaction.response.send_message("대기열이 섞였습니다!")
    else:
        await interaction.response.send_message("대기열이 비어있습니다", ephemeral=True)

@bot.tree.command(name="search", description="유튜브에서 노래를 검색합니다")
@app_commands.describe(query="검색할 노래 제목")
async def search(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    driver = webdriver.Chrome(options=options)
    
    try:
        driver.get(f"https://www.youtube.com/results?search_query={query}")
        wait = WebDriverWait(driver, 10)
        videos = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "ytd-video-renderer")))
        
        results = []
        search_results = "**검색 결과:**\n"
        for i, video in enumerate(videos[:5], 1):
            title = video.find_element(By.CSS_SELECTOR, "#video-title").text
            url = video.find_element(By.CSS_SELECTOR, "#video-title").get_attribute("href")
            results.append({'title': title, 'url': url})
            search_results += f"{i}. {title}\n"
        
        await interaction.followup.send(f"{search_results}\n숫자를 입력하여 선택해주세요")
        
        def check(m):
            return (m.author == interaction.user and 
                   m.channel == interaction.channel and 
                   m.content.isdigit() and 
                   1 <= int(m.content) <= len(results))
        
        try:
            msg = await bot.wait_for('message', timeout=30.0, check=check)
            selected = results[int(msg.content)-1]
            await interaction.channel.send(f"선택한 노래를 재생합니다: {selected['title']}")
            interaction.channel = msg.channel  # 채널 정보 업데이트
            await play(interaction, selected['url'])
        except asyncio.TimeoutError:
            await interaction.followup.send("시간이 초과되었습니다", ephemeral=True)
            
    finally:
        driver.quit()

@bot.tree.command(name="help", description="사용 가능한 명령어들을 보여줍니다")
async def help(interaction: discord.Interaction):
    commands_list = """
**음악 봇 명령어:**
/join - 음성 채널에 봇을 참가시킵니다
/play [노래] - 노래를 재생하거나 대기열에 추가합니다
/pause - 현재 재생중인 노래를 일시정지합니다
/resume - 일시정지된 노래를 다시 재생합니다
/queue - 현재 대기열을 보여줍니다
/favorite [노래] - 즐겨찾기에 노래를 추가하거나 목록을 봅니다
/loop - 현재 노래를 반복 재생합니다
/shuffle - 대기열을 랜덤으로 섞습니다
/search [검색어] - 유튜브에서 노래를 검색합니다
"""
    await interaction.response.send_message(commands_list)

@bot.tree.command(name="ping", description="봇의 응답 시간을 확인합니다")
async def ping(interaction: discord.Interaction):
    """봇의 지연 시간을 측정하여 응답합니다.(관리자전용)"""
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 퐁! ({latency}ms)")

# Bot token
bot.run(TOKEN)
