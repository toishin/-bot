import discord
from discord import app_commands
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

PERM_MENTION_EVERYONE = discord.Permissions.mention_everyone
PERM_USE_EXTERNAL_APPS = discord.Permissions.use_external_apps


def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator or interaction.user.guild.owner_id == interaction.user.id


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot起動: {bot.user}")
    print("✅ コマンド: /disable-mention /enable-mention")


@app_commands.command(name="disable-mention", description="指定ロールの@everyoneメンション・外部アプリ使用をOFF")
@app_commands.describe(role="権限をOFFにするロール")
async def disable_mention(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ 管理者のみ使用可能", ephemeral=True)
        return

    perms = role.permissions
    new_perms = perms.copy()
    new_perms.update(mention_everyone=False, use_external_apps=False)

    try:
        await role.edit(permissions=new_perms)
        await interaction.response.send_message(
            f"✅ {role.mention} を制限\n"
            "@everyoneメンション: ❌ OFF\n"
            "外部アプリ使用: ❌ OFF"
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ 失敗: {e}", ephemeral=True)


@app_commands.command(name="enable-mention", description="指定ロールの権限をONに戻す")
@app_commands.describe(role="権限をONに戻すロール")
async def enable_mention(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ 管理者のみ使用可能", ephemeral=True)
        return

    perms = role.permissions
    new_perms = perms.copy()
    new_perms.update(mention_everyone=True, use_external_apps=True)

    try:
        await role.edit(permissions=new_perms)
        await interaction.response.send_message(
            f"✅ {role.mention} を復元\n"
            "@everyoneメンション: ✅ ON\n"
            "外部アプリ使用: ✅ ON"
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ 失敗: {e}", ephemeral=True)


TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN を設定してください")

bot.run(TOKEN)