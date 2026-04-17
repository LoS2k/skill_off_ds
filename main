"""
SkillOFF and KO — Discord Bot v3 (Cloud Edition)
==================================================
Готовий до деплою на Railway / Render / VPS

Змінні середовища (Environment Variables):
  TOKEN     — токен бота з Discord Developer Portal
  GUILD_ID  — ID вашого сервера
  TEAM_SIZE — розмір команди: 3, 5 або 7 (за замовчуванням 3)

Функції:
  • Кнопки ролей у каналі верифікації (Гравець/Капітан/Глядач/Стрімер)
  • Красиве привітання нових учасників + ЛС
  • Стрімер-команди: !match !score !map !poll !winner !gg !mvp !bracket
  • Реєстрація: !register + авто-роль Капітана
  • Тимчасові голосові кімнати
  • Збереження команд між перезапусками
  • Keep-alive HTTP сервер (для Render безкоштовного плану)
"""

import discord
from discord.ext import commands
from discord.ui import Button, View
import asyncio, os, json
from datetime import datetime
from dotenv import load_dotenv

# Завантажуємо .env якщо є (локальний запуск)
load_dotenv()

# ─── Конфігурація з Environment Variables ───────────────────────────────────
TOKEN     = os.getenv("TOKEN", "")
GUILD_ID  = int(os.getenv("GUILD_ID", "0"))
TEAM_SIZE = int(os.getenv("TEAM_SIZE", "3"))

# Назви каналів (мають збігатися з вашим сервером)
CH_WELCOME  = "glory-to-ukraine"    # привітання нових
CH_VERIFY   = "верифікація"         # кнопки ролей
CH_ANNOUNCE = "оголошення"          # стрімер-оголошення
CH_RESULTS  = "live-результати"     # рахунки матчів
CH_BRACKET  = "розклад"             # сітка турніру
# ─────────────────────────────────────────────────────────────────────────────

TRIGGER_VC   = "Створити кімнату"
DATA_FILE    = "teams_data.json"

registered_teams: dict[str, list[str]] = {}
temp_rooms:       dict[int, discord.Member] = {}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# ═══════════════════════════════════════════════════════════════════════════════
# Keep-alive для Render (безкоштовний план потребує HTTP пінгу)
# ═══════════════════════════════════════════════════════════════════════════════
def run_keepalive():
    """Запускає мінімальний HTTP сервер щоб Render не усипляв бота."""
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive!")
        def log_message(self, *a): pass  # тиша в логах

    def _serve():
        port = int(os.getenv("PORT", "8080"))
        HTTPServer(("0.0.0.0", port), _H).serve_forever()

    threading.Thread(target=_serve, daemon=True).start()
    print(f"[✓] Keep-alive HTTP запущено")


# ═══════════════════════════════════════════════════════════════════════════════
# Збереження команд
# ═══════════════════════════════════════════════════════════════════════════════
def save_teams():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(registered_teams, f, ensure_ascii=False, indent=2)

def load_teams():
    global registered_teams
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            registered_teams = json.load(f)
        print(f"[✓] Завантажено {len(registered_teams)} команд")


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW: Кнопки вибору ролі
# ═══════════════════════════════════════════════════════════════════════════════
class RoleView(View):
    def __init__(self):
        super().__init__(timeout=None)  # кнопки не зникають ніколи

    async def _assign(self, interaction: discord.Interaction, keyword: str):
        role = discord.utils.find(
            lambda r: keyword.lower() in r.name.lower(),
            interaction.guild.roles
        )
        if not role:
            await interaction.response.send_message(
                f"⚠️ Роль «{keyword}» не знайдена. Зверніться до адміна.",
                ephemeral=True); return

        if role in interaction.user.roles:
            await interaction.response.send_message(
                f"ℹ️ У вас вже є роль **{role.name}**!", ephemeral=True); return

        try:
            await interaction.user.add_roles(role)
            # Відповідь бачить тільки сам гравець
            await interaction.response.send_message(
                f"✅ Роль **{role.name}** видано!\n"
                f"Тепер у вас є доступ до відповідних каналів сервера.",
                ephemeral=True)
            print(f"[+] Роль {role.name} → {interaction.user.display_name}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ Бот не може видати роль — переконайтесь що роль бота "
                "вища за ролі гравців у списку ролей сервера.",
                ephemeral=True)

    @discord.ui.button(label="🎮 Гравець",  style=discord.ButtonStyle.primary,   custom_id="rv_player")
    async def b_player(self, i, b):   await self._assign(i, "Гравець")

    @discord.ui.button(label="🎖️ Капітан", style=discord.ButtonStyle.success,   custom_id="rv_captain")
    async def b_captain(self, i, b):  await self._assign(i, "Капітан")

    @discord.ui.button(label="👁️ Глядач",  style=discord.ButtonStyle.secondary,  custom_id="rv_viewer")
    async def b_viewer(self, i, b):   await self._assign(i, "Глядач")

    @discord.ui.button(label="🎙️ Стрімер", style=discord.ButtonStyle.danger,     custom_id="rv_streamer")
    async def b_streamer(self, i, b): await self._assign(i, "Стрімер")


# ═══════════════════════════════════════════════════════════════════════════════
# СТАРТ
# ═══════════════════════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    load_teams()
    bot.add_view(RoleView())   # відновлюємо кнопки після перезапуску

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print(f"[!] Сервер {GUILD_ID} не знайдено!"); return

    print(f"[✓] Бот: {bot.user}  |  Сервер: {guild.name}  |  {TEAM_SIZE}v{TEAM_SIZE}")
    await _post_role_buttons(guild)
    print("[✓] Бот готовий!")


async def _post_role_buttons(guild: discord.Guild):
    """Розміщує embed з кнопками ролей. Якщо вже є — не дублює."""
    ch = _ch(guild, CH_VERIFY) or _ch(guild, "реєстрація") or _ch(guild, "verify")
    if not ch:
        print(f"[!] Канал верифікації не знайдено (очікується «{CH_VERIFY}»)")
        return

    # Перевіряємо чи є вже наше повідомлення
    async for msg in ch.history(limit=30):
        if (msg.author == bot.user and msg.embeds
                and "Оберіть свою роль" in (msg.embeds[0].title or "")):
            print(f"[=] Кнопки ролей вже є в #{ch.name}"); return

    embed = discord.Embed(
        title="🎮 Оберіть свою роль на сервері",
        description=(
            "Натисніть кнопку нижче — роль видається миттєво.\n\n"
            "🎮 **Гравець** — учасник турніру\n"
            "🎖️ **Капітан** — реєструє команду командою `!register`\n"
            "👁️ **Глядач** — слідкує за турніром\n"
            "🎙️ **Стрімер** — стрімить турнір, доступ до стрімер-команд\n\n"
            "*Роль можна змінити — просто натисніть іншу кнопку*"
        ),
        color=discord.Color.from_rgb(88, 101, 242)
    )
    embed.set_footer(text="SkillOFF and KO • Tank Company Tournament")
    embed.timestamp = datetime.now()
    await ch.send(embed=embed, view=RoleView())
    print(f"[+] Кнопки ролей розміщено в #{ch.name}")


# ═══════════════════════════════════════════════════════════════════════════════
# ПРИВІТАННЯ
# ═══════════════════════════════════════════════════════════════════════════════
@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    ch = _ch(guild, CH_WELCOME) or _ch(guild, "welcome") or _ch(guild, "загальний")

    if ch:
        verify_ch = _ch(guild, CH_VERIFY) or _ch(guild, "реєстрація")
        verify_mention = verify_ch.mention if verify_ch else "#верифікація"

        embed = discord.Embed(
            title=f"👋 {member.display_name} приєднався!",
            description=(
                f"Ласкаво просимо на **{guild.name}**! 🎮\n\n"
                f"**Що робити далі:**\n"
                f"1️⃣ Перейди в {verify_mention} та обери роль\n"
                f"2️⃣ Слідкуй за `#оголошення` — там всі новини\n"
                f"3️⃣ Капітани — реєструйте команду: `!register`\n\n"
                f"Удачі в боях, {member.mention}! ⚔️"
            ),
            color=discord.Color.from_rgb(29, 185, 84)
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Учасник #{guild.member_count} • SkillOFF and KO")
        embed.timestamp = datetime.now()
        await ch.send(embed=embed)

    # ЛС новому учаснику
    try:
        dm = discord.Embed(
            title=f"🏆 Ласкаво просимо на {guild.name}!",
            description=(
                f"Привіт, **{member.display_name}**! 👋\n\n"
                f"Ти зайшов на сервер турніру **Tank Company**.\n\n"
                f"**Швидкий старт:**\n"
                f"• Обери роль кнопкою в каналі верифікації\n"
                f"• Якщо граєш — капітан команди пише `!register`\n"
                f"• Питання? Пиши в загальний чат або адміну\n\n"
                f"*Бажаємо перемог!* 🥇"
            ),
            color=discord.Color.from_rgb(88, 101, 242)
        )
        dm.set_footer(text="SkillOFF and KO")
        await member.send(embed=dm)
    except discord.Forbidden:
        pass  # ЛС закриті — ок

    print(f"[+] Новий: {member.display_name}")


# ═══════════════════════════════════════════════════════════════════════════════
# СТРІМЕР-КОМАНДИ
# ═══════════════════════════════════════════════════════════════════════════════
def _is_staff(ctx):
    return (ctx.author.guild_permissions.administrator or
            discord.utils.find(
                lambda r: any(k in r.name for k in ("Адмін","Стрімер","Суддя")),
                ctx.author.roles))

def _ch(guild, name):
    return discord.utils.find(lambda c: name.lower() in c.name.lower(), guild.text_channels)

async def _send_to(ctx, ch_name, content=None, embed=None, mention=None):
    """Відправляє в потрібний канал, видаляє оригінал."""
    ch = _ch(ctx.guild, ch_name) or ctx.channel
    if mention:
        await ch.send(mention, embed=embed)
    elif embed:
        await ch.send(embed=embed)
    else:
        await ch.send(content)
    if ch != ctx.channel:
        try: await ctx.message.delete()
        except: pass


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
    embed = discord.Embed(
        title="📊 Рахунок матчу",
        description=f"# {args}",
        color=discord.Color.from_rgb(88, 101, 242)
    )
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_RESULTS, embed=embed)


@bot.command(name="map")
async def cmd_map(ctx, *, map_name: str):
    """!map НазваМапи"""
    if not _is_staff(ctx): return
    embed = discord.Embed(
        title="🗺️ Поточна мапа",
        description=f"**{map_name}**",
        color=discord.Color.from_rgb(0, 150, 200)
    )
    embed.set_footer(text="Tank Company Tournament")
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_ANNOUNCE, embed=embed)


@bot.command(name="winner")
async def cmd_winner(ctx, *, team: str):
    """!winner НазваКоманди"""
    if not _is_staff(ctx): return
    embed = discord.Embed(
        title="🥇 ПЕРЕМОЖЕЦЬ ТУРНІРУ!",
        description=f"# 🏆 {team} 🏆\n\nВітаємо з перемогою! 🎉🎊🎉",
        color=discord.Color.gold()
    )
    embed.set_footer(text="Tank Company Tournament • SkillOFF and KO")
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_ANNOUNCE, embed=embed, mention="@everyone 🎉")


@bot.command(name="gg")
async def cmd_gg(ctx):
    """!gg — GG WP після матчу"""
    if not _is_staff(ctx): return
    embed = discord.Embed(
        title="🏆 GG WP — Матч завершено!",
        description="Дякуємо всім гравцям за гру!\nРезультати будуть оголошені незабаром.",
        color=discord.Color.gold()
    )
    embed.set_footer(text="Tank Company Tournament • SkillOFF and KO")
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_ANNOUNCE, embed=embed)


@bot.command(name="mvp")
async def cmd_mvp(ctx, member: discord.Member, *, reason: str = ""):
    """!mvp @гравець Причина — оголосити MVP матчу"""
    if not _is_staff(ctx): return
    embed = discord.Embed(
        title="⭐ MVP Матчу!",
        description=(
            f"# {member.mention}\n\n"
            f"{reason if reason else 'За видатну гру!'}"
        ),
        color=discord.Color.from_rgb(255, 215, 0)
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Tank Company Tournament")
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_ANNOUNCE, embed=embed)


@bot.command(name="poll")
async def cmd_poll(ctx, *, args: str):
    """!poll Питання | Варіант1 | Варіант2 | ..."""
    if not _is_staff(ctx): return
    parts = [p.strip() for p in args.split("|")]
    if len(parts) < 3:
        await ctx.reply("⚠️ Формат: `!poll Питання | Варіант1 | Варіант2`", delete_after=8)
        return
    question = parts[0]; options = parts[1:10]
    nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    embed = discord.Embed(
        title=f"📊 {question}",
        description="\n".join(f"{nums[i]} **{o}**" for i,o in enumerate(options)),
        color=discord.Color.from_rgb(230, 126, 34)
    )
    embed.set_footer(text="Проголосуйте реакцією нижче")
    embed.timestamp = datetime.now()
    ch = _ch(ctx.guild, CH_ANNOUNCE) or ctx.channel
    msg = await ch.send(embed=embed)
    for i in range(len(options)):
        await msg.add_reaction(nums[i])
    if ch != ctx.channel:
        try: await ctx.message.delete()
        except: pass


@bot.command(name="bracket")
async def cmd_bracket(ctx, *, info: str):
    """!bracket Текст — опублікувати інфо про сітку"""
    if not _is_staff(ctx): return
    embed = discord.Embed(
        title="🔱 Турнірна сітка",
        description=info,
        color=discord.Color.from_rgb(155, 89, 182)
    )
    embed.set_footer(text="Tank Company Tournament • SkillOFF and KO")
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_BRACKET, embed=embed, mention="@everyone")


@bot.command(name="announce")
async def cmd_announce(ctx, *, text: str):
    """!announce Текст — звичайне оголошення від адміна"""
    if not _is_staff(ctx): return
    embed = discord.Embed(
        description=text,
        color=discord.Color.from_rgb(52, 152, 219)
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.timestamp = datetime.now()
    await _send_to(ctx, CH_ANNOUNCE, embed=embed, mention="@everyone")


# ═══════════════════════════════════════════════════════════════════════════════
# РЕЄСТРАЦІЯ КОМАНД
# ═══════════════════════════════════════════════════════════════════════════════
@bot.command(name="register")
async def cmd_register(ctx):
    """!register НазваКоманди, Гравець1, Гравець2, ..."""
    raw   = ctx.message.content[len("!register"):].strip()
    parts = [p.strip() for p in raw.split(",") if p.strip()]

    if len(parts) < 2:
        await ctx.reply(
            f"⚠️ **Формат:** `!register НазваКоманди, Гравець1, ...`\n"
            f"Для {TEAM_SIZE}v{TEAM_SIZE} потрібно {TEAM_SIZE} гравці."
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
            ctx.guild.members
        )
        if m and pl:
            try:
                await m.add_roles(pl)
                pl_lines.append(f"  ✅ {m.mention}")
            except:
                pl_lines.append(f"  ⚠️ {pname}")
        else:
            pl_lines.append(f"  ❓ **{pname}** — не на сервері")

    pl_block = ("\n👥 Гравці:\n" + "\n".join(pl_lines)) if pl_lines else ""
    await ctx.reply(
        f"✅ Команду **{name}** зареєстровано!\n"
        f"👥 Склад: {', '.join(players)}"
        f"{cap_line}{pl_block}"
    )
    print(f"[+] Команда: {name} ({players})")


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
# ТИМЧАСОВІ ГОЛОСОВІ КІМНАТИ
# ═══════════════════════════════════════════════════════════════════════════════
@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild

    if after.channel and TRIGGER_VC in after.channel.name:
        cat  = after.channel.category
        name = f"🔒 {member.display_name}"
        for r in reversed(member.roles):
            clean = r.name.replace("🎖️ ","").replace("👑 ","").replace("⚖️ ","").replace("🎙️ ","")
            if clean and r.name not in ("@everyone","👁️ Глядач","🎮 Гравець","🎙️ Стрімер"):
                name = f"🔒 {clean}"; break
        ow = {
            guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True),
            member: discord.PermissionOverwrite(
                connect=True, speak=True, manage_channels=True, move_members=True),
        }
        adm = discord.utils.find(lambda r: "Адмін" in r.name, guild.roles)
        if adm: ow[adm] = discord.PermissionOverwrite(connect=True, speak=True, manage_channels=True)
        ch = await guild.create_voice_channel(
            name=name, category=cat, overwrites=ow, user_limit=TEAM_SIZE * 2)
        temp_rooms[ch.id] = member
        try: await member.move_to(ch)
        except: pass

    if before.channel and before.channel.id in temp_rooms:
        if len(before.channel.members) == 0:
            temp_rooms.pop(before.channel.id, None)
            try: await before.channel.delete()
            except: pass


def _room(m):
    if not m.voice or not m.voice.channel: return None
    return m.voice.channel if m.voice.channel.id in temp_rooms else None

@bot.command(name="lock")
async def c_lock(ctx):
    r=_room(ctx.author)
    if not r: await ctx.reply("❌ Не у своїй кімнаті.",delete_after=5); return
    await r.set_permissions(ctx.guild.default_role,connect=False,view_channel=True)
    await ctx.reply(f"🔒 **{r.name}** закрито.",delete_after=6)

@bot.command(name="unlock")
async def c_unlock(ctx):
    r=_room(ctx.author)
    if not r: await ctx.reply("❌ Не у своїй кімнаті.",delete_after=5); return
    await r.set_permissions(ctx.guild.default_role,connect=True,view_channel=True)
    await ctx.reply(f"🔓 **{r.name}** відкрито.",delete_after=6)

@bot.command(name="rename")
async def c_rename(ctx, *, name: str):
    r=_room(ctx.author)
    if not r: await ctx.reply("❌ Не у своїй кімнаті.",delete_after=5); return
    await r.edit(name=f"🔒 {name}")
    await ctx.reply(f"✏️ → **🔒 {name}**",delete_after=8)

@bot.command(name="limit")
async def c_limit(ctx, n: int):
    r=_room(ctx.author)
    if not r: await ctx.reply("❌ Не у своїй кімнаті.",delete_after=5); return
    await r.edit(user_limit=max(1,min(n,99)))
    await ctx.reply(f"👥 Ліміт: **{n}**",delete_after=5)

@bot.command(name="permit")
async def c_permit(ctx, member: discord.Member):
    r=_room(ctx.author)
    if not r: await ctx.reply("❌ Не у своїй кімнаті.",delete_after=5); return
    await r.set_permissions(member,connect=True,speak=True)
    await ctx.reply(f"✅ **{member.display_name}** може зайти.",delete_after=8)

@bot.command(name="kick_voice")
async def c_kick(ctx, member: discord.Member):
    r=_room(ctx.author)
    if not r or member not in r.members:
        await ctx.reply("❌ Гравець не у вашій кімнаті.",delete_after=5); return
    await member.move_to(None)
    await r.set_permissions(member,connect=False)
    await ctx.reply(f"👢 **{member.display_name}** вигнано.",delete_after=8)


# ═══════════════════════════════════════════════════════════════════════════════
# !help
# ═══════════════════════════════════════════════════════════════════════════════
@bot.command(name="help")
async def cmd_help(ctx):
    embed = discord.Embed(
        title="🤖 SkillOFF Bot — Команди",
        color=discord.Color.from_rgb(88,101,242)
    )
    embed.add_field(name="📝 Реєстрація", inline=False, value=(
        f"`!register Назва, Гравець1, ...` — {TEAM_SIZE} гравці\n"
        "`!standings` — список команд\n"
        "`!unregister Назва` — видалити (адмін)"
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
        "`!gg` — GG WP"
    ))
    embed.add_field(name="🔊 Голосова кімната", inline=False, value=(
        "`!lock` `!unlock` `!rename Назва`\n"
        f"`!limit {TEAM_SIZE}` `!permit @гравець` `!kick_voice @гравець`"
    ))
    embed.add_field(name="👑 Адмін", inline=False, value=(
        "`!give_role @гравець НазваРолі`"
    ))
    embed.set_footer(text="SkillOFF and KO • Tank Company Tournament")
    await ctx.reply(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not TOKEN:
        print("=" * 55)
        print("  Встановіть змінні середовища:")
        print("  TOKEN    = токен бота")
        print("  GUILD_ID = ID сервера")
        print()
        print("  Локально: заповніть файл .env")
        print("  Railway:  Variables → Add Variable")
        print("  Render:   Environment → Add Environment Variable")
        print("=" * 55)
    else:
        run_keepalive()   # для Render
        print("[→] Запускаємо бота...")
        bot.run(TOKEN)
