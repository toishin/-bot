import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def is_admin(ctx: commands.Context) -> bool:
    return ctx.author.guild_permissions.administrator or ctx.author.id == ctx.guild.owner_id


async def find_role(ctx: commands.Context, query: str) -> discord.Role | None:
    """ロールを柔軟に検索する"""
    query = query.strip()

    # 1. everyone キーワード
    if query.lower() in ("everyone", "@everyone"):
        return ctx.guild.default_role

    # 2. メンション形式 <@&12345> からIDを抽出
    if query.startswith("<@&") and query.endswith(">"):
        try:
            role_id = int(query[3:-1])
            return ctx.guild.get_role(role_id)
        except ValueError:
            pass

    # 3. 数字のみならロールIDとして扱う
    if query.isdigit():
        try:
            return ctx.guild.get_role(int(query))
        except ValueError:
            pass

    # 4. 名前で部分一致検索
    query_lower = query.lower()
    for role in ctx.guild.roles:
        if role.name.lower() == query_lower:
            return role
    for role in ctx.guild.roles:
        if query_lower in role.name.lower():
            return role

    return None


@bot.event
async def on_ready():
    print(f"[起動] Bot名: {bot.user}")
    print(f"[起動] 参加サーバー数: {len(bot.guilds)}")
    print("[完了] 準備完了。 !disable <ロール> / !enable <ロール> が使えます。")


@bot.command(name="disable", help="指定ロールの@everyoneメンション・外部アプリ使用をOFF")
async def disable_perms(ctx: commands.Context, *, role_query: str):
    if not is_admin(ctx):
        await ctx.reply("❌ このコマンドは管理者のみ使用可能です。")
        return

    role = await find_role(ctx, role_query)
    if not role:
        await ctx.reply(
            "❌ ロールが見つかりません。次の方法で指定してください。\n"
            "・メンション: `!disable @ロール名`\n"
            "・ID: `!disable 123456789`\n"
            "・名前: `!disable 認証済み`\n"
            "・everyone: `!disable everyone`"
        )
        return

    # 権限オブジェクトを新規作成（copy()不使用）
    new_perms = discord.Permissions(role.permissions.value)
    new_perms.update(mention_everyone=False, use_external_apps=False)

    try:
        await role.edit(permissions=new_perms, reason=f"!disable by {ctx.author}")
        await ctx.reply(
            f"✅ **{role.mention}** の権限を制限しました。\n"
            "@everyoneメンション: OFF\n"
            "外部アプリ使用: OFF"
        )
    except discord.Forbidden:
        await ctx.reply(
            "❌ 権限が不足しています。次を確認してください。\n"
            "1. Botに「ロールの管理」権限があるか\n"
            "2. Bot自身のロールが、編集したいロールより**上**にあるか（サーバー設定→ロールで順番を変更）"
        )
    except Exception as e:
        await ctx.reply(f"❌ 失敗: {e}")


@bot.command(name="enable", help="指定ロールの@everyoneメンション・外部アプリ使用をON")
async def enable_perms(ctx: commands.Context, *, role_query: str):
    if not is_admin(ctx):
        await ctx.reply("❌ このコマンドは管理者のみ使用可能です。")
        return

    role = await find_role(ctx, role_query)
    if not role:
        await ctx.reply(
            "❌ ロールが見つかりません。次の方法で指定してください。\n"
            "・メンション: `!enable @ロール名`\n"
            "・ID: `!enable 123456789`\n"
            "・名前: `!enable 認証済み`\n"
            "・everyone: `!enable everyone`"
        )
        return

    new_perms = discord.Permissions(role.permissions.value)
    new_perms.update(mention_everyone=True, use_external_apps=True)

    try:
        await role.edit(permissions=new_perms, reason=f"!enable by {ctx.author}")
        await ctx.reply(
            f"✅ **{role.mention}** の権限を復元しました。\n"
            "@everyoneメンション: ON\n"
            "外部アプリ使用: ON"
        )
    except discord.Forbidden:
        await ctx.reply(
            "❌ 権限が不足しています。次を確認してください。\n"
            "1. Botに「ロールの管理」権限があるか\n"
            "2. Bot自身のロールが、編集したいロールより**上**にあるか（サーバー設定→ロールで順番を変更）"
        )
    except Exception as e:
        await ctx.reply(f"❌ 失敗: {e}")


@disable_perms.error
@enable_perms.error
async def cmd_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(
            "❌ 使い方: `!disable <ロール>` または `!enable <ロール>`\n"
            "例: `!disable everyone` / `!enable @メンバー` / `!disable 認証済み`"
        )
    else:
        await ctx.reply(f"❌ エラー: {error}")


TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("環境変数 DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)