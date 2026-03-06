require("dotenv").config();
const { Client, GatewayIntentBits, Events } = require("discord.js");

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildVoiceStates
  ]
});

// ROLES QUI NE SERONT JAMAIS DECONNECTÉS
const ALLOWED_ROLES = [
  "498466121075392533",
  "1234631516982612052"
];

client.once(Events.ClientReady, () => {
  console.log(`Bot connecté : ${client.user.tag}`);
});

client.on("voiceStateUpdate", async (oldState, newState) => {

  if (!newState.channel) return;

  const member = newState.member;

  // ignore fonda / co-fonda
  if (member.roles.cache.some(role => ALLOWED_ROLES.includes(role.id))) {
    return;
  }

  const channel = newState.channel;

  if (channel.userLimit > 0 && channel.members.size > channel.userLimit) {

    try {
      await member.voice.disconnect();
      console.log(`${member.user.tag} déconnecté (salon plein)`);
    } catch (err) {
      console.log("Erreur :", err);
    }

  }

});

client.login(process.env.TOKEN);