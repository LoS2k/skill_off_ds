"""
SkillOFF and KO — Combined Bot v4
===================================
Об'єднує:
  • Тимчасові голосові кімнати (slash-команди /lock /unlock /rename /limit /permit /kick /transfer /rooms)
  • Кнопки ролей при вході (Гравець / Капітан / Глядач / Стрімер)
  • Красиве привітання нових учасників + ЛС
  • Стрімер-команди: !match !score !map !poll !winner !mvp !gg !announce !bracket
  • Реєстрація команд: !register + авто-роль Капітана і Гравця
  • Збереження команд між перезапусками (teams_data.json)
  • Keep-alive HTTP (для Railway/Render)

Змінні середовища (Railway → Variables):
  TOKEN     = токен бота
  GUILD_ID  = ID сервера
  TEAM_SIZE = 3 (або 5, 7)
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View
import asyncio, json, os, time
from datetime import datetime
from dotenv import load_dotenv
import aiohttp
import feedparser

load_dotenv()

# ─── Конфіг ──────────────────────────────────────────────────────────────────
TOKEN     = os.getenv("TOKEN", "")
GUILD_ID  = int(os.getenv("GUILD_ID", "0"))
TEAM_SIZE = int(os.getenv("TEAM_SIZE", "3"))

# Голосові кімнати
TRIGGER_NAME   = "➕ Створити кімнату"
ROOMS_CATEGORY = "🎮 Кімнати команд"
ROOM_PREFIX    = "🪖 "
DEFAULT_LIMIT  = 0

# Канали (мають збігатися з назвами на вашому сервері)
CH_WELCOME  = "glory-to-ukraine"
CH_VERIFY   = "верифікація"
CH_ANNOUNCE = "оголошення"
CH_RESULTS  = "live-результати"
CH_BRACKET  = "розклад"

STATE_FILE = "rooms_state.json"
TEAMS_FILE = "teams_data.json"

# ── Сповіщення про стріми ─────────────────────────────────────────────────────
TWITCH_CLIENT_ID     = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
NOTIFY_CHANNEL_NAME  = os.getenv("NOTIFY_CHANNEL", "стріми")
CHECK_INTERVAL       = 300   # секунд між перевірками (5 хв)
STREAMERS_FILE       = "streamers.json"

streamers_data: dict   = {"youtube": [], "twitch": [], "tiktok": []}
twitch_token: str      = ""
twitch_token_expires: float = 0.0
# ─────────────────────────────────────────────────────────────────────────────

# Стан
active_rooms:     dict[int, dict]   = {}  # room_id → {owner_id, guild_id, locked, ...}
registered_teams: dict[str, list]   = {}  # team_name → [player1, ...]

intents = discord.Intents.default()
intents.message_content = True
intents.members         = True
intents.voice_states    = True

bot  = commands.Bot(command_prefix="!", intents=intents, help_command=None)
tree = bot.tree


# ═══════════════════════════════════════════════════════════════════════════════
# Keep-alive (Render)
# ═══════════════════════════════════════════════════════════════════════════════
def run_keepalive():
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers()
            self.wfile.write(b"alive")
        def log_message(self, *a): pass
    def _s(): HTTPServer(("0.0.0.0", int(os.getenv("PORT","8080"))), _H).serve_forever()
    threading.Thread(target=_s, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════════
# Збереження / завантаження
# ═══════════════════════════════════════════════════════════════════════════════
def save_rooms():
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in active_rooms.items()}, f, ensure_ascii=False)

def load_rooms():
    if not os.path.exists(STATE_FILE): return
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                active_rooms[int(k)] = v
        print(f"[✓] Кімнати: завантажено {len(active_rooms)}")
    except Exception as e:
        print(f"[!] rooms state: {e}")

def save_teams():
    with open(TEAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(registered_teams, f, ensure_ascii=False, indent=2)

def load_teams():
    global registered_teams
    if not os.path.exists(TEAMS_FILE): return
    try:
        with open(TEAMS_FILE, encoding="utf-8") as f:
            registered_teams = json.load(f)
        print(f"[✓] Команди: завантажено {len(registered_teams)}")
    except Exception as e:
        print(f"[!] teams state: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Хелпери
# ═══════════════════════════════════════════════════════════════════════════════
def _ch(guild, name):
    return discord.utils.find(lambda c: name.lower() in c.name.lower(), guild.text_channels)

def get_trigger(guild):
    return discord.utils.find(
        lambda c: c.name.strip() == TRIGGER_NAME.strip(), guild.voice_channels)

async def get_rooms_cat(guild):
    cat = discord.utils.get(guild.categories, name=ROOMS_CATEGORY)
    if cat is None:
        cat = await guild.create_category(ROOMS_CATEGORY)
        print(f"[+] Категорію створено: {ROOMS_CATEGORY}")
    return cat

def get_user_room(member: discord.Member):
    """Кімната якою цей гравець ВОЛОДІЄ і в якій зараз знаходиться."""
    if not member.voice or not member.voice.channel: return None
    ch = member.voice.channel
    info = active_rooms.get(ch.id)
    if info and info["owner_id"] == member.id:
        return ch
    return None

def _is_staff(ctx):
    return (ctx.author.guild_permissions.administrator or
            discord.utils.find(
                lambda r: any(k in r.name for k in ("Адмін","Стрімер","Суддя")),
                ctx.author.roles))

async def _send_to(ctx, ch_name, embed=None, mention=None):
    ch = _ch(ctx.guild, ch_name) or ctx.channel
    kwargs = {"embed": embed} if embed else {}
    if mention: await ch.send(mention, **kwargs)
    else:        await ch.send(**kwargs)
    if ch != ctx.channel:
        try: await ctx.message.delete()
        except: pass


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW: Кнопки ролей
# ═══════════════════════════════════════════════════════════════════════════════
class RoleView(View):
    def __init__(self): super().__init__(timeout=None)

    async def _give(self, interaction: discord.Interaction, keyword: str):
        role = discord.utils.find(lambda r: keyword.lower() in r.name.lower(), interaction.guild.roles)
        if not role:
            await interaction.response.send_message(
                f"⚠️ Роль «{keyword}» не знайдена. Зверніться до адміна.", ephemeral=True); return
        if role in interaction.user.roles:
            await interaction.response.send_message(
                f"ℹ️ У вас вже є роль **{role.name}**!", ephemeral=True); return
        try:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(
                f"✅ Роль **{role.name}** видано!\nТепер маєте доступ до відповідних каналів.",
                ephemeral=True)
            print(f"[+] {role.name} → {interaction.user.display_name}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ Бот не може видати роль. Переконайтесь що роль бота вища за ролі гравців.",
                ephemeral=True)

    @discord.ui.button(label="🎮 Гравець",  style=discord.ButtonStyle.primary,   custom_id="rv_player")
    async def b1(self, i, b): await self._give(i, "Гравець")

    @discord.ui.button(label="🎖️ Капітан", style=discord.ButtonStyle.success,   custom_id="rv_captain")
    async def b2(self, i, b): await self._give(i, "Капітан")

    @discord.ui.button(label="👁️ Глядач",  style=discord.ButtonStyle.secondary, custom_id="rv_viewer")
    async def b3(self, i, b): await self._give(i, "Глядач")

    @discord.ui.button(label="🎙️ Стрімер", style=discord.ButtonStyle.danger,    custom_id="rv_streamer")
    async def b4(self, i, b): await self._give(i, "Стрімер")


# ═══════════════════════════════════════════════════════════════════════════════
# СТАРТ
# ═══════════════════════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    load_rooms(); load_teams(); load_streamers()
    bot.add_view(RoleView())

    # Синхронізуємо slash-команди на конкретний сервер (миттєво)
    # Глобальна синхронізація без guild= займає до 1 години!
    guild_obj = discord.Object(id=GUILD_ID)
    tree.copy_global_to(guild=guild_obj)
    await tree.sync(guild=guild_obj)
    print(f"[✓] Slash-команди синхронізовано на сервер {GUILD_ID}")

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print(f"[!] Сервер {GUILD_ID} не знайдено"); return

    print(f"[✓] Бот: {bot.user} | Сервер: {guild.name} | {TEAM_SIZE}v{TEAM_SIZE}")
    await _post_role_buttons(guild)
    cleanup_loop.start()
    notify_loop.start()
    print("[✓] Бот готовий!")


async def _post_role_buttons(guild):
    ch = _ch(guild, CH_VERIFY) or _ch(guild, "реєстрація") or _ch(guild, "verify")
    if not ch:
        print(f"[!] Канал верифікації «{CH_VERIFY}» не знайдено"); return
    async for msg in ch.history(limit=30):
        if msg.author == bot.user and msg.embeds and "Оберіть свою роль" in (msg.embeds[0].title or ""):
            print(f"[=] Кнопки ролей вже є в #{ch.name}"); return
    embed = discord.Embed(
        title="🎮 Оберіть свою роль на сервері",
        description=(
            "Натисніть кнопку — роль видається миттєво.\n\n"
            "🎮 **Гравець** — учасник турніру\n"
            "🎖️ **Капітан** — реєструє команду через `!register`\n"
            "👁️ **Глядач** — слідкує за турніром\n"
            "🎙️ **Стрімер** — стрімить, доступ до стрімер-команд\n\n"
            "*Роль можна змінити — натисніть іншу кнопку*"
        ),
        color=discord.Color.from_rgb(88, 101, 242)
    )
    embed.set_footer(text="SkillOFF and KO • Tank Company Tournament")
    embed.timestamp = datetime.now()
    await ch.send(embed=embed, view=RoleView())
    print(f"[+] Кнопки ролей → #{ch.name}")


# ═══════════════════════════════════════════════════════════════════════════════
# ПРИВІТАННЯ
# ═══════════════════════════════════════════════════════════════════════════════
@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    ch = _ch(guild, CH_WELCOME) or _ch(guild, "welcome") or _ch(guild, "загальний")
    if ch:
        vc = _ch(guild, CH_VERIFY) or _ch(guild, "реєстрація")
        vm = vc.mention if vc else "#верифікація"
        embed = discord.Embed(
            title=f"👋 {member.display_name} приєднався!",
            description=(
                f"Ласкаво просимо на **{guild.name}**! 🎮\n\n"
                f"1️⃣ Перейди в {vm} та обери роль\n"
                f"2️⃣ Слідкуй за `#оголошення`\n"
                f"3️⃣ Капітани — реєструйте команду: `!register`\n\n"
                f"Удачі в боях, {member.mention}! ⚔️"
            ),
            color=discord.Color.from_rgb(29, 185, 84)
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Учасник #{guild.member_count} • SkillOFF and KO")
        embed.timestamp = datetime.now()
        await ch.send(embed=embed)
    try:
        dm = discord.Embed(
            title=f"🏆 Ласкаво просимо на {guild.name}!",
            description=(
                f"Привіт, **{member.display_name}**! 👋\n\n"
                "• Обери роль кнопкою в каналі верифікації\n"
                "• Капітан команди пише `!register`\n"
                "• Питання? Пиши в загальний чат\n\n"
                "*Бажаємо перемог!* 🥇"
            ),
            color=discord.Color.from_rgb(88, 101, 242)
        )
        dm.set_footer(text="SkillOFF and KO")
        await member.send(embed=dm)
    except discord.Forbidden:
        pass
    print(f"[+] Новий: {member.display_name}")


# ═══════════════════════════════════════════════════════════════════════════════
# ГОЛОСОВІ КІМНАТИ — події
# ═══════════════════════════════════════════════════════════════════════════════
@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild

    # Зайшов у тригер → створити кімнату
    if after.channel and after.channel.name.strip() == TRIGGER_NAME.strip():
        await _create_room(guild, member)

    # Вийшов з кімнати → перевірити чи порожня
    if before.channel and before.channel.id in active_rooms:
        await _check_delete(before.channel)


async def _create_room(guild, owner):
    category = await get_rooms_cat(guild)
    name = f"{ROOM_PREFIX}{owner.display_name}"
    ow = {
        guild.default_role: discord.PermissionOverwrite(connect=True, speak=True),
        owner:              discord.PermissionOverwrite(
                                connect=True, speak=True, manage_channels=True,
                                move_members=True, mute_members=True, deafen_members=True),
        guild.me:           discord.PermissionOverwrite(
                                connect=True, manage_channels=True, move_members=True),
    }
    ch = await guild.create_voice_channel(name=name, category=category,
                                           overwrites=ow, user_limit=DEFAULT_LIMIT)
    try:
        await owner.move_to(ch)
    except discord.HTTPException:
        await ch.delete(); return

    active_rooms[ch.id] = {
        "owner_id":   owner.id,
        "guild_id":   guild.id,
        "created_at": datetime.now().isoformat(),
        "locked":     False,
    }
    save_rooms()
    print(f"[+] Кімната: {name}")


async def _check_delete(channel):
    if channel.id not in active_rooms: return
    if len(channel.members) == 0:
        try:
            await channel.delete(reason="порожня")
            print(f"[-] Видалено: {channel.name}")
        except discord.NotFound:
            pass
        active_rooms.pop(channel.id, None)
        save_rooms()


@tasks.loop(minutes=2)
async def cleanup_loop():
    for room_id, info in list(active_rooms.items()):
        guild = bot.get_guild(info["guild_id"])
        if not guild: active_rooms.pop(room_id, None); continue
        ch = guild.get_channel(room_id)
        if ch is None: active_rooms.pop(room_id, None); continue
        if len(ch.members) == 0:
            await _check_delete(ch)
    save_rooms()


# ═══════════════════════════════════════════════════════════════════════════════
# SLASH-КОМАНДИ ДЛЯ КІМНАТ  (/lock /unlock /rename /limit /permit /kick /transfer /rooms)
# ═══════════════════════════════════════════════════════════════════════════════
@tree.command(name="lock", description="Закрити кімнату від нових учасників")
async def sl_lock(interaction: discord.Interaction):
    room = get_user_room(interaction.user)
    if not room:
        await interaction.response.send_message("❌ Ти не в своїй кімнаті.", ephemeral=True); return
    await room.set_permissions(interaction.guild.default_role, connect=False)
    active_rooms[room.id]["locked"] = True; save_rooms()
    await interaction.response.send_message(f"🔒 **{room.name}** закрито.", ephemeral=True)


@tree.command(name="unlock", description="Відкрити кімнату для всіх")
async def sl_unlock(interaction: discord.Interaction):
    room = get_user_room(interaction.user)
    if not room:
        await interaction.response.send_message("❌ Ти не в своїй кімнаті.", ephemeral=True); return
    await room.set_permissions(interaction.guild.default_role, connect=True)
    active_rooms[room.id]["locked"] = False; save_rooms()
    await interaction.response.send_message(f"🔓 **{room.name}** відкрито.", ephemeral=True)


@tree.command(name="rename", description="Перейменувати свою кімнату")
@app_commands.describe(name="Нова назва")
async def sl_rename(interaction: discord.Interaction, name: str):
    room = get_user_room(interaction.user)
    if not room:
        await interaction.response.send_message("❌ Ти не в своїй кімнаті.", ephemeral=True); return
    if len(name) > 32:
        await interaction.response.send_message("❌ Макс. 32 символи.", ephemeral=True); return
    old = room.name
    await room.edit(name=f"{ROOM_PREFIX}{name}")
    await interaction.response.send_message(f"✏️ {old} → **{ROOM_PREFIX}{name}**", ephemeral=True)


@tree.command(name="limit", description="Ліміт учасників у кімнаті")
@app_commands.describe(slots="Кількість місць (0 = без ліміту)")
async def sl_limit(interaction: discord.Interaction, slots: int):
    room = get_user_room(interaction.user)
    if not room:
        await interaction.response.send_message("❌ Ти не в своїй кімнаті.", ephemeral=True); return
    if not (0 <= slots <= 99):
        await interaction.response.send_message("❌ Від 0 до 99.", ephemeral=True); return
    await room.edit(user_limit=slots)
    txt = "без ліміту" if slots == 0 else f"{slots} місць"
    await interaction.response.send_message(f"👥 Ліміт: **{txt}**", ephemeral=True)


@tree.command(name="permit", description="Впустити гравця в закриту кімнату")
@app_commands.describe(member="Гравець")
async def sl_permit(interaction: discord.Interaction, member: discord.Member):
    room = get_user_room(interaction.user)
    if not room:
        await interaction.response.send_message("❌ Ти не в своїй кімнаті.", ephemeral=True); return
    await room.set_permissions(member, connect=True, speak=True)
    await interaction.response.send_message(f"✅ **{member.display_name}** може зайти.", ephemeral=True)


@tree.command(name="kick", description="Вигнати гравця зі своєї кімнати")
@app_commands.describe(member="Гравець")
async def sl_kick(interaction: discord.Interaction, member: discord.Member):
    room = get_user_room(interaction.user)
    if not room:
        await interaction.response.send_message("❌ Ти не в своїй кімнаті.", ephemeral=True); return
    if member.id == interaction.user.id:
        await interaction.response.send_message("❌ Не можна вигнати себе.", ephemeral=True); return
    if member.voice and member.voice.channel == room:
        lobby = get_trigger(interaction.guild)
        await member.move_to(lobby)
        await room.set_permissions(member, connect=False)
        await interaction.response.send_message(f"👢 **{member.display_name}** вигнано.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ **{member.display_name}** не в твоїй кімнаті.", ephemeral=True)


@tree.command(name="transfer", description="Передати права власника кімнати")
@app_commands.describe(member="Новий власник")
async def sl_transfer(interaction: discord.Interaction, member: discord.Member):
    room = get_user_room(interaction.user)
    if not room:
        await interaction.response.send_message("❌ Ти не в своїй кімнаті.", ephemeral=True); return
    if member not in room.members:
        await interaction.response.send_message("❌ Гравець не в твоїй кімнаті.", ephemeral=True); return
    await room.set_permissions(interaction.user, overwrite=None)
    await room.set_permissions(member, connect=True, speak=True,
                                manage_channels=True, move_members=True,
                                mute_members=True, deafen_members=True)
    active_rooms[room.id]["owner_id"] = member.id; save_rooms()
    await interaction.response.send_message(f"👑 Права передано **{member.display_name}**.", ephemeral=True)


@tree.command(name="rooms", description="Список активних кімнат")
async def sl_rooms(interaction: discord.Interaction):
    if not active_rooms:
        await interaction.response.send_message("🏜️ Активних кімнат немає.", ephemeral=True); return
    lines = []
    for rid, info in active_rooms.items():
        ch = interaction.guild.get_channel(rid)
        if not ch: continue
        owner = interaction.guild.get_member(info["owner_id"])
        lock  = "🔒" if info.get("locked") else "🔓"
        cnt   = len(ch.members)
        lim   = f"/{ch.user_limit}" if ch.user_limit else ""
        lines.append(f"{lock} **{ch.name}** — {cnt}{lim} | {owner.display_name if owner else '?'}")
    embed = discord.Embed(
        title="🎮 Активні кімнати",
        description="\n".join(lines) or "Немає",
        color=0xf5a623
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="setup", description="[Адмін] Створити тригер і категорію")
@app_commands.checks.has_permissions(administrator=True)
async def sl_setup(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    cat   = await get_rooms_cat(guild)
    trig  = get_trigger(guild)
    if trig is None:
        trig = await guild.create_voice_channel(name=TRIGGER_NAME, category=cat)
        msg = f"✅ Створено:\n• **{ROOMS_CATEGORY}**\n• **{TRIGGER_NAME}**"
    else:
        msg = f"ℹ️ Канал **{TRIGGER_NAME}** вже існує. Все готово!"
    await interaction.followup.send(msg, ephemeral=True)


# ═══════════════════════════════════════════════════════════════════════════════
# СТРІМЕР-КОМАНДИ  (!match !score !map !poll !winner !mvp !gg !announce !bracket)
# ═══════════════════════════════════════════════════════════════════════════════
@bot.command(name="match")
async def cmd_match(ctx, *, args: str):
    """!match Команда1 vs Команда2 | НазваМапи"""
    if not _is_staff(ctx): return
    parts = [p.strip() for p in args.split("|")]
    teams = parts[0]; map_n = parts[1] if len(parts) > 1 else "TBD"
    embed = discord.Embed(
        title="⚔️ Матч починається!",
        description=f"## {teams}\n🗺️ Мапа: **{map_n}**",
        color=discord.Color.from_rgb(231, 76, 60)
    )
    embed.set_footer(text="Tank Company Tournament • SkillOFF and KO")
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_ANNOUNCE, embed=embed, mention="@everyone")

@bot.command(name="score")
async def cmd_score(ctx, *, args: str):
    """!score Команда1 2:1 Команда2"""
    if not _is_staff(ctx): return
    embed = discord.Embed(title="📊 Рахунок", description=f"# {args}",
                          color=discord.Color.from_rgb(88, 101, 242))
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_RESULTS, embed=embed)

@bot.command(name="map")
async def cmd_map(ctx, *, name: str):
    """!map НазваМапи"""
    if not _is_staff(ctx): return
    embed = discord.Embed(title="🗺️ Поточна мапа", description=f"**{name}**",
                          color=discord.Color.from_rgb(0, 150, 200))
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_ANNOUNCE, embed=embed)

@bot.command(name="winner")
async def cmd_winner(ctx, *, team: str):
    """!winner НазваКоманди"""
    if not _is_staff(ctx): return
    embed = discord.Embed(
        title="🥇 ПЕРЕМОЖЕЦЬ ТУРНІРУ!",
        description=f"# 🏆 {team} 🏆\n\nВітаємо з перемогою! 🎉🎊",
        color=discord.Color.gold()
    )
    embed.set_footer(text="Tank Company Tournament • SkillOFF and KO")
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_ANNOUNCE, embed=embed, mention="@everyone 🎉")

@bot.command(name="gg")
async def cmd_gg(ctx):
    """!gg — GG WP"""
    if not _is_staff(ctx): return
    embed = discord.Embed(
        title="🏆 GG WP — Матч завершено!",
        description="Дякуємо всім за гру! Результати незабаром.",
        color=discord.Color.gold()
    )
    embed.set_footer(text="Tank Company Tournament • SkillOFF and KO")
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_ANNOUNCE, embed=embed)

@bot.command(name="mvp")
async def cmd_mvp(ctx, member: discord.Member, *, reason: str = ""):
    """!mvp @гравець Причина"""
    if not _is_staff(ctx): return
    embed = discord.Embed(
        title="⭐ MVP Матчу!",
        description=f"# {member.mention}\n\n{reason or 'За видатну гру!'}",
        color=discord.Color.from_rgb(255, 215, 0)
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Tank Company Tournament")
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_ANNOUNCE, embed=embed)

@bot.command(name="poll")
async def cmd_poll(ctx, *, args: str):
    """!poll Питання | Варіант1 | Варіант2"""
    if not _is_staff(ctx): return
    parts = [p.strip() for p in args.split("|")]
    if len(parts) < 3:
        await ctx.reply("⚠️ `!poll Питання | Варіант1 | Варіант2`", delete_after=8); return
    nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    opts = parts[1:10]
    embed = discord.Embed(
        title=f"📊 {parts[0]}",
        description="\n".join(f"{nums[i]} **{o}**" for i,o in enumerate(opts)),
        color=discord.Color.from_rgb(230, 126, 34)
    )
    embed.set_footer(text="Проголосуйте реакцією нижче")
    embed.timestamp = datetime.now()
    ch = _ch(ctx.guild, CH_ANNOUNCE) or ctx.channel
    msg = await ch.send(embed=embed)
    for i in range(len(opts)): await msg.add_reaction(nums[i])
    if ch != ctx.channel:
        try: await ctx.message.delete()
        except: pass

@bot.command(name="bracket")
async def cmd_bracket(ctx, *, info: str):
    """!bracket Текст про сітку"""
    if not _is_staff(ctx): return
    embed = discord.Embed(title="🔱 Турнірна сітка", description=info,
                          color=discord.Color.from_rgb(155, 89, 182))
    embed.set_footer(text="Tank Company Tournament • SkillOFF and KO")
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_BRACKET, embed=embed, mention="@everyone")

@bot.command(name="announce")
async def cmd_announce(ctx, *, text: str):
    """!announce Текст"""
    if not _is_staff(ctx): return
    embed = discord.Embed(description=text, color=discord.Color.from_rgb(52, 152, 219))
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_ANNOUNCE, embed=embed, mention="@everyone")


# ═══════════════════════════════════════════════════════════════════════════════
# РЕЄСТРАЦІЯ КОМАНД
# ═══════════════════════════════════════════════════════════════════════════════
@bot.command(name="register")
async def cmd_register(ctx):
    """!register НазваКоманди, Гравець1, Гравець2, Гравець3"""
    raw   = ctx.message.content[len("!register"):].strip()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) < 2:
        await ctx.reply(
            f"⚠️ Формат: `!register НазваКоманди, Гравець1, ...`\n"
            f"Потрібно {TEAM_SIZE} гравці."
        ); return
    name    = parts[0]
    players = parts[1:]
    if len(players) != TEAM_SIZE:
        ex = ", ".join(f"Гравець{i+1}" for i in range(TEAM_SIZE))
        await ctx.reply(
            f"⚠️ Потрібно **{TEAM_SIZE} гравці**, ви вказали {len(players)}.\n"
            f"Приклад: `!register {name}, {ex}`"
        ); return
    if name in registered_teams:
        await ctx.reply(f"❌ **{name}** вже зареєстровано!"); return

    registered_teams[name] = players
    save_teams()

    # Роль Капітана → автору
    cap = discord.utils.find(lambda r: "Капітан" in r.name, ctx.guild.roles)
    cap_line = ""
    if cap:
        try:
            await ctx.author.add_roles(cap)
            cap_line = f"\n🎖️ {ctx.author.mention} → **{cap.name}**"
        except discord.Forbidden:
            cap_line = "\n⚠️ Не вдалось видати роль Капітана"

    # Роль Гравця → решта
    pl = discord.utils.find(lambda r: "Гравець" in r.name, ctx.guild.roles)
    pl_lines = []
    for pname in players:
        m = discord.utils.find(
            lambda mb: mb.name.lower()==pname.lower()
                    or mb.display_name.lower()==pname.lower(),
            ctx.guild.members)
        if m and pl:
            try: await m.add_roles(pl); pl_lines.append(f"  ✅ {m.mention}")
            except: pl_lines.append(f"  ⚠️ {pname}")
        else:
            pl_lines.append(f"  ❓ **{pname}** — не на сервері")

    pl_block = ("\n👥 Гравці:\n" + "\n".join(pl_lines)) if pl_lines else ""
    await ctx.reply(
        f"✅ **{name}** зареєстровано! ({TEAM_SIZE}v{TEAM_SIZE})\n"
        f"👥 Склад: {', '.join(players)}"
        f"{cap_line}{pl_block}"
    )
    print(f"[+] Команда: {name}")

@bot.command(name="standings")
async def cmd_standings(ctx):
    if not registered_teams:
        await ctx.reply("📋 Немає команд. Реєструйте через `!register`."); return
    lines = [f"**📋 Команди ({len(registered_teams)}):**\n"]
    for i,(n,pl) in enumerate(registered_teams.items(),1):
        lines.append(f"**{i}. {n}** — {', '.join(pl)}")
    await ctx.reply("\n".join(lines))

@bot.command(name="unregister")
async def cmd_unregister(ctx, *, name: str):
    if not ctx.author.guild_permissions.administrator:
        await ctx.reply("❌ Тільки адмін.", delete_after=5); return
    if name not in registered_teams:
        await ctx.reply(f"❌ **{name}** не знайдено.", delete_after=5); return
    del registered_teams[name]; save_teams()
    await ctx.reply(f"🗑️ **{name}** видалено.")

@bot.command(name="give_role")
async def cmd_give_role(ctx, member: discord.Member, *, role_name: str):
    if not ctx.author.guild_permissions.administrator:
        await ctx.reply("❌ Тільки адмін.", delete_after=5); return
    role = discord.utils.find(lambda r: role_name.lower() in r.name.lower(), ctx.guild.roles)
    if not role:
        await ctx.reply(f"❌ Роль **{role_name}** не знайдена.", delete_after=5); return
    await member.add_roles(role)
    await ctx.reply(f"✅ **{member.display_name}** → **{role.name}**")


# ═══════════════════════════════════════════════════════════════════════════════
# !help
# ═══════════════════════════════════════════════════════════════════════════════
@bot.command(name="help")
async def cmd_help(ctx):
    embed = discord.Embed(
        title="🤖 SkillOFF Bot — Всі команди",
        color=discord.Color.from_rgb(88, 101, 242)
    )
    embed.add_field(name="🔊 Голосова кімната (slash)", inline=False, value=(
        "`/lock` `/unlock` — закрити/відкрити\n"
        "`/rename назва` — перейменувати\n"
        "`/limit N` — ліміт місць\n"
        "`/permit @гравець` — впустити\n"
        "`/kick @гравець` — вигнати\n"
        "`/transfer @гравець` — передати права\n"
        "`/rooms` — список активних кімнат\n"
        "`/setup` — [адмін] створити тригер"
    ))
    embed.add_field(name="📝 Реєстрація", inline=False, value=(
        f"`!register Назва, Гравець1, ...` — {TEAM_SIZE} гравці\n"
        "`!standings` — список команд\n"
        "`!unregister Назва` — видалити (адмін)\n"
        "`!give_role @гравець Роль` — видати роль (адмін)"
    ))
    embed.add_field(name="🎙️ Стрімер / Суддя / Адмін", inline=False, value=(
        "`!match Команда1 vs Команда2 | Мапа`\n"
        "`!score Команда1 2:1 Команда2`\n"
        "`!map НазваМапи`\n"
        "`!poll Питання | Варіант1 | Варіант2`\n"
        "`!winner НазваКоманди`\n"
        "`!mvp @гравець Причина`\n"
        "`!bracket Текст`\n"
        "`!announce Текст`\n"
        "`!gg`"
    ))
    embed.add_field(name="📡 Сповіщення про стріми", inline=False, value=(
        "`!addstreamer youtube Назва UCxxxxxx`\n"
        "`!addstreamer twitch нік`\n"
        "`!addstreamer tiktok @нік`\n"
        "`!removestreamer youtube/twitch/tiktok нік`\n"
        "`!streamers` — список всіх\n"
        "`!checkstreams` — перевірити зараз (адмін)"
    ))
    embed.set_footer(text="SkillOFF and KO • Tank Company Tournament")
    await ctx.reply(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════════

# ─── Конфіг сповіщень ────────────────────────────────────────────────────────

# Файл зі списком стрімерів і переглянутими відео
STREAMERS_FILE = "streamers.json"

# Структура streamers.json:
# {
#   "youtube":  [{"name": "SkillOFF", "channel_id": "UCxxxxxx", "last_video": ""}],
#   "twitch":   [{"name": "skilloff_ua", "last_live": false}],
#   "tiktok":   [{"name": "skilloff.ua", "last_video": ""}]
# }

streamers_data: dict = {"youtube": [], "twitch": [], "tiktok": []}
twitch_token: str = ""


# ── Збереження / завантаження ─────────────────────────────────────────────────
def load_streamers():
    global streamers_data
    if os.path.exists(STREAMERS_FILE):
        try:
            with open(STREAMERS_FILE, encoding="utf-8") as f:
                streamers_data = json.load(f)
            # Переконуємось що всі ключі є
            for k in ("youtube", "twitch", "tiktok"):
                streamers_data.setdefault(k, [])
            total = sum(len(v) for v in streamers_data.values())
            print(f"[✓] Стрімери завантажено: {total}")
        except Exception as e:
            print(f"[!] streamers load: {e}")

def save_streamers():
    with open(STREAMERS_FILE, "w", encoding="utf-8") as f:
        json.dump(streamers_data, f, ensure_ascii=False, indent=2)


# ── Отримати канал для сповіщень ──────────────────────────────────────────────
def _notify_ch(guild):
    return discord.utils.find(
        lambda c: NOTIFY_CHANNEL_NAME.lower() in c.name.lower(),
        guild.text_channels
    )


# ═══════════════════════════════════════════════════════════════════════════════
# YOUTUBE — через RSS (без API ключа)
# ═══════════════════════════════════════════════════════════════════════════════
async def check_youtube():
    """Перевіряє нові відео/стріми на YouTube через RSS."""
    guild = bot.get_guild(GUILD_ID)
    if not guild: return

    for streamer in streamers_data.get("youtube", []):
        try:
            channel_id = streamer.get("channel_id", "")
            if not channel_id:
                continue

            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

            async with aiohttp.ClientSession() as session:
                async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        continue
                    content = await resp.text()

            feed = feedparser.parse(content)
            if not feed.entries:
                continue

            latest = feed.entries[0]
            video_id  = latest.get("yt_videoid", "")
            video_url = f"https://youtube.com/watch?v={video_id}"
            title     = latest.get("title", "Нове відео")

            # Перевіряємо чи вже сповіщали
            if video_id == streamer.get("last_video", ""):
                continue

            streamer["last_video"] = video_id
            save_streamers()

            # Визначаємо чи це стрім
            is_live = "live" in title.lower() or "стрім" in title.lower() or "stream" in title.lower()

            embed = discord.Embed(
                title=f"{'🔴 LIVE' if is_live else '🎬 Нове відео'} — {streamer['name']}",
                description=f"**{title}**",
                url=video_url,
                color=discord.Color.from_rgb(255, 0, 0)  # YouTube червоний
            )
            embed.set_author(
                name=streamer["name"],
                icon_url="https://www.youtube.com/favicon.ico"
            )

            # Thumbnail через oEmbed
            thumb = latest.get("media_thumbnail", [{}])
            if thumb and isinstance(thumb, list):
                embed.set_image(url=thumb[0].get("url", ""))

            embed.add_field(name="📺 Платформа", value="YouTube", inline=True)
            embed.add_field(name="🔗 Посилання", value=video_url, inline=True)
            embed.set_footer(text="SkillOFF and KO • Сповіщення")
            embed.timestamp = datetime.now()

            ch = _notify_ch(guild)
            if ch:
                mention = "@everyone" if is_live else "@here"
                await ch.send(mention, embed=embed)
                print(f"[YT] {'LIVE' if is_live else 'Відео'}: {streamer['name']} — {title}")

        except Exception as e:
            print(f"[!] YouTube {streamer.get('name')}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# TWITCH — через офіційний API
# ═══════════════════════════════════════════════════════════════════════════════
async def get_twitch_token():
    """Отримує/оновлює App Access Token для Twitch API."""
    global twitch_token, twitch_token_expires
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        return False
    import time
    if twitch_token and time.time() < twitch_token_expires - 60:
        return True
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://id.twitch.tv/oauth2/token",
                params={
                    "client_id":     TWITCH_CLIENT_ID,
                    "client_secret": TWITCH_CLIENT_SECRET,
                    "grant_type":    "client_credentials",
                }
            ) as resp:
                if resp.status != 200:
                    print(f"[!] Twitch token error: {resp.status}")
                    return False
                data = await resp.json()
                twitch_token = data["access_token"]
                import time as _t
                twitch_token_expires = _t.time() + data.get("expires_in", 3600)
                return True
    except Exception as e:
        print(f"[!] Twitch token: {e}")
        return False


async def check_twitch():
    """Перевіряє чи стрімер онлайн на Twitch."""
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    if not await get_twitch_token(): return

    for streamer in streamers_data.get("twitch", []):
        try:
            login = streamer.get("name", "").lower()
            if not login: continue

            headers = {
                "Client-ID":     TWITCH_CLIENT_ID,
                "Authorization": f"Bearer {twitch_token}",
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.twitch.tv/helix/streams",
                    params={"user_login": login},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200: continue
                    data = await resp.json()

            streams = data.get("data", [])
            is_live = len(streams) > 0
            was_live = streamer.get("last_live", False)

            if is_live and not was_live:
                # Тільки щойно почав стрімити
                stream_info = streams[0]
                title       = stream_info.get("title", "Без назви")
                game        = stream_info.get("game_name", "")
                viewers     = stream_info.get("viewer_count", 0)
                thumbnail   = stream_info.get("thumbnail_url", "").replace("{width}", "1280").replace("{height}", "720")
                stream_url  = f"https://twitch.tv/{login}"

                embed = discord.Embed(
                    title=f"🟣 {streamer['name']} тепер LIVE на Twitch!",
                    description=f"**{title}**",
                    url=stream_url,
                    color=discord.Color.from_rgb(145, 70, 255)  # Twitch фіолетовий
                )
                embed.set_author(
                    name=streamer["name"],
                    icon_url="https://static.twitchcdn.net/assets/favicon-32-e29e246c157142c1.png"
                )
                if thumbnail:
                    embed.set_image(url=thumbnail + f"?t={int(datetime.now().timestamp())}")
                if game:
                    embed.add_field(name="🎮 Гра", value=game, inline=True)
                embed.add_field(name="👥 Глядачів", value=str(viewers), inline=True)
                embed.add_field(name="🔗 Дивитись", value=stream_url, inline=True)
                embed.set_footer(text="SkillOFF and KO • Сповіщення")
                embed.timestamp = datetime.now()

                ch = _notify_ch(guild)
                if ch:
                    await ch.send("@everyone 🔴", embed=embed)
                    print(f"[TW] LIVE: {streamer['name']} — {title}")

                streamer["last_live"] = True
                save_streamers()

            elif not is_live and was_live:
                streamer["last_live"] = False
                save_streamers()
                print(f"[TW] Офлайн: {streamer['name']}")

        except Exception as e:
            print(f"[!] Twitch {streamer.get('name')}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# TIKTOK — через RSS від proxitok (без офіційного API)
# ═══════════════════════════════════════════════════════════════════════════════
async def check_tiktok():
    """Перевіряє нові відео на TikTok через RSS проксі."""
    guild = bot.get_guild(GUILD_ID)
    if not guild: return

    # Публічні RSS проксі для TikTok (якщо один не працює — пробує інший)
    RSS_PROXIES = [
        "https://proxitok.pabloferreiro.es/@{username}/rss",
        "https://tok.itsmeow.cat/@{username}/rss",
    ]

    for streamer in streamers_data.get("tiktok", []):
        try:
            username = streamer.get("name", "").lstrip("@")
            if not username: continue

            feed = None
            for proxy in RSS_PROXIES:
                url = proxy.format(username=username)
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                            if resp.status == 200:
                                content = await resp.text()
                                feed = feedparser.parse(content)
                                if feed.entries:
                                    break
                except:
                    continue

            if not feed or not feed.entries:
                continue

            latest = feed.entries[0]
            video_id  = latest.get("id", latest.get("link", ""))
            title     = latest.get("title", "Нове відео")
            video_url = latest.get("link", f"https://tiktok.com/@{username}")

            if video_id == streamer.get("last_video", ""):
                continue

            streamer["last_video"] = video_id
            save_streamers()

            embed = discord.Embed(
                title=f"🎵 Нове TikTok відео — {streamer['name']}",
                description=f"**{title}**",
                url=video_url,
                color=discord.Color.from_rgb(0, 0, 0)  # TikTok чорний
            )
            embed.set_author(name=f"@{username}")
            embed.add_field(name="📱 Платформа", value="TikTok", inline=True)
            embed.add_field(name="🔗 Переглянути", value=video_url, inline=True)
            embed.set_footer(text="SkillOFF and KO • Сповіщення")
            embed.timestamp = datetime.now()

            ch = _notify_ch(guild)
            if ch:
                await ch.send("@here", embed=embed)
                print(f"[TT] Нове відео: {streamer['name']} — {title}")

        except Exception as e:
            print(f"[!] TikTok {streamer.get('name')}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Фоновий цикл перевірки
# ═══════════════════════════════════════════════════════════════════════════════
@tasks.loop(seconds=CHECK_INTERVAL)
async def notify_loop():
    await check_youtube()
    await check_twitch()
    await check_tiktok()


# ═══════════════════════════════════════════════════════════════════════════════
# КОМАНДИ КЕРУВАННЯ СТРІМЕРАМИ
# ═══════════════════════════════════════════════════════════════════════════════

# !addstreamer youtube НазваДляПоказу ID_Каналу
# !addstreamer twitch НікТвіч
# !addstreamer tiktok @нік

@bot.command(name="addstreamer")
async def cmd_add_streamer(ctx, platform: str, *args):
    """
    !addstreamer youtube НазваДляПоказу UCxxxxx — додати YouTube канал
    !addstreamer twitch НікТвіч              — додати Twitch стрімера
    !addstreamer tiktok @нік                 — додати TikTok акаунт

    Де взяти YouTube Channel ID:
      Відкрийте канал → About → Share → Copy channel ID
      Або з URL: youtube.com/channel/UCxxxxxx
    """
    if not ctx.author.guild_permissions.administrator and not discord.utils.find(
            lambda r: any(k in r.name for k in ("Адмін","Суддя")), ctx.author.roles):
        await ctx.reply("❌ Тільки адмін або суддя.", delete_after=6); return

    platform = platform.lower()
    if platform not in ("youtube", "twitch", "tiktok"):
        await ctx.reply(
            "❌ Платформа має бути: `youtube`, `twitch` або `tiktok`\n"
            "Приклади:\n"
            "`!addstreamer youtube SkillOFF UCabcd1234`\n"
            "`!addstreamer twitch skilloff_ua`\n"
            "`!addstreamer tiktok @skilloff.ua`"
        ); return

    if platform == "youtube":
        if len(args) < 2:
            await ctx.reply(
                "⚠️ Формат: `!addstreamer youtube НазваДляПоказу ID_Каналу`\n"
                "Channel ID виглядає як: `UCabcdef1234567890`\n"
                "Знайти: відкрийте канал → About → Share → Copy channel ID"
            ); return
        display_name = args[0]
        channel_id   = args[1]
        if not channel_id.startswith("UC"):
            await ctx.reply(
                "⚠️ Channel ID має починатись з `UC`\n"
                "Наприклад: `UCabcdef1234567890`"
            ); return
        # Перевірка дублікату
        if any(s["channel_id"] == channel_id for s in streamers_data["youtube"]):
            await ctx.reply(f"ℹ️ YouTube канал **{display_name}** вже є в списку."); return
        streamers_data["youtube"].append({
            "name": display_name, "channel_id": channel_id, "last_video": ""
        })
        save_streamers()
        await ctx.reply(
            f"✅ Додано YouTube канал **{display_name}**\n"
            f"ID: `{channel_id}`\n"
            f"Сповіщення будуть у <#{_notify_ch(ctx.guild).id if _notify_ch(ctx.guild) else 'стріми'}>"
        )

    elif platform == "twitch":
        if len(args) < 1:
            await ctx.reply("⚠️ Формат: `!addstreamer twitch нік_на_твічі`"); return
        login = args[0].lower().lstrip("@")
        if any(s["name"].lower() == login for s in streamers_data["twitch"]):
            await ctx.reply(f"ℹ️ Twitch **{login}** вже є в списку."); return
        streamers_data["twitch"].append({"name": login, "last_live": False})
        save_streamers()
        tw_ok = bool(TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET)
        warn  = "" if tw_ok else "\n⚠️ Twitch API не налаштований! Додайте `TWITCH_CLIENT_ID` і `TWITCH_CLIENT_SECRET` у Variables."
        await ctx.reply(f"✅ Додано Twitch стрімера **{login}**{warn}")

    elif platform == "tiktok":
        if len(args) < 1:
            await ctx.reply("⚠️ Формат: `!addstreamer tiktok @нік`"); return
        nick = args[0].lstrip("@")
        if any(s["name"] == nick for s in streamers_data["tiktok"]):
            await ctx.reply(f"ℹ️ TikTok **@{nick}** вже є в списку."); return
        streamers_data["tiktok"].append({"name": nick, "last_video": ""})
        save_streamers()
        await ctx.reply(
            f"✅ Додано TikTok **@{nick}**\n"
            "⚠️ TikTok використовує сторонній RSS — може бути нестабільним."
        )
    print(f"[+] Стрімер додано: {platform} — {args}")


@bot.command(name="removestreamer")
async def cmd_remove_streamer(ctx, platform: str, *, name: str):
    """!removestreamer youtube/twitch/tiktok НазваАбоНік"""
    if not ctx.author.guild_permissions.administrator and not discord.utils.find(
            lambda r: any(k in r.name for k in ("Адмін","Суддя")), ctx.author.roles):
        await ctx.reply("❌ Тільки адмін.", delete_after=6); return

    platform = platform.lower()
    name_clean = name.lower().lstrip("@")
    original_count = len(streamers_data.get(platform, []))

    streamers_data[platform] = [
        s for s in streamers_data.get(platform, [])
        if s.get("name","").lower() != name_clean
        and s.get("channel_id","").lower() != name_clean
    ]

    if len(streamers_data[platform]) < original_count:
        save_streamers()
        await ctx.reply(f"🗑️ **{name}** видалено зі списку {platform}.")
    else:
        await ctx.reply(f"❌ **{name}** не знайдено в списку {platform}.")


@bot.command(name="streamers")
async def cmd_list_streamers(ctx):
    """!streamers — список всіх доданих стрімерів"""
    embed = discord.Embed(
        title="📡 Список стрімерів для сповіщень",
        color=discord.Color.from_rgb(88, 101, 242)
    )

    yt = streamers_data.get("youtube", [])
    tw = streamers_data.get("twitch", [])
    tt = streamers_data.get("tiktok", [])

    if yt:
        lines = [f"▶️ **{s['name']}** (`{s['channel_id']}`)" for s in yt]
        embed.add_field(name=f"🔴 YouTube ({len(yt)})", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="🔴 YouTube", value="*немає*", inline=False)

    if tw:
        lines = [f"🟢 **{s['name']}**" + (" (LIVE)" if s.get("last_live") else "") for s in tw]
        embed.add_field(name=f"🟣 Twitch ({len(tw)})", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="🟣 Twitch", value="*немає*", inline=False)

    if tt:
        lines = [f"🎵 **@{s['name']}**" for s in tt]
        embed.add_field(name=f"⚫ TikTok ({len(tt)})", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="⚫ TikTok", value="*немає*", inline=False)

    ch = _notify_ch(ctx.guild)
    embed.set_footer(text=f"Канал сповіщень: #{ch.name if ch else NOTIFY_CHANNEL_NAME} • перевірка кожні {CHECK_INTERVAL//60} хв")
    await ctx.reply(embed=embed)


@bot.command(name="checkstreams")
async def cmd_check_now(ctx):
    """!checkstreams — перевірити всі платформи прямо зараз (адмін)"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.reply("❌ Тільки адмін.", delete_after=5); return
    await ctx.reply("🔄 Перевіряємо всі платформи...")
    await check_youtube()
    await check_twitch()
    await check_tiktok()
    await ctx.reply("✅ Перевірку завершено. Нові сповіщення відправлені якщо є.")


# ═══════════════════════════════════════════════════════════════════════════════
# ЗАПУСК ЦИКЛУ (додати в on_ready після cleanup_loop.start())
# notify_loop.start()
# load_streamers()   ← додати перед bot.run()
# ═══════════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    if not TOKEN:
        print("=" * 50)
        print("  Встановіть змінні середовища:")
        print("  TOKEN    = токен бота")
        print("  GUILD_ID = ID сервера")
        print("  TEAM_SIZE = 3")
        print()
        print("  Railway: Variables → Add Variable")
        print("  Локально: файл .env")
        print("=" * 50)
    else:
        run_keepalive()
        print("[→] Запуск...")
        bot.run(TOKEN)
