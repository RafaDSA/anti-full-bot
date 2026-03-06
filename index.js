require("dotenv").config();
const { Client, GatewayIntentBits, Events } = require("discord.js");

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildVoiceStates
  ]
});

const ALLOWED_ROLES = [
  "498466121075392533",   // Fonda
  "1234631516982612052"   // Co-Fonda
];

client.once(Events.ClientReady, () => {
  console.log(`Bot connecté : ${client.user.tag}`);
});

client.on("voiceStateUpdate", async (oldState, newState) => {
  try {
    if (!newState.channel) return;
    if (oldState.channelId === newState.channelId) return;

    const member = newState.member;
    const channel = newState.channel;

    if (!member) return;

    const isAllowed = member.roles.cache.some(role =>
      ALLOWED_ROLES.includes(role.id)
    );

    if (isAllowed) {
      console.log(`${member.user.tag} ignoré (Fonda/Co-Fonda)`);
      return;
    }

    if (channel.userLimit > 0 && channel.members.size > channel.userLimit) {
      await member.voice.setChannel(null, "Salon plein");
      console.log(`${member.user.tag} déconnecté (salon plein)`);
    }
  } catch (err) {
    console.error("Erreur :", err);
  }
});

client.login(process.env.TOKEN);