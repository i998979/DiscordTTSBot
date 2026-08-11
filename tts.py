import asyncio
import os
import re
import time

import aiohttp
import discord
import yt_dlp
from discord import app_commands
from dotenv import load_dotenv
from gtts import gTTS, gTTSError
from gtts.lang import tts_langs

load_dotenv()
TOKEN = os.getenv('TOKEN')
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

audio_queue = asyncio.Queue()
is_playing = False

URL_REGEX = r'https?://[^\s]+'


@client.event
async def on_ready():
    await tree.sync()
    await tree.sync(guild=discord.Object(id=os.getenv('GUILD')))
    print(f'Logged in as {client.user}')


@tree.command(name="speak", description="Bot joins VC and speaks the given text in the specified language.")
async def speak(interaction: discord.Interaction, text: str, lang: str = 'yue', accent: str = 'com',
                play_tone: bool = False):
    await interaction.response.defer()
    await interaction.edit_original_response(content="🎧 " + text)

    if interaction.user.voice is None or interaction.user.voice.channel is None:
        await interaction.edit_original_response(content="You need to be in a voice channel!")
        return

    timestamp = str(int(time.time() * 1000))
    audio_path = f"{timestamp}.mp3"

    try:
        await asyncio.to_thread(lambda: gTTS(text, lang=lang, tld=accent).save(audio_path))

        if play_tone:
            await enqueue_audio(interaction, "tritone.mp3", is_temp=False)

        await enqueue_audio(interaction, audio_path)
    except ValueError:
        await interaction.edit_original_response(content="Language not supported. " + str(tts_langs()))
    except gTTSError:
        await interaction.edit_original_response(
            content="Accent not supported. https://gtts.readthedocs.io/en/latest/module.html#localized-accents")


async def generate_tts(text, voice_id):
    url = "https://api.fakeyou.com/tts/inference"
    headers = {"Content-Type": "application/json"}
    payload = {
        "uuid_idempotency_token": str(time.time()),
        "tts_model_token": voice_id,
        "inference_text": text
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                print("FakeYou API Response:", response.status, await response.text())
                if response.status != 200:
                    return None
                result = await response.json()
                if not result.get("success"):
                    return None
                return result.get("inference_job_token")
    except Exception as e:
        print(f"Error in generate_tts: {e}")
        return None


async def wait_for_tts(job_token):
    url = f"https://api.fakeyou.com/tts/job/{job_token}"

    async with aiohttp.ClientSession() as session:
        for _ in range(10):
            await asyncio.sleep(2)
            try:
                async with session.get(url) as status_response:
                    status_data = await status_response.json()
                    print("Job Status:", status_data)
                    if status_data.get("state", {}).get("status") == "complete_success":
                        return "https://cdn-2.fakeyou.com" + status_data["state"]["maybe_public_bucket_wav_audio_path"]
            except Exception as e:
                print(f"Error polling TTS status: {e}")

    return None


@tree.command(name="celebrity_tts", description="Generate TTS using a celebrity's voice.")
async def celebrity_tts(interaction: discord.Interaction, celebrity: str, text: str):
    await interaction.response.defer()
    await interaction.edit_original_response(content=f"🔄 {text}")

    if interaction.user.voice is None or interaction.user.voice.channel is None:
        return await interaction.edit_original_response(content="You need to be in a voice channel!")

    voice_id = celebrity
    job_token = await generate_tts(text, voice_id)

    if not job_token:
        return await interaction.edit_original_response(
            content="❌ Failed to generate celebrity TTS. Most likely celebrity was not found.\n\n"
                    "Refer https://api.fakeyou.com/tts/list and insert the corresponding \"model_token\",\n"
                    "or visit https://fakeyou.com/explore/weights?page_size=24&weight_type=tt2, "
                    "select a voice, and copy the token from the URL.")

    audio_url = await wait_for_tts(job_token)

    if not audio_url:
        return await interaction.edit_original_response(content="❌ TTS generation failed or timed out.")

    timestamp = str(int(time.time() * 1000))
    audio_path = f"{timestamp}.mp3"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(audio_url) as resp:
                if resp.status == 200:
                    audio_data = await resp.read()
                    await asyncio.to_thread(lambda: open(audio_path, "wb").write(audio_data))
                else:
                    return await interaction.edit_original_response(content="❌ Failed to download audio from provider.")
    except Exception as e:
        return await interaction.edit_original_response(content=f"❌ Failed to download audio: {e}")

    await enqueue_audio(interaction, audio_path, is_temp=True)


dict_language = {
    "中文": "all_zh",
    "粤语": "all_yue",
    "英文": "en",
    "日文": "all_ja",
    "韩文": "all_ko",
    "中英混合": "zh",
    "粤英混合": "yue",
    "日英混合": "ja",
    "韩英混合": "ko",
    "多语种混合": "auto",
    "多语种混合(粤语)": "auto_yue",
    "all_zh": "all_zh",
    "all_yue": "all_yue",
    "en": "en",
    "all_ja": "all_ja",
    "all_ko": "all_ko",
    "zh": "zh",
    "yue": "yue",
    "ja": "ja",
    "ko": "ko",
    "auto": "auto",
    "auto_yue": "auto_yue",
}

tts_lock = asyncio.Lock()


async def generate_speech(interaction, text, text_language, cut_punc, top_k, top_p, temperature, speed, sample_steps,
                          speaker):
    try:
        await interaction.response.defer()
        await interaction.edit_original_response(content=f"🎧 {text_language}: {text}")
    except discord.NotFound as e:
        print(f"❗ Error handling interaction: {e}")
        return

    if text_language not in dict_language.values():
        return await interaction.edit_original_response(
            content=f"Invalid language. Choose from: {list(dict_language.values())}")

    tts_server = os.getenv("TTS_SERVER")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(tts_server, timeout=3):
                pass
    except Exception as e:
        print(f"❗ TTS server unreachable: {e}")
        return await interaction.edit_original_response(
            content=f"❌ TTS server is down or unreachable. Wake up the TTS server at {tts_server}.")

    model_paths = {
        "KCR": {
            "gpt": os.getenv("KCR_GPT"),
            "sovits": os.getenv("KCR_SOVITS"),
            "ref_wav": os.getenv("KCR_REFERENCE"),
            "ref_text": os.getenv("KCR_REF_TEXT")
        },
        "MTR": {
            "gpt": os.getenv("MTR_GPT"),
            "sovits": os.getenv("MTR_SOVITS"),
            "ref_wav": os.getenv("MTR_REFERENCE"),
            "ref_text": os.getenv("MTR_REF_TEXT")
        }
    }.get(speaker)

    async with tts_lock:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        }

        set_model_url = f"{tts_server}/set_model?gpt_model_path={model_paths['gpt']}&sovits_model_path={model_paths['sovits']}"
        print(f"[DEBUG] Set model: {set_model_url}")
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(set_model_url) as response:
                    print(f"[DEBUG] Set model response: {response.status}")

                    if not response.ok:
                        return await interaction.edit_original_response(
                            content=f"❌ Invalid response from {tts_server}. "
                                    f"Open https://huggingface.co/spaces/i998979/GPT-SoVITS-CPUFast to wake it up.")
        except Exception as e:
            print(f"❗ Error setting model: {e}")
            return await interaction.edit_original_response(content="❌ Failed to set TTS model.")

        api_url = (
            f"{tts_server}?text={text}&text_language={text_language}&cut_punc={cut_punc}"
            f"&top_k={top_k}&top_p={top_p}&temperature={temperature}&speed={speed}&sample_steps={sample_steps}"
            f"&refer_wav_path={model_paths['ref_wav']}&prompt_text={model_paths['ref_text']}&prompt_language=yue"
        )
        print(f"[DEBUG] TTS API: {api_url}")
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(api_url) as response:
                    timestamp = str(int(time.time() * 1000))
                    audio_path = f"{timestamp}.wav"
                    audio_data = await response.read()
                    await asyncio.to_thread(lambda: open(audio_path, "wb").write(audio_data))
        except Exception as e:
            print(f"❗ Error generating audio: {e}")
            return await interaction.edit_original_response(content="❌ Error generating audio.")

    # 如果使用者不在語音頻道，直接傳送檔案並刪除
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send(file=discord.File(audio_path, filename=f"{text}.wav"))
        await interaction.edit_original_response(content=f"💾 {text_language}: {text}")
        if os.path.exists(audio_path):
            print(f"Removed: {audio_path}")
            os.remove(audio_path)
        return
    else:
        # 使用者在語音頻道，進入隊列播放（enqueue_audio 播放完畢後會自動刪除）
        await enqueue_audio(interaction, audio_path, is_temp=True)


async def enqueue_audio(interaction: discord.Interaction, audio_path: str, is_temp=True):
    global is_playing
    await audio_queue.put((interaction, audio_path, is_temp))

    if is_playing:
        return

    is_playing = True

    while not audio_queue.empty():
        interaction, audio_path, is_temp = await audio_queue.get()
        channel = interaction.user.voice.channel

        vc = discord.utils.get(interaction.client.voice_clients, guild=interaction.guild)
        if vc is None or not vc.is_connected():
            vc = await channel.connect()

        play_done_event = asyncio.Event()

        def after_play(error):
            async def update_response():
                await interaction.edit_original_response(content=f"✅ {content[2:]}")

                if is_temp and os.path.exists(audio_path):
                    os.remove(audio_path)
                    print(f"Removed: {audio_path}")

            asyncio.run_coroutine_threadsafe(update_response(), interaction.client.loop)
            interaction.client.loop.call_soon_threadsafe(play_done_event.set)

            if error:
                print(f"Playback error: {error}")

        try:
            message = await interaction.original_response()
            content = message.content
            await interaction.edit_original_response(content=f"🔉 {content[2:]}")

            audio_source = await discord.FFmpegOpusAudio.from_probe(audio_path, method='fallback', options="-threads 1")
            vc.play(audio_source, after=after_play)
        except Exception as e:
            print(f"Error during audio playback: {e}")
            if is_temp and os.path.exists(audio_path):
                os.remove(audio_path)
            continue

        await play_done_event.wait()

    is_playing = False


@tree.command(name="kcr_speak", description="Generate speech using GPT-SoVITS")
async def kcr_speak(interaction: discord.Interaction, text: str, text_language: str = "yue", cut_punc: str = ".。",
                    top_k: int = 15, top_p: float = 1.0, temperature: float = 1.0, speed: float = 1.0,
                    sample_steps: int = 32):
    await generate_speech(interaction, text, text_language, cut_punc, top_k, top_p, temperature, speed, sample_steps,
                          'KCR')


@tree.command(name="mtr_speak", description="Generate speech using GPT-SoVITS")
async def mtr_speak(interaction: discord.Interaction, text: str, text_language: str = "yue", cut_punc: str = ".。",
                    top_k: int = 15, top_p: float = 1.0, temperature: float = 1.0, speed: float = 1.0,
                    sample_steps: int = 32):
    await generate_speech(interaction, text, text_language, cut_punc, top_k, top_p, temperature, speed, sample_steps,
                          'MTR')


@client.event
async def on_voice_state_update(member, before, after):
    if before.mute is False and after.mute is True:
        vc = discord.utils.get(client.voice_clients, guild=member.guild)

        if vc and vc.is_connected() and vc.channel == after.channel:
            if not vc.is_playing():
                try:
                    audio_source = await discord.FFmpegOpusAudio.from_probe(
                        "mute.mp3",
                        method='fallback',
                        before_options="-nostdin",
                        options="-filter:a 'atempo=1.2' -threads 1"
                    )
                    vc.play(audio_source)
                except Exception as e:
                    print(f"Mute sound error: {e}")

    if not member.guild:
        return

    vc = discord.utils.get(client.voice_clients, guild=member.guild)

    if vc and vc.is_connected():
        if len(vc.channel.members) == 1:
            await vc.disconnect()
            print("Bot disconnected due to an empty voice channel.")


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    if client.user.mentioned_in(message) and len(message.mentions) == 1 and message.mentions[0] == client.user:
        if message.author.voice is None or message.author.voice.channel is None:
            await message.channel.send("You need to be in a voice channel!")
            return

        audio_file = None
        display_name = ""
        source_type = None
        target_attachment = None
        target_url = None

        for attachment in message.attachments:
            if attachment.filename.lower().endswith((".mp3", ".wav", ".ogg", ".flac", ".m4a", ".mp4", ".mkv", ".webm")):
                target_attachment = attachment
                display_name = attachment.filename
                source_type = 'attachment'
                break

        if not source_type:
            urls = re.findall(URL_REGEX, message.content)
            if urls:
                target_url = urls[0]
                clean_url = target_url.split('?')[0]

                if any(clean_url.lower().endswith(ext) for ext in
                       [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".mp4", ".mkv", ".webm"]):
                    display_name = clean_url.split('/')[-1]
                    source_type = 'direct_url'
                else:
                    display_name = "Youtube Audio"
                    source_type = 'stream'

        if not source_type:
            await message.channel.send("Please attach or provide a valid audio/video link!")
            return

        timestamp = str(int(time.time() * 1000))
        status_msg = await message.channel.send(f"📥 Processing {display_name}...")

        if source_type == 'attachment':
            audio_file = f"{timestamp}_{target_attachment.filename}"
            await target_attachment.save(audio_file)

        elif source_type == 'direct_url':
            audio_file = f"{timestamp}.mp3"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(target_url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            await asyncio.to_thread(lambda: open(audio_file, "wb").write(data))
                        else:
                            audio_file = None
            except Exception as e:
                print(f"Error downloading direct link: {e}")
                audio_file = None

        elif source_type == 'stream':
            audio_file = f"{timestamp}.mp3"
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f"{timestamp}",
                'quiet': True,
                'no_warnings': True,
            }

            def download_with_ytdlp():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(target_url, download=True)
                    return info.get('title', 'Stream Audio')

            try:
                real_title = await asyncio.to_thread(download_with_ytdlp)
                if real_title:
                    display_name = real_title
                if not os.path.exists(audio_file):
                    audio_file = None
            except Exception as e:
                print(f"yt-dlp download error: {e}")
                audio_file = None

        if not audio_file:
            await status_msg.edit(content="❌ Failed to download or process the audio/video link.")
            return

        status_msg = await status_msg.edit(content=f"🔄 {display_name}")

        class FakeInteraction:
            def __init__(self, msg, sent_msg):
                self.user = msg.author
                self.guild = msg.guild
                self.client = client
                self._original_message = sent_msg

            async def original_response(self):
                return self._original_message

            async def edit_original_response(self, content):
                self._original_message = await self._original_message.edit(content=content)

        fake_interaction = FakeInteraction(message, status_msg)
        await enqueue_audio(fake_interaction, audio_file, is_temp=True)


client.run(TOKEN)