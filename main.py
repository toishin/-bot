import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def is_admin(ctx: commands.Context) -> bool:
    if not ctx.guild:
        return False
    return (
        ctx.author.guild_permissions.administrator
        or ctx.author.id == ctx.guild.owner_id
    )


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
    # フラグを除去したトークンを作成
    raw_tokens = [t.strip() for t in args_str.replace(",", " ").split() if t.strip()]
    flags = {t.lower() for t in raw_tokens if t.startswith("--")}
    tokens = [t for t in raw_tokens if not t.startswith("--")]

    if not tokens:
        return [], flags, "引数がありません。"

    result_roles = []
    messages = []

    for tok in tokens:
        resolved = await find_single_target(ctx, tok)
        if resolved is None:
            messages.append(f"❌ `{tok}` が見つかりません")
            continue
        kind, data = resolved
        if kind == "all":
            everyone_flag = "--everyone" in flags
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

    return unique, flags, "\n".join(messages)


async def overwrite_channel_perms(guild: discord.Guild, roles: list[discord.Role], *, disable: bool, force_deny: bool):
    """全チャンネル・カテゴリの権限上書きを修正"""
    modified = []
    failed = []

    # 対象とする全チャンネル（カテゴリ + テキスト + スレッド親）
    targets = []
    for category in guild.categories:
        targets.append(category)
    for channel in guild.text_channels:
        targets.append(channel)
    for channel in guild.voice_channels:
        targets.append(channel)

    for ch in targets:
        for role in roles:
            overwrite = ch.overwrites_for(role)
            changed = False

            # mention_everyone
            if disable:
                # OFFにしたい → 上書きで許可(True)になっているものを修正
                if overwrite.mention_everyone is True:
                    overwrite.mention_everyone = False if force_deny else None
                    changed = True
                if overwrite.use_external_apps is True:
                    overwrite.use_external_apps = False if force_deny else None
                    changed = True
            else:
                # ONにしたい → 上書きで拒否(False)になっているものを中立に戻す
                if overwrite.mention_everyone is False:
                    overwrite.mention_everyone = None
                    changed = True
                if overwrite.use_external_apps is False:
                    overwrite.use_external_apps = None
                    changed = True

            if changed:
                try:
                    await ch.set_permissions(role, overwrite=overwrite, reason=f"権限一括修正 by Bot")
                    modified.append(f"{ch.mention} / {role.name}")
                except Exception as e:
                    failed.append(f"{ch.mention} / {role.name}: {e}")

    return modified, failed


@bot.event
async def on_ready():
    print(f"[起動] Bot名: {bot.user}")
    print(f"[起動] 参加サーバー数: {len(bot.guilds)}")
    print("[完了] 準備完了。!disable / !enable は管理者のみ使用可能。")


async def run_batch(ctx: commands.Context, args_str: str, *, disable: bool):
    if not is_admin(ctx):
        await ctx.reply("⛔ サーバー管理者のみ実行可能です。", delete_after=10)
        return

    roles, flags, info = await resolve_targets(ctx, args_str)
    deep = "--deep" in flags
    force_deny = "--deny" in flags

    header = f"🔍 対象解決結果（{len(roles)}個）:\n{info}"
    if deep:
        header += "\n⚡ --deep: チャンネル個別の権限上書きも修正します"
    if force_deny and disable:
        header += "\n🛑 --deny: チャンネル上書きを「許可」→「拒否」に強制変更します"

    if not roles:
        await ctx.reply(header + "\n\n❌ 操作するロールが1つもありません。")
        return

    # 1. ロールの基本権限を変更
    success_role = []
    failed_role = []

    for role in roles:
        new_perms = discord.Permissions(role.permissions.value)
        new_perms.update(
            mention_everyone=(not disable),
            use_external_apps=(not disable)
        )
        try:
            label = "disable" if disable else "enable"
            await role.edit(permissions=new_perms, reason=f"!{label} by {ctx.author}")
            success_role.append(role)
        except discord.Forbidden:
            failed_role.append((role, "Botの権限不足（ロールの順番を確認）"))
        except Exception as e:
            failed_role.append((role, str(e)))

    # 2. --deep があればチャンネル上書きも修正
    ch_modified = []
    ch_failed = []
    if deep:
        ch_modified, ch_failed = await overwrite_channel_perms(
            ctx.guild, roles, disable=disable, force_deny=force_deny
        )

    # 結果表示
    mode = "🔒 制限（OFF）" if disable else "🔓 復元（ON）"
    lines = [f"## {mode} 実行結果（実行者: {ctx.author.display_name}）", ""]
    lines.append(f"対象ロール数: {len(roles)} / 基本権限 成功:{len(success_role)} 失敗:{len(failed_role)}")
    if deep:
        lines.append(f"チャンネル上書き 修正:{len(ch_modified)}件 / 失敗:{len(ch_failed)}件")
    lines.append("")

    if success_role:
        lines.append("### ✅ 基本権限 成功")
        lines.append(", ".join(r.mention for r in success_role))
        lines.append("")
    if failed_role:
        lines.append("### ❌ 基本権限 失敗")
        for r, reason in failed_role:
            lines.append(f"- {r.mention}: {reason}")
        lines.append("")
    if deep and ch_modified:
        lines.append("### ⚡ チャンネル上書き 修正完了")
        lines.append(f"計 {len(ch_modified)} 件のチャンネル×ロールの組み合わせを修正")
        if len(ch_modified) <= 20:
            for m in ch_modified:
                lines.append(f"- {m}")
        else:
            lines.append("（件数が多いため一覧省略）")
        lines.append("")
    if deep and ch_failed:
        lines.append("### ❌ チャンネル上書き 失敗")
        for f in ch_failed[:30]:
            lines.append(f"- {f}")
        lines.append("")

    await ctx.reply("\n".join(lines))


@bot.command(name="disable", help="【管理者専用】ロールの権限を一括OFF。--deepでチャンネル上書きも修正")
@admin_only
async def disable_cmd(ctx: commands.Context, *, args: str):
    await run_batch(ctx, args, disable=True)


@bot.command(name="enable", help="【管理者専用】ロールの権限を一括ON。--deepでチャンネル上書きも戻す")
@admin_only
async def enable_cmd(ctx: commands.Context, *, args: str):
    await run_batch(ctx, args, disable=False)


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.reply("⛔ このコマンドはサーバー管理者のみ使用可能です。", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(
            "❌ 使い方（管理者のみ）:\n"
            "・基本: `!disable ロールA ロールB`\n"
            "・メンバー指定: `!disable @ユーザー`\n"
            "・全ロール: `!disable all`\n"
            "・@everyone含む: `!disable all --everyone`\n"
            "・チャンネル上書きも修正: `!disable everyone --deep`\n"
            "・更に強制拒否: `!disable everyone --deep --deny`"
        )
    else:
        await ctx.reply(f"❌ エラー: {error}")


TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("環境変数 DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)