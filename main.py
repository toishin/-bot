import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def is_admin(ctx: commands.Context) -> bool:
    """管理者かどうかを判定：administrator権限 または サーバーオーナー のみ許可"""
    if not ctx.guild:
        return False  # DMでは実行不可
    return (
        ctx.author.guild_permissions.administrator
        or ctx.author.id == ctx.guild.owner_id
    )


# コマンド用チェックデコレータ：これをつけたコマンドは管理者以外エラーになる
admin_only = commands.check(is_admin)


async def find_single_target(ctx: commands.Context, query: str):
    query = query.strip()
    if not query:
        return None

    if query.lower() == "all":
        return ("all", None)

    if query.lower() in ("everyone", "@everyone"):
        return ("roles", [ctx.guild.default_role])

    if query.startswith("<@") and query.endswith(">"):
        try:
            uid = int(query.lstrip("<@!").rstrip(">"))
            member = ctx.guild.get_member(uid)
            if member:
                roles = [r for r in member.roles if r != ctx.guild.default_role]
                return ("roles", roles)
        except ValueError:
            pass

    if query.startswith("<@&") and query.endswith(">"):
        try:
            rid = int(query[3:-1])
            r = ctx.guild.get_role(rid)
            return ("roles", [r]) if r else None
        except ValueError:
            pass

    if query.isdigit():
        try:
            n = int(query)
            r = ctx.guild.get_role(n)
            if r:
                return ("roles", [r])
            m = ctx.guild.get_member(n)
            if m:
                roles = [r for r in m.roles if r != ctx.guild.default_role]
                return ("roles", roles)
        except ValueError:
            pass

    q = query.lower()
    for r in ctx.guild.roles:
        if r.name.lower() == q:
            return ("roles", [r])
    for m in ctx.guild.members:
        if m.display_name.lower() == q or m.name.lower() == q:
            roles = [r for r in m.roles if r != ctx.guild.default_role]
            return ("roles", roles)
    for r in ctx.guild.roles:
        if q in r.name.lower():
            return ("roles", [r])
    for m in ctx.guild.members:
        if q in m.display_name.lower() or q in m.name.lower():
            roles = [r for r in m.roles if r != ctx.guild.default_role]
            return ("roles", roles)

    return None


async def resolve_targets(ctx: commands.Context, args_str: str):
    tokens = [t.strip() for t in args_str.replace(",", " ").split() if t.strip()]
    if not tokens:
        return [], "引数がありません。"

    result_roles = []
    messages = []

    for tok in tokens:
        resolved = await find_single_target(ctx, tok)
        if resolved is None:
            messages.append(f"❌ `{tok}` が見つかりません")
            continue

        kind, data = resolved
        if kind == "all":
            everyone_flag = "--everyone" in args_str.lower()
            all_roles = list(ctx.guild.roles)
            if not everyone_flag:
                all_roles = [r for r in all_roles if r != ctx.guild.default_role]
            result_roles.extend(all_roles)
            messages.append(f"📋 `all` → 全{len(all_roles)}ロールを対象" + ("（@everyone含む）" if everyone_flag else ""))
        else:
            result_roles.extend(data)
            names = ", ".join(r.name for r in data)
            messages.append(f"✅ `{tok}` → {names}")

    seen = set()
    unique = []
    for r in result_roles:
        if r.id not in seen:
            seen.add(r.id)
            unique.append(r)

    return unique, "\n".join(messages)


@bot.event
async def on_ready():
    print(f"[起動] Bot名: {bot.user}")
    print(f"[起動] 参加サーバー数: {len(bot.guilds)}")
    print("[完了] 準備完了。 !disable / !enable は管理者のみ使用可能です。")


async def run_batch(ctx: commands.Context, args_str: str, *, disable: bool):
    # 【二重チェック】デコレータで弾かれるはずだが、保険としてここでも再度確認
    if not is_admin(ctx):
        await ctx.reply("⛔ この操作はサーバー管理者のみ実行可能です。", delete_after=10)
        return

    roles, info = await resolve_targets(ctx, args_str)
    header = f"🔍 対象解決結果（{len(roles)}個）:\n{info}"

    if not roles:
        await ctx.reply(header + "\n\n❌ 操作するロールが1つもありません。")
        return

    success = []
    failed = []

    for role in roles:
        new_perms = discord.Permissions(role.permissions.value)
        new_perms.update(
            mention_everyone=(not disable),
            use_external_apps=(not disable)
        )
        try:
            label = "disable" if disable else "enable"
            await role.edit(permissions=new_perms, reason=f"!{label} by {ctx.author} (管理者実行)")
            success.append(role)
        except discord.Forbidden:
            failed.append((role, "Botの権限不足（Bot自身のロールを対象ロールより上に移動してください）"))
        except Exception as e:
            failed.append((role, str(e)))

    mode = "🔒 制限（OFF）" if disable else "🔓 復元（ON）"
    lines = [f"## {mode} 実行結果（実行者: {ctx.author.display_name}）", ""]
    lines.append(f"対象ロール数: {len(roles)} / 成功: {len(success)} / 失敗: {len(failed)}")
    lines.append("")
    if success:
        lines.append("### ✅ 成功")
        lines.append(", ".join(r.mention for r in success))
        lines.append("")
    if failed:
        lines.append("### ❌ 失敗")
        for r, reason in failed:
            lines.append(f"- {r.mention}: {reason}")

    await ctx.reply("\n".join(lines))


# 各コマンドに @admin_only を付ける → 管理者以外はそもそも起動しない
@bot.command(name="disable", help="【管理者専用】ロール/メンバー/all をまとめて権限制限")
@admin_only
async def disable_cmd(ctx: commands.Context, *, args: str):
    await run_batch(ctx, args, disable=True)


@bot.command(name="enable", help="【管理者専用】ロール/メンバー/all をまとめて権限復元")
@admin_only
async def enable_cmd(ctx: commands.Context, *, args: str):
    await run_batch(ctx, args, disable=False)


# 管理者権限が無い場合のエラーを親切に表示
@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.reply("⛔ このコマンドはサーバー管理者のみ使用可能です。権限がありません。", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(
            "❌ 使い方（管理者のみ）:\n"
            "・複数ロール: `!disable ロールA ロールB`\n"
            "・メンバー指定: `!disable @ユーザー`\n"
            "・全ロール: `!disable all`\n"
            "・@everyoneも含む: `!disable all --everyone`"
        )
    else:
        await ctx.reply(f"❌ エラー: {error}")


TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("環境変数 DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)