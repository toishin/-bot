import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# コマンドの接頭辞を ! にする
bot = commands.Bot(command_prefix="!", intents=intents)


def is_admin(ctx: commands.Context) -> bool:
    return ctx.author.guild_permissions.administrator or ctx.author.id == ctx.guild.owner_id


@bot.event
async def on_ready():
    print(f"[起動] Bot名: {bot.user}")
    print(f"[起動] 参加サーバー数: {len(bot.guilds)}")
    print("[完了] 準備完了。 !disable @ロール / !enable @ロール が使えます。")


@bot.command(name="disable", help="指定ロールの@everyoneメンション・外部アプリ使用をOFF")
async def disable_perms(ctx: commands.Context, role: discord.Role):
    if not is_admin(ctx):
        await ctx.reply("❌ このコマンドは管理者のみ使用可能です。")
        return

    new_perms = role.permissions.copy()
    new_perms.update(mention_everyone=False, use_external_apps=False)

    try:
        await role.edit(permissions=new_perms, reason=f"!disable by {ctx.author}")
        await ctx.reply(
            f"✅ **{role.mention}** の権限を制限しました。\n"
            "@everyoneメンション: OFF\n"
            "外部アプリ使用: OFF"
        )
    except Exception as e:
        await ctx.reply(f"❌ 失敗: {e}")


@bot.command(name="enable", help="指定ロールの@everyoneメンション・外部アプリ使用をON")
async def enable_perms(ctx: commands.Context, role: discord.Role):
    if not is_admin(ctx):
        await ctx.reply("❌ このコマンドは管理者のみ使用可能です。")
        return

    new_perms = role.permissions.copy()
    new_perms.update(mention_everyone=True, use_external_apps=True)

    try:
        await role.edit(permissions=new_perms, reason=f"!enable by {ctx.author}")
        await ctx.reply(
            f"✅ **{role.mention}** の権限を復元しました。\n"
            "@everyoneメンション: ON\n"
            "外部アプリ使用: ON"
        )
    except Exception as e:
        await ctx.reply(f"❌ 失敗: {e}")


# コマンドのエラー処理（ロールを指定しなかった場合など）
@disable_perms.error
@enable_perms.error
async def cmd_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("❌ 使い方: `!disable @ロール` または `!enable @ロール`")
    elif isinstance(error, commands.RoleNotFound):
        await ctx.reply("❌ ロールが見つかりません。@でロールを指定してください。")
    else:
        await ctx.reply(f"❌ エラー: {error}")


TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("環境変数 DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)