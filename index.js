require("dotenv").config();
const { Client, GatewayIntentBits } = require("discord.js");

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildVoiceStates
  ]
});

client.once("ready", () => {
  console.log(`Bot connecté : ${client.user.tag}`);
});

client.on("voiceStateUpdate", async (oldState, newState) => {

  if (!newState.channel) return;

  const channel = newState.channel;

  if (channel.userLimit > 0 && channel.members.size > channel.userLimit) {

    const member = newState.member;

    try {
      await member.voice.disconnect();
      console.log(`${member.user.tag} a été déconnecté (salon plein)`);
    } catch (err) {
      console.log("Erreur :", err);
    }

  }

});

client.login(process.env.TOKEN);