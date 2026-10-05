import os
import time
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord
from discord.ext import commands, tasks


# --- SERVEUR HTTP (nécessaire pour Render "Web Service") ---
# Render exige que l'app écoute sur le port fourni via la variable PORT
# pour considérer le service comme "en ligne" (healthcheck).
#
# IMPORTANT : ce healthcheck doit refléter l'état RÉEL du bot, pas juste
# "le thread HTTP répond". Sinon, si l'event loop du bot se fige (ex: un
# appel réseau bloqué indéfiniment), Render continue de voir un 200 OK
# en continu et ne redémarre jamais le service, alors que le bot est mort
# côté Discord. On expose donc un timestamp "last_alive" mis à jour
# régulièrement par la boucle anti-AFK et par on_ready ; si ce timestamp
# est trop vieux, le healthcheck renvoie une erreur 503.
last_alive = time.time()
STALE_THRESHOLD = 120  # secondes sans activité = on considère le bot figé

def mark_alive():
    global last_alive
    last_alive = time.time()

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        age = time.time() - last_alive
        is_stale = age > STALE_THRESHOLD
        is_discord_connected = bot.is_ready() and not bot.is_closed()

        if is_stale or not is_discord_connected:
            self.send_response(503)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(
                f"Bot unhealthy (stale={is_stale}, discord_connected={is_discord_connected}, age={age:.0f}s)".encode()
            )
        else:
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot is alive")

    def log_message(self, format, *args):
        # Evite de spammer les logs Render à chaque requête de healthcheck
        pass

def run_health_server():
    port = int(os.getenv("PORT", 3000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"🌐 Serveur healthcheck démarré sur le port {port}")
    server.serve_forever()

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# IDs Discord
JOIN_TO_CREATE_ID = 1521679861234536519
CATEGORY_ID = 567096279629299724

# IDs des rôles à exclure du système anti-AFK
EXCLUDED_ROLE_IDS = {
    498466121075392533,   # Fonda
    1234631516982612052,  # Co fonda
    563113152510951459,   # Staff
}

# Rôles autorisés à entrer dans un salon plein (issu de index.js : ALLOWED_ROLES)
ALLOWED_OVERFLOW_ROLE_IDS = {
    498466121075392533,   # Fonda
    1234631516982612052,  # Co fonda
}

# Passe à True pour voir dans les logs quels rôles sont vus pour chaque membre
DEBUG_ROLES = False

SUPERSCRIPTS = {
    1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵",
    6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹", 0: "⁰"
}

def get_superscript(number: int) -> str:
    return "".join(SUPERSCRIPTS[int(d)] for d in str(number))

def has_excluded_role(member) -> bool:
    role_ids = {role.id for role in member.roles}
    excluded = bool(role_ids & EXCLUDED_ROLE_IDS)
    if DEBUG_ROLES:
        print(f"[AFK-DEBUG] {member.display_name} rôles vus: {sorted(role_ids)}")
    if excluded:
        print(f"[AFK] {member.display_name} exclu (rôles trouvés: {role_ids & EXCLUDED_ROLE_IDS})")
    return excluded

def has_allowed_overflow_role(member) -> bool:
    role_ids = {role.id for role in member.roles}
    return bool(role_ids & ALLOWED_OVERFLOW_ROLE_IDS)

# Dictionnaires pour suivre les temps
muted_users = {}
deafened_users = {}
alone_users = {}

# Seul en vocal -> 15 min (900 secondes)
ALONE_TIMEOUT = 900

@bot.event
async def on_ready():
    mark_alive()
    print(f"✅ Bot connecté sous {bot.user}")
    # on_ready peut être redéclenché après une reconnexion complète au Gateway.
    # is_running() protège déjà contre les doublons dans la plupart des cas,
    # mais on force explicitement l'arrêt de toute instance existante avant
    # de relancer, pour éviter que plusieurs boucles tournent en parallèle.
    if check_afk_timeouts.is_running():
        check_afk_timeouts.cancel()
    check_afk_timeouts.start()

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    # 1. Création du salon Trio
    if after.channel and after.channel.id == JOIN_TO_CREATE_ID:
        guild = member.guild
        category = guild.get_channel(CATEGORY_ID)

        existing_numbers = set()
        for channel in guild.voice_channels:
            if channel.name.startswith("🦎 ᵀʳⁱᵒ"):
                parts = channel.name.split()
                if parts:
                    last_part = parts[-1]
                    num_str = ""
                    for char in last_part:
                        for k, v in SUPERSCRIPTS.items():
                            if v == char:
                                num_str += str(k)
                    if num_str.isdigit():
                        existing_numbers.add(int(num_str))

        next_number = 1
        while next_number in existing_numbers:
            next_number += 1

        superscript_num = get_superscript(next_number)
        new_channel_name = f"🦎 ᵀʳⁱᵒ {superscript_num}"

        new_channel = await guild.create_voice_channel(
            name=new_channel_name,
            category=category,
            user_limit=3
        )
        try:
            await asyncio.wait_for(member.move_to(new_channel), timeout=10)
        except asyncio.TimeoutError:
            print(f"⏱️ Timeout move_to (création salon Trio) pour {member}")

    # 2. Suppression des salons Trio vides
    if before.channel and before.channel.name.startswith("🦎 ᵀʳⁱᵒ"):
        if len(before.channel.members) == 0:
            await before.channel.delete()

    # 3. Anti salon plein (portage de index.js)
    #    Si le membre vient d'arriver dans un nouveau salon (changement de channel)
    #    et que ce salon a une limite dépassée, on le vire, sauf s'il a un rôle autorisé.
    if after.channel and before.channel != after.channel:
        channel = after.channel
        if not has_allowed_overflow_role(member):
            if channel.user_limit and len(channel.members) > channel.user_limit:
                try:
                    await asyncio.wait_for(member.move_to(None, reason="Salon plein"), timeout=10)
                    print(f"🚪 {member.display_name} déconnecté (salon plein: {channel.name})")
                except asyncio.TimeoutError:
                    print(f"⏱️ Timeout move_to (salon plein) pour {member}")
                except Exception as e:
                    print(f"Erreur déconnexion (salon plein) {member}: {e}")
        else:
            print(f"{member} ignoré pour la vérif salon plein (Fonda/Co-fonda)")


# --- BOUCLE ANTI-AFK ---
@tasks.loop(seconds=15)
async def check_afk_timeouts():
    mark_alive()
    now = time.time()
    active_member_ids = set()

    for guild in bot.guilds:
        for vc in guild.voice_channels:
            members_in_vc = [m for m in vc.members if not m.bot]
            # Vrai si un seul humain (hors bots) est présent dans ce salon
            is_alone_channel = len(members_in_vc) == 1

            for raw_member in members_in_vc:
                voice = raw_member.voice
                if voice is None:
                    continue

                # IMPORTANT : on ne fait PAS confiance au membre issu du cache
                # (guild.get_member / vc.members) pour la vérification des rôles.
                # Ce cache peut être périmé, ce qui faisait que des membres Staff /
                # Fonda / Co-fonda perdaient leur exclusion et se faisaient déco.
                # On récupère donc une version fraîche du membre via l'API avant
                # de trancher, uniquement quand c'est nécessaire (mute/deaf/seul actif).
                is_deafened = voice.self_deaf or voice.deaf
                is_muted = voice.self_mute or voice.mute
                is_alone = is_alone_channel

                if not is_deafened and not is_muted and not is_alone:
                    muted_users.pop(raw_member.id, None)
                    deafened_users.pop(raw_member.id, None)
                    alone_users.pop(raw_member.id, None)
                    continue

                try:
                    member = await asyncio.wait_for(
                        guild.fetch_member(raw_member.id), timeout=10
                    )
                except asyncio.TimeoutError:
                    print(f"⏱️ Timeout fetch_member {raw_member}, on retentera au prochain tick")
                    continue
                except discord.NotFound:
                    # Le membre a quitté le serveur entre-temps
                    muted_users.pop(raw_member.id, None)
                    deafened_users.pop(raw_member.id, None)
                    alone_users.pop(raw_member.id, None)
                    continue
                except discord.HTTPException as e:
                    print(f"Erreur fetch_member {raw_member}: {e}")
                    # On retente au prochain tick, on ne prend pas de décision
                    # sur la base de données potentiellement obsolètes.
                    continue

                # Exclusion des rôles Fonda / Co fonda / Staff
                if has_excluded_role(member):
                    muted_users.pop(member.id, None)
                    deafened_users.pop(member.id, None)
                    alone_users.pop(member.id, None)
                    continue

                active_member_ids.add(member.id)

                # Casque coupé (Sourd) -> 15 min (900 secondes)
                if is_deafened:
                    if member.id not in deafened_users:
                        deafened_users[member.id] = now
                    muted_users.pop(member.id, None)

                    if now - deafened_users[member.id] >= 900:
                        try:
                            await asyncio.wait_for(member.move_to(None), timeout=10)
                            print(f"🎧 {member.display_name} déconnecté (Casque coupé > 15 min)")
                        except asyncio.TimeoutError:
                            print(f"⏱️ Timeout move_to (deaf) pour {member}")
                        except Exception as e:
                            print(f"Erreur déconnexion {member}: {e}")
                        deafened_users.pop(member.id, None)

                # Micro coupé (Mute simple) -> 30 min (1800 secondes)
                elif is_muted:
                    if member.id not in muted_users:
                        muted_users[member.id] = now
                    deafened_users.pop(member.id, None)

                    if now - muted_users[member.id] >= 1800:
                        try:
                            await asyncio.wait_for(member.move_to(None), timeout=10)
                            print(f"🎤 {member.display_name} déconnecté (Micro coupé > 30 min)")
                        except asyncio.TimeoutError:
                            print(f"⏱️ Timeout move_to (mute) pour {member}")
                        except Exception as e:
                            print(f"Erreur déconnexion {member}: {e}")
                        muted_users.pop(member.id, None)

                else:
                    muted_users.pop(member.id, None)
                    deafened_users.pop(member.id, None)

                # Seul en vocal -> 15 min (900 secondes), indépendant du mute/deaf
                if is_alone:
                    if member.id not in alone_users:
                        alone_users[member.id] = now

                    if now - alone_users[member.id] >= ALONE_TIMEOUT:
                        try:
                            await asyncio.wait_for(member.move_to(None), timeout=10)
                            print(f"👤 {member.display_name} déconnecté (Seul en vocal > 15 min)")
                        except asyncio.TimeoutError:
                            print(f"⏱️ Timeout move_to (alone) pour {member}")
                        except Exception as e:
                            print(f"Erreur déconnexion {member}: {e}")
                        alone_users.pop(member.id, None)
                else:
                    alone_users.pop(member.id, None)

    # Nettoyage des membres déconnectés
    for m_id in list(muted_users.keys()):
        if m_id not in active_member_ids:
            muted_users.pop(m_id, None)

    for m_id in list(deafened_users.keys()):
        if m_id not in active_member_ids:
            deafened_users.pop(m_id, None)

    for m_id in list(alone_users.keys()):
        if m_id not in active_member_ids:
            alone_users.pop(m_id, None)

@check_afk_timeouts.before_loop
async def before_check():
    await bot.wait_until_ready()

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    threading.Thread(target=run_health_server, daemon=True).start()
    bot.run(TOKEN)
else:
    print("❌ Erreur : La variable DISCORD_TOKEN n'est pas définie.")
