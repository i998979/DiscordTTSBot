import asyncio
import os
import time

import aiohttp
import discord
import requests
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


@client.event
async def on_ready():
    await tree.sync()
    await tree.sync(guild=discord.Object(id=os.getenv('GUILD')))
    print(f'Logged in as {client.user}')


# Speak command (Prevents playing multiple audios at the same time)
@tree.command(name="speak", description="Bot joins VC and speaks the given text in the specified language.")
async def speak(interaction: discord.Interaction, text: str, lang: str = 'yue', accent: str = 'com',
                play_tone: bool = False):
    await interaction.response.defer()
    await interaction.edit_original_response(content="🔉 " + text)

    if interaction.user.voice is None or interaction.user.voice.channel is None:
        await interaction.edit_original_response(content="You need to be in a voice channel!")
        return

    try:
        tts = gTTS(text, lang=lang, tld=accent)
        timestamp = str(int(time.time() * 1000))
        audio_path = f"{timestamp}.mp3"
        tts.save(audio_path)

        if play_tone:
            # Optional: enqueue tritone first
            await enqueue_audio(interaction, "tritone.mp3", is_temp=False)

        # Enqueue generated audio
        await enqueue_audio(interaction, audio_path)
    except ValueError:
        await interaction.edit_original_response(content="Language not supported. " + str(tts_langs()))
    except gTTSError:
        await interaction.edit_original_response(
            content="Accent not supported. https://gtts.readthedocs.io/en/latest/module.html#localized-accents")


# Generate TTS using FakeYou API and return job token
async def generate_tts(text, voice_id):
    """Generate TTS using FakeYou API and return job token."""
    url = "https://api.fakeyou.com/tts/inference"
    headers = {"Content-Type": "application/json"}
    payload = {
        "uuid_idempotency_token": str(time.time()),
        "tts_model_token": voice_id,
        "inference_text": text
    }

    response = requests.post(url, json=payload, headers=headers)
    print("FakeYou API Response:", response.status_code, response.text)

    if response.status_code != 200:
        return None

    result = response.json()
    if not result.get("success"):
        return None

    return result["inference_job_token"]


# Poll for the TTS job to complete asynchronously
async def wait_for_tts(job_token):
    """Poll FakeYou API to check if TTS is complete."""
    url = f"https://api.fakeyou.com/tts/job/{job_token}"

    for _ in range(10):  # Retry up to 10 times
        await asyncio.sleep(2)  # Use async sleep to avoid blocking
        status_response = requests.get(url)
        status_data = status_response.json()

        print("Job Status:", status_data)

        if status_data.get("state", {}).get("status") == "complete_success":
            return "https://cdn-2.fakeyou.com" + status_data["state"]["maybe_public_bucket_wav_audio_path"]

    return None


# Discord command to generate and play celebrity TTS
@tree.command(name="celebrity_tts", description="Generate TTS using a celebrity's voice.")
async def celebrity_tts(interaction: discord.Interaction, celebrity: str, text: str):
    """Generates and plays TTS in a celebrity's voice using FakeYou."""
    await interaction.response.defer()
    await interaction.edit_original_response(content=f"🔄 {text}")

    if interaction.user.voice is None or interaction.user.voice.channel is None:
        return await interaction.edit_original_response(content="You need to be in a voice channel!")

    voice_id = celebrity  # Using voice ID directly
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

    # Download the TTS file
    timestamp = str(int(time.time() * 1000))
    audio_path = f"{timestamp}.mp3"

    try:
        audio_data = requests.get(audio_url).content
        with open(audio_path, "wb") as f:
            f.write(audio_data)
    except Exception as e:
        return await interaction.edit_original_response(content=f"❌ Failed to download audio: {e}")

    # Enqueue the audio (VC connection + cleanup handled by the queue system)
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
    "多语种混合": "auto",  # 多语种启动切分识别语种
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
        return await interaction.edit_original_response(content="❌ TTS server is down or unreachable.")

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

    # Sequential section starts here
    async with tts_lock:
        set_model_url = f"{tts_server}/set_model?gpt_model_path={model_paths['gpt']}&sovits_model_path={model_paths['sovits']}"
        print(f"[DEBUG] Set model: {set_model_url}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(set_model_url) as response:
                    print(f"[DEBUG] Set model response: {response.status}")
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
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as response:
                    timestamp = str(int(time.time() * 1000))
                    audio_path = f"{timestamp}.wav"
                    with open(audio_path, "wb") as f:
                        f.write(await response.read())
        except Exception as e:
            print(f"❗ Error generating audio: {e}")
            return await interaction.edit_original_response(content="❌ Error generating audio.")

    # Outside lock – enqueue audio or send file
    await interaction.followup.send(file=discord.File(audio_path, filename=f"{text}.wav"))

    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.edit_original_response(content=f"💾 {text_language}: {text}")
        if os.path.exists(audio_path):
            print(f"Removed: {audio_path}")
            os.remove(audio_path)
        return
    else:
        await enqueue_audio(interaction, audio_path)


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

        def after_play(error):
            async def update_response():
                await interaction.edit_original_response(content=f"✅ {content[1:]}")

                if is_temp and os.path.exists(audio_path):
                    os.remove(audio_path)
                    print(f"Removed: {audio_path}")

            asyncio.run_coroutine_threadsafe(update_response(), interaction.client.loop)

            if error:
                print(f"Playback error: {error}")

        try:
            message = await interaction.original_response()
            content = message.content
            await interaction.edit_original_response(content=f"🔉 {content[1:]}")
            vc.play(discord.FFmpegPCMAudio(audio_path), after=after_play)
        except Exception as e:
            print(f"Error during audio playback: {e}")
            if is_temp and os.path.exists(audio_path):
                os.remove(audio_path)
            continue

        while vc.is_playing():
            await asyncio.sleep(1)

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
    """Plays a sound when a user mutes themselves."""

    if before.mute is False and after.mute is True:  # User just muted
        vc = discord.utils.get(client.voice_clients, guild=member.guild)

        # Ensure the bot is in the same voice channel
        if vc and vc.is_connected() and vc.channel == after.channel:
            if not vc.is_playing():
                vc.play(discord.FFmpegPCMAudio(
                    source="mute.mp3",
                    before_options="-nostdin",
                    options="-filter:a 'atempo=1.2'"
                ))  # Play mute sound

    """Disconnects the bot if it is alone in the voice channel."""
    if not member.guild:  # Ensure it's a valid guild
        return

    vc = discord.utils.get(client.voice_clients, guild=member.guild)

    if vc and vc.is_connected():  # Ensure bot is in a voice channel
        if len(vc.channel.members) == 1:  # Only the bot remains
            await vc.disconnect()
            print("Bot disconnected due to an empty voice channel.")


client.run(TOKEN)
