import discord
from discord import app_commands
from discord.ext import commands
import os
import traceback

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def is_admin(interaction: discord.Interaction) -> bool:
    return (
        interaction.user.guild_permissions.administrator
        or interaction.user.id == interaction.guild.owner_id
    )


@bot.event
async def on_ready():
    print(f"[起動] Bot名: {bot.user}")
    print(f"[起動] 参加サーバー数: {len(bot.guilds)}")

    if not bot.guilds:
        print("[エラー] サーバーにBotが追加されていません。URLから招待し直してください。")
        return

    # 参加している全サーバーに対して個別にコマンドを登録
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=discord.Object(id=guild.id))
            synced = await bot.tree.sync(guild=discord.Object(id=guild.id))
            print(f"[成功] サーバー「{guild.name}」(ID:{guild.id}) にコマンドを {len(synced)} 個登録完了")
            for cmd in synced:
                print(f"       - /{cmd.name}")
        except Exception as e:
            print(f"[失敗] サーバー「{guild.name}」でコマンド登録エラー: {e}")
            traceback.print_exc()

    print("[完了] 起動処理終了。Discord側に反映されるまで2～3分待ってください。")


@app_commands.command(name="disable-mention", description="指定ロールの@everyoneメンション・外部アプリ使用を強制OFF")
@app_commands.describe(role="権限をOFFにするロールを選択")
async def disable_mention(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ このコマンドは管理者のみ使用可能です。", ephemeral=True)
        return

    new_perms = role.permissions.copy()
    new_perms.update(mention_everyone=False, use_external_apps=False)

    try:
        await role.edit(permissions=new_perms, reason=f"/disable-mention by {interaction.user}")
        await interaction.response.send_message(
            f"✅ **{role.mention}** の権限を制限しました。\n"
            "@everyoneメンション: OFF\n"
            "外部アプリ使用: OFF"
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ 失敗: {e}", ephemeral=True)


@app_commands.command(name="enable-mention", description="指定ロールの@everyoneメンション・外部アプリ使用をONに戻す")
@app_commands.describe(role="権限をONに戻すロールを選択")
async def enable_mention(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ このコマンドは管理者のみ使用可能です。", ephemeral=True)
        return

    new_perms = role.permissions.copy()
    new_perms.update(mention_everyone=True, use_external_apps=True)

    try:
        await role.edit(permissions=new_perms, reason=f"/enable-mention by {interaction.user}")
        await interaction.response.send_message(
            f"✅ **{role.mention}** の権限を復元しました。\n"
            "@everyoneメンション: ON\n"
            "外部アプリ使用: ON"
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ 失敗: {e}", ephemeral=True)


TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("環境変数 DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)