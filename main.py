import discord
from discord import app_commands
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 管理する権限：@everyoneメンション / 外部アプリを使用
PERM_MENTION_EVERYONE = discord.Permissions.mention_everyone
PERM_USE_EXTERNAL_APPS = discord.Permissions.use_external_apps


def is_admin(interaction: discord.Interaction) -> bool:
    """実行者がサーバー管理者か判定"""
    return interaction.user.guild_permissions.administrator or interaction.user.guild.owner_id == interaction.user.id


@bot.event
async def on_ready():
    await bot.tree.sync()  # スラッシュコマンドを同期
    print(f"✅ Bot起動: {bot.user}")
    print("✅ コマンド: /disable-mention /enable-mention")


@app_commands.command(name="disable-mention", description="指定ロールの@everyoneメンション・外部アプリ使用を強制OFF")
@app_commands.describe(role="権限をOFFにするロールを選択")
async def disable_mention(interaction: discord.Interaction, role: discord.Role):
    # 管理者チェック
    if not is_admin(interaction):
        await interaction.response.send_message(
            "❌ このコマンドは管理者のみ使用可能です。", ephemeral=True
        )
        return

    # 現在の権限を取得
    current_perms = role.permissions
    new_perms = current_perms.copy()

    # 対象権限を強制的にOFF
    new_perms.update(
        mention_everyone=False,
        use_external_apps=False
    )

    # ロールを更新
    try:
        await role.edit(
            permissions=new_perms,
            reason=f"/disable-mention by {interaction.user} (権限制限)"
        )
        await interaction.response.send_message(
            f"✅ **{role.mention}** の権限を制限しました！\n"
            "🔒 @everyoneメンション: ❌ OFF\n"
            "🔒 外部アプリ使用: ❌ OFF",
            ephemeral=False
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ 権限の変更に失敗しました：{e}", ephemeral=True
        )


@app_commands.command(name="enable-mention", description="指定ロールの@everyoneメンション・外部アプリ使用をONに戻す")
@app_commands.describe(role="権限をONに戻すロールを選択")
async def enable_mention(interaction: discord.Interaction, role: discord.Role):
    # 管理者チェック
    if not is_admin(interaction):
        await interaction.response.send_message(
            "❌ このコマンドは管理者のみ使用可能です。", ephemeral=True
        )
        return

    current_perms = role.permissions
    new_perms = current_perms.copy()

    # 対象権限をONに
    new_perms.update(
        mention_everyone=True,
        use_external_apps=True
    )

    try:
        await role.edit(
            permissions=new_perms,
            reason=f"/enable-mention by {interaction.user}"
        )
        await interaction.response.send_message(
            f"✅ **{role.mention}** の権限を復元しました！\n"
            "🔓 @everyoneメンション: ✅ ON\n"
            "🔓 外部アプリ使用: ✅ ON",
            ephemeral=False
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ 権限の変更に失敗しました：{e}", ephemeral=True
        )


TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("環境変数 DISCORD_BOT_TOKEN を設定してください。")

bot.run(TOKEN)