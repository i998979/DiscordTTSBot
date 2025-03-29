import asyncio
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

import discord
from discord.ext import commands
from gtts import gTTS, gTTSError
from gtts.lang import tts_langs

TOKEN = os.getenv('TOKEN')
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

client = commands.Bot(command_prefix="!", intents=intents)
tree = client.tree


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
        tts.save("speech.mp3")

        channel = interaction.user.voice.channel
        vc = discord.utils.get(client.voice_clients, guild=interaction.guild)

        if vc is None or not vc.is_connected():
            vc = await channel.connect()

        # 🔹 **Wait until previous audio finishes before playing a new one**
        while vc.is_playing():
            await asyncio.sleep(1)

        # Play tritone if enabled
        if play_tone:
            vc.play(discord.FFmpegPCMAudio(source="tritone.mp3"))
            while vc.is_playing():
                await asyncio.sleep(1)

        def after_playback(e):
            """Callback function to remove the file after playback."""
            if e:
                print(f"Error during playback: {e}")
            if os.path.exists("speech.mp3"):
                os.remove("speech.mp3")

        # Play the speech file
        vc.play(
            discord.FFmpegPCMAudio(
                source="speech.mp3",
                before_options="-nostdin",
                options="-filter:a 'atempo=1.2'"
            ), after=after_playback
        )

        await interaction.edit_original_response(content="✅ " + text)

    except ValueError:
        await interaction.edit_original_response(content="Language not supported. " + str(tts_langs()))
    except gTTSError:
        await interaction.edit_original_response(
            content="Accent not supported. https://gtts.readthedocs.io/en/latest/module.html#localized-accents")


# Discord command to generate and play celebrity TTS
@tree.command(name="celebrity_tts", description="Generate TTS using a celebrity's voice.")
async def celebrity_tts(interaction: discord.Interaction, celebrity: str, text: str):
    """Generates and plays TTS in a celebrity's voice using FakeYou."""
    await interaction.response.defer()
    await interaction.edit_original_response(content="🔉 " + text)

    if interaction.user.voice is None or interaction.user.voice.channel is None:
        await interaction.edit_original_response(content="You need to be in a voice channel!")
        return

    voice_id = celebrity  # Using voice ID directly
    job_token = await generate_tts(text, voice_id)

    if not job_token:
        await interaction.edit_original_response(
            content="Failed to generate celebrity TTS. Most likely celebrity was not found. "
                    "Refer https://api.fakeyou.com/tts/list and insert corresponding \"model_token\", "
                    "or https://fakeyou.com/explore/weights?page_size=24&weight_type=tt2, select \"Weights\", select \"tt2\" in \"All weight types\" and copy the weight from the link.")
        return

    async def process_tts():
        """Handle the TTS processing in a separate task."""
        audio_url = await wait_for_tts(job_token)

        if not audio_url:
            await interaction.edit_original_response(content="TTS generation failed or timed out.")
            return

        # Download the TTS file
        audio_path = "celebrity_tts.mp3"
        try:
            audio_data = requests.get(audio_url).content
            with open(audio_path, "wb") as f:
                f.write(audio_data)
        except Exception as e:
            await interaction.edit_original_response(content=f"Failed to download audio: {e}")
            return

        # Play the TTS in voice chat
        channel = interaction.user.voice.channel
        vc = discord.utils.get(client.voice_clients, guild=interaction.guild)

        if vc is None or not vc.is_connected():
            vc = await channel.connect()

        # 🔹 **Wait until the bot is not playing before playing new audio**
        while vc.is_playing():
            await asyncio.sleep(1)

        def after_playback(e):
            """Callback function for when playback finishes."""
            if e:
                print(f"Error during playback: {e}")
            if os.path.exists(audio_path):
                os.remove(audio_path)  # Clean up the file

        vc.play(discord.FFmpegPCMAudio(audio_path), after=after_playback)

        await interaction.edit_original_response(content="✅ " + text)

    # Start the async task without blocking the bot
    client.loop.create_task(process_tts())

    await interaction.edit_original_response(content="TTS request submitted. Processing in the background...")


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


async def generate_speech(interaction, text, text_language, cut_punc, top_k, top_p, temperature, speed, sample_steps,
                          speaker):
    await interaction.response.defer()
    await interaction.edit_original_response(content=f"🎧 {text_language}: {text}")

    if text_language not in dict_language.values():
        await interaction.edit_original_response(content="Invalid language. " + str(list(dict_language.values())))
        return

    try:
        requests.get(f"{os.getenv('TTS_SERVER')}", timeout=3)
    except Exception as e:
        await interaction.edit_original_response(content="Error: TTS server is down.")
        print(e)
        return

    if speaker == 'KCR':
        set_model = f"{os.getenv('TTS_SERVER')}/set_model?gpt_model_path={os.getenv('KCR_GPT')}&sovits_model_path={os.getenv('KCR_SOVITS')}"
    else:
        set_model = f"{os.getenv('TTS_SERVER')}/set_model?gpt_model_path={os.getenv('MTR_GPT')}&sovits_model_path={os.getenv('MTR_SOVITS')}"
    print(set_model)

    api = (f"{os.getenv('TTS_SERVER')}?text={text}&text_language={text_language}&cut_punc={cut_punc}"
           f"&top_k={top_k}&top_p={top_p}&temperature={temperature}&speed={speed}&sample_steps={sample_steps}")

    if speaker == 'KCR':
        api += f"&refer_wav_path={os.getenv('KCR_REFERENCE')}&prompt_text={os.getenv('KCR_REF_TEXT')}&prompt_language=yue"
    else:
        api += f"&refer_wav_path={os.getenv('MTR_REFERENCE')}&prompt_text={os.getenv('MTR_REF_TEXT')}&prompt_language=yue"
    print(api)

    requests.get(set_model)
    response = requests.get(api)

    if response.status_code == 200:
        filename = f"{text}.wav"
        with open(filename, "wb") as f:
            f.write(response.content)

        if interaction.user.voice is None or interaction.user.voice.channel is None:
            await interaction.followup.send(file=discord.File(filename))
            await interaction.edit_original_response(content=f"💾 {text_language}: {text}")
        else:
            channel = interaction.user.voice.channel
            vc = discord.utils.get(client.voice_clients, guild=interaction.guild)

            if vc is None or not vc.is_connected():
                vc = await channel.connect()

            while vc.is_playing():
                await asyncio.sleep(1)

            def after_playback(e):
                if e:
                    print(f"Error playing audio: {e}")
                if os.path.exists(filename):
                    os.remove(filename)

            vc.play(discord.FFmpegPCMAudio(filename), after=after_playback)
            await interaction.followup.send(file=discord.File(filename))
            await interaction.edit_original_response(content=f"✅ {text_language}: {text}")
    else:
        await interaction.edit_original_response(content="Error generating audio.")


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
