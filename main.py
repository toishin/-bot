import discord
from discord.ext import commands
import os
import time
import datetime
from collections import defaultdict

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!！", intents=intents)

# ========== 設定 ==========
# 単体スパム
SPAM_WINDOW = 10                 # 秒：監視時間枠
SPAM_THRESHOLD = 5               # 件数：これ以上でスパム判定
TIMEOUT_DURATION = 24 * 60 * 60  # 24時間（秒）

# 複数アカウント 類似メッセージ検知
GROUP_WINDOW = 8                  # 秒：同じメッセージとみなす時間幅
GROUP_SIMILARITY = 0.80           # 類似度 0.0～1.0
GROUP_COUNT = 2                   # 何アカウント以上で発動

# 参加時 複数アカウント予備検知
JOIN_WINDOW_MINUTES = 10
NEW_ACCOUNT_DAYS = 7
NAME_SIMILARITY_THRESHOLD = 0.6

ADMIN_ROLE_NAME = "TISN管理者"
# ==========================

# 履歴
user_message_times = defaultdict(lambda: defaultdict(list))  # gid → uid → [時刻]
recent_messages = defaultdict(list)  # gid → [(正規化本文, uid, メッセージオブジェクト, 時刻)]
banned_user_ids = set()

# ---- 文字列類似度 ----
def normalize_text(text: str) -> str:
    """空白・記号・大文字小文字を統一"""
    t = text.strip().lower()
    t = "".join(c for c in t if c.isalnum() or c in " ")
    return " ".join(t.split())

def calc_similarity(a: str, b: str) -> float:
    """正規化済み文字列の類似度（0.0～1.0）"""
    if a == b:
        return 1.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    max_common = 0
    for i in range(len(shorter)):
        for j in range(i + 1, len(shorter) + 1):
            sub = shorter[i:j]
            l = len(sub)
            if l > max_common and sub in longer:
                max_common = l
    return max_common / max(len(a), len(b), 1)

# ---- 権限チェック ----
def is_admin(ctx: commands.Context) -> bool:
    if not ctx.guild:
        return False
    return (
        ctx.author.guild_permissions.administrator
        or ctx.author.id == ctx.guild.owner_id
        or any(r.name == ADMIN_ROLE_NAME for r in ctx.author.roles)
    )

async def is_tisn_admin(member: discord.Member) -> bool:
    if member.guild_permissions.administrator or member.id == member.guild.owner_id:
        return True
    return any(r.name == ADMIN_ROLE_NAME for r in member.roles)

admin_only = commands.check(is_admin)

# ---- 参加時 名前類似検知 ----
async def find_correlated_members(guild: discord.Guild, new_member: discord.Member):
    now = datetime.datetime.now(datetime.timezone.utc)
    correlated = []
    new_created = new_member.created_at
    new_name = normalize_text(new_member.name)
    new_disp = normalize_text(new_member.display_name)

    async for member in guild.fetch_members(limit=None):
        if member.id == new_member.id:
            continue
        jdiff = abs((member.joined_at - new_member.joined_at).total_seconds()) if member.joined_at else 999999
        cdiff = abs((member.created_at - new_created).total_seconds())
        sim_n = calc_similarity(new_name, normalize_text(member.name))
        sim_d = calc_similarity(new_disp, normalize_text(member.display_name))
        if (
            jdiff < JOIN_WINDOW_MINUTES * 60
            and max(sim_n, sim_d) >= NAME_SIMILARITY_THRESHOLD
            and (now - member.created_at).days < NEW_ACCOUNT_DAYS
            and (now - new_created).days < NEW_ACCOUNT_DAYS
        ):
            correlated.append({
                "member": member,
                "time_diff_min": round(jdiff / 60, 1),
                "similarity": round(max(sim_n, sim_d), 2),
            })
    return correlated

# ---- 操作ボタン：単体スパム ----
class SpamActionView(discord.ui.View):
    def __init__(self, target_member, deleted_messages, duration):
        super().__init__(timeout=None)
        self.member = target_member
        self.deleted = deleted_messages
        self.duration = duration
        self.reason = "スパム送信による自動制限"

    async def interaction_check(self, inter):
        if not await is_tisn_admin(inter.user):
            await inter.response.send_message("⛔ TISN管理者のみ実行可能", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📩 メッセージ復元", style=discord.ButtonStyle.secondary)
    async def restore(self, inter, btn):
        await inter.response.defer()
        ch = inter.channel
        ok, ng = 0, 0
        for m in self.deleted:
            try:
                files = [await a.to_file() for a in m.attachments]
                await ch.send(f"📝 **{self.member.mention} 復元**\n{m.content}", files=files)
                ok += 1
            except:
                ng += 1
        await inter.followup.send(f"✅ 復元 {ok}件 / ❌ {ng}件")

    @discord.ui.button(label="🔓 タイムアウト解除", style=discord.ButtonStyle.success)
    async def untimeout(self, inter, btn):
        try:
            await self.member.edit(timed_out_until=None, reason=f"管理者 {inter.user} による解除")
            await inter.response.send_message(f"✅ {self.member.mention} を解除")
        except Exception as e:
            await inter.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="👢 キック", style=discord.ButtonStyle.primary)
    async def kick(self, inter, btn):
        try:
            await self.member.kick(reason=self.reason)
            await inter.response.send_message(f"✅ {self.member.mention} をキック")
        except Exception as e:
            await inter.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="🔨 BAN", style=discord.ButtonStyle.danger)
    async def ban(self, inter, btn):
        try:
            await self.member.ban(reason=self.reason)
            banned_user_ids.add(self.member.id)
            await inter.response.send_message(f"✅ {self.member.mention} をBAN")
        except Exception as e:
            await inter.response.send_message(f"❌ {e}", ephemeral=True)

# ---- 操作ボタン：グループスパム ----
class GroupSpamView(discord.ui.View):
    def __init__(self, members, deleted_map):
        super().__init__(timeout=None)
        self.members = members
        self.deleted_map = deleted_map  # uid → [メッセージ]
        self.reason = "類似メッセージ一斉送信（スパム）"

    async def interaction_check(self, inter):
        if not await is_tisn_admin(inter.user):
            await inter.response.send_message("⛔ TISN管理者のみ実行可能", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📩 全メッセージ復元", style=discord.ButtonStyle.secondary)
    async def restore_all(self, inter, btn):
        await inter.response.defer()
        ch = inter.channel
        ok, ng = 0, 0
        for msgs in self.deleted_map.values():
            for m in msgs:
                try:
                    files = [await a.to_file() for a in m.attachments]
                    await ch.send(f"📝 **{m.author.mention} 復元**\n{m.content}", files=files)
                    ok += 1
                except:
                    ng += 1
        await inter.followup.send(f"✅ 計{ok}件復元 / ❌{ng}件失敗")

    @discord.ui.button(label="🔓 全員タイムアウト解除", style=discord.ButtonStyle.success)
    async def untimeout_all(self, inter, btn):
        await inter.response.defer()
        done, fail = [], []
        for mem in self.members:
            try:
                await mem.edit(timed_out_until=None, reason=f"管理者 {inter.user} による解除")
                done.append(mem.mention)
            except Exception as e:
                fail.append(f"{mem.mention}: {e}")
        await inter.followup.send(
            ("✅ 解除: " + " ".join(done) if done else "") +
            ("\n❌ 失敗: " + " ".join(fail) if fail else "")
        )

    @discord.ui.button(label="👢 全員キック", style=discord.ButtonStyle.primary)
    async def kick_all(self, inter, btn):
        await inter.response.defer()
        done, fail = [], []
        for mem in self.members:
            try:
                await mem.kick(reason=self.reason)
                done.append(mem.mention)
            except Exception as e:
                fail.append(f"{mem.mention}: {e}")
        await inter.followup.send(
            ("✅ キック: " + " ".join(done) if done else "") +
            ("\n❌ 失敗: " + " ".join(fail) if fail else "")
        )

    @discord.ui.button(label="🔨 全員BAN", style=discord.ButtonStyle.danger)
    async def ban_all(self, inter, btn):
        await inter.response.defer()
        done, fail = [], []
        for mem in self.members:
            try:
                await mem.ban(reason=self.reason)
                banned_user_ids.add(mem.id)
                done.append(mem.mention)
            except Exception as e:
                fail.append(f"{mem.mention}: {e}")
        await inter.followup.send(
            ("✅ BAN: " + " ".join(done) if done else "") +
            ("\n❌ 失敗: " + " ".join(fail) if fail else "")
        )

    @discord.ui.button(label="✅ 誤検知として無視", style=discord.ButtonStyle.secondary)
    async def ignore(self, inter, btn):
        await inter.response.send_message("✅ 誤検知として無視されました。")
        self.clear_items()
        await inter.message.edit(view=self)

# ---- 操作ボタン：参加時要注意 ----
class AltJoinView(discord.ui.View):
    def __init__(self, suspects):
        super().__init__(timeout=None)
        self.suspects = suspects

    async def interaction_check(self, inter):
        return await is_tisn_admin(inter.user)

    @discord.ui.button(label="👢 全員キック", style=discord.ButtonStyle.primary)
    async def kick(self, inter, btn):
        await inter.response.defer()
        done, fail = [], []
        for s in self.suspects:
            try:
                await s["member"].kick(reason="複数アカウントの疑い")
                done.append(s["member"].mention)
            except Exception as e:
                fail.append(f"{s['member'].mention}: {e}")
        await inter.followup.send(
            ("✅ キック: " + " ".join(done) if done else "") +
            ("\n❌ 失敗: " + " ".join(fail) if fail else "")
        )

    @discord.ui.button(label="🔨 全員BAN", style=discord.ButtonStyle.danger)
    async def ban(self, inter, btn):
        await inter.response.defer()
        done, fail = [], []
        for s in self.suspects:
            try:
                await s["member"].ban(reason="複数アカウントの疑い")
                banned_user_ids.add(s["member"].id)
                done.append(s["member"].mention)
            except Exception as e:
                fail.append(f"{s['member'].mention}: {e}")
        await inter.followup.send(
            ("✅ BAN: " + " ".join(done) if done else "") +
            ("\n❌ 失敗: " + " ".join(fail) if fail else "")
        )

    @discord.ui.button(label="✅ 誤検知", style=discord.ButtonStyle.secondary)
    async def ignore(self, inter, btn):
        await inter.response.send_message("✅ 無視されました。")
        self.clear_items()
        await inter.message.edit(view=self)

# ---- 個別スパム実行 ----
async def apply_spam_action(channel, members, messages_map):
    """スパム判定時の共通処理：削除＋タイムアウト＋通知"""
    duration_str = f"{TIMEOUT_DURATION // 3600}時間"
    deleted_total = 0
    # メッセージ削除
    for uid, msgs in messages_map.items():
        for m in msgs:
            try:
                await m.delete()
                deleted_total += 1
            except:
                pass
    # タイムアウト
    until = discord.utils.utcnow() + datetime.timedelta(seconds=TIMEOUT_DURATION)
    ok_mem = []
    fail_info = []
    for mem in members:
        try:
            await mem.edit(timed_out_until=until, reason="スパム自動判定")
            ok_mem.append(mem)
        except Exception as e:
            fail_info.append(f"{mem.mention}: {e}")
    # 通知
    if len(members) == 1:
        mem = members[0]
        notify = (
            f"⚠️ **スパム送信を検知**\n"
            f"対象: {mem.mention} (`{mem.id}`)\n"
            f"削除: {deleted_total}件\n"
            f"自動タイムアウト: {duration_str}"
        )
        view = SpamActionView(mem, messages_map[mem.id], TIMEOUT_DURATION)
    else:
        notify = (
            f"⚠️ **【複数アカウント】類似メッセージを検知**\n"
            f"対象: {' '.join(m.mention for m in members)}\n"
            f"アカウント数: {len(members)}\n"
            f"削除: {deleted_total}件\n"
            f"自動タイムアウト: 全員 {duration_str}"
        )
        view = GroupSpamView(members, messages_map)
    if fail_info:
        notify += "\n❌ タイムアウト失敗:\n" + "\n".join(fail_info)
    await channel.send(notify, view=view)

# ---- メイン：メッセージ受信 ----
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return

    now = time.time()
    gid = message.guild.id
    uid = message.author.id
    norm = normalize_text(message.content)

    # ── 1. 単体スパム（同じ人が連投）──
    times = user_message_times[gid][uid]
    times.append(now)
    times[:] = [t for t in times if now - t <= SPAM_WINDOW]
    if len(times) >= SPAM_THRESHOLD:
        # 削除履歴回収
        dels = []
        async for h in message.channel.history(limit=50):
            if h.author.id == uid and (now - h.created_at.timestamp()) <= SPAM_WINDOW:
                dels.append(h)
        await apply_spam_action(message.channel, [message.author], {uid: dels})
        user_message_times[gid][uid].clear()

    # ── 2. 類似メッセージ：複数アカウント検知 ──
    pool = recent_messages[gid]
    # 古いエントリ削除
    pool[:] = [e for e in pool if now - e[3] <= GROUP_WINDOW]
    # 類似度判定
    group_uids = {uid}
    for entry in pool:
        text_e, uid_e, msg_e, t_e = entry
        if uid_e == uid:
            continue
        if calc_similarity(norm, text_e) >= GROUP_SIMILARITY:
            group_uids.add(uid_e)
    # 閾値超えたら一括処理
    if len(group_uids) >= GROUP_COUNT:
        members = []
        del_map = defaultdict(list)
        async for h in message.channel.history(limit=80):
            if (
                h.author.id in group_uids
                and (now - h.created_at.timestamp()) <= GROUP_WINDOW
            ):
                del_map[h.author.id].append(h)
        for uid_g in group_uids:
            m = message.guild.get_member(uid_g)
            if m:
                members.append(m)
        if members:
            await apply_spam_action(message.channel, members, dict(del_map))
        pool.clear()  # 重複発動防止
    else:
        # プールに追加
        if norm:
            pool.append((norm, uid, message, now))

    await bot.process_commands(message)

# ---- 参加時検知 ----
@bot.event
async def on_member_join(member):
    if member.bot:
        return
    guild = member.guild
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    correlated = await find_correlated_members(guild, member)
    age_days = (now_dt - member.created_at).days

    uid_str = str(member.id)
    banned_like = any(
        uid_str.startswith(str(b)[:6]) or str(b).startswith(uid_str[:6])
        for b in banned_user_ids
    )

    if age_days < NEW_ACCOUNT_DAYS or correlated or banned_like:
        lines = [
            "⚠️ **要注意：新規参加アカウントの特徴**",
            f"対象: {member.mention} (`{member.id}`)",
            f"アカウント年齢: {age_days}日",
            f"作成: {member.created_at.strftime('%Y-%m-%d %H:%M')}"
        ]
        if banned_like:
            lines.append("🚨 IDパターンがBAN済みに類似")
        if correlated:
            lines.append(f"\n🔗 名前/参加時間が類似: {len(correlated)}人")
            for c in correlated:
                lines.append(f"- {c['member'].mention} 類似度:{c['similarity']}")
        suspects = [{"member": member}] + correlated
        view = AltJoinView(suspects) if len(suspects) > 0 else None
        log_ch = discord.utils.get(guild.text_channels, name="ログ") or guild.text_channels[0]
        await log_ch.send("\n".join(lines), view=view)

# ---- 以下 既存コマンド類（変更なし） ----
async def find_single_target(ctx, query: str):
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

async def resolve_targets(ctx, args_str: str):
    raw_tokens = [t.strip() for t in args_str.replace(",", " ").split() if t.strip()]
    flags = {t.lower() for t in raw_tokens if t.startswith("--")}
    tokens = [t for t in raw_tokens if not t.startswith("--")]
    if not tokens:
        return [], flags, "引数がありません。"
    result_roles, messages = [], []
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
            messages.append(f"📋 `all` → 全{len(all_roles)}ロール" + ("（@everyone含む）" if everyone_flag else ""))
        else:
            result_roles.extend(data)
            messages.append(f"✅ `{tok}` → {', '.join(r.name for r in data)}")
    seen, unique = set(), []
    for r in result_roles:
        if r.id not in seen:
            seen.add(r.id)
            unique.append(r)
    return unique, flags, "\n".join(messages)

async def overwrite_channel_perms(guild, roles, *, disable, force_deny):
    modified, failed = [], []
    targets = guild.categories + guild.text_channels + guild.voice_channels
    for ch in targets:
        for role in roles:
            overwrite = ch.overwrites_for(role)
            changed = False
            if disable:
                if overwrite.mention_everyone is True:
                    overwrite.mention_everyone = False if force_deny else None
                    changed = True
                if overwrite.use_external_apps is True:
                    overwrite.use_external_apps = False if force_deny else None
                    changed = True
            else:
                if overwrite.mention_everyone is False:
                    overwrite.mention_everyone = None
                    changed = True
                if overwrite.use_external_apps is False:
                    overwrite.use_external_apps = None
                    changed = True
            if changed:
                try:
                    await ch.set_permissions(role, overwrite=overwrite, reason="権限一括修正")
                    modified.append(f"{ch.mention} / {role.name}")
                except Exception as e:
                    failed.append(f"{ch.mention} / {role.name}: {e}")
    return modified, failed

async def run_batch(ctx, args_str, *, disable):
    if not is_admin(ctx):
        await ctx.reply("⛔ サーバー管理者のみ実行可能です。", delete_after=10)
        return
    roles, flags, info = await resolve_targets(ctx, args_str)
    deep, force_deny = "--deep" in flags, "--deny" in flags
    header = f"🔍 対象解決結果（{len(roles)}個）:\n{info}"
    if deep:
        header += "\n⚡ --deep: チャンネル個別上書きも修正"
    if force_deny and disable:
        header += "\n🛑 --deny: 許可→拒否に強制"
    if not roles:
        await ctx.reply(header + "\n\n❌ 操作するロールがありません。")
        return
    success_role, failed_role = [], []
    for role in roles:
        new_perms = discord.Permissions(role.permissions.value)
        new_perms.update(mention_everyone=(not disable), use_external_apps=(not disable))
        try:
            label = "disable" if disable else "enable"
            await role.edit(permissions=new_perms, reason=f"!{label} by {ctx.author}")
            success_role.append(role)
        except discord.Forbidden:
            failed_role.append((role, "Botの権限不足（ロールの順番を確認）"))
        except Exception as e:
            failed_role.append((role, str(e)))
    ch_modified, ch_failed = [], []
    if deep:
        ch_modified, ch_failed = await overwrite_channel_perms(ctx.guild, roles, disable=disable, force_deny=force_deny)
    mode = "🔒 制限（OFF）" if disable else "🔓 復元（ON）"
    lines = [f"## {mode} 実行結果（実行者: {ctx.author.display_name}）", ""]
    lines.append(f"対象ロール数: {len(roles)} / 基本権限 成功:{len(success_role)} 失敗:{len(failed_role)}")
    if deep:
        lines.append(f"チャンネル上書き 修正:{len(ch_modified)}件 / 失敗:{len(ch_failed)}件")
    lines.append("")
    if success_role:
        lines.extend(["### ✅ 基本権限 成功", ", ".join(r.mention for r in success_role), ""])
    if failed_role:
        lines.append("### ❌ 基本権限 失敗")
        for r, reason in failed_role:
            lines.append(f"- {r.mention}: {reason}")
        lines.append("")
    if deep and ch_modified:
        lines.append("### ⚡ チャンネル上書き 修正完了")
        lines.append(f"計 {len(ch_modified)} 件を修正" + ("（一覧省略）" if len(ch_modified) > 20 else ""))
        lines.append("")
    if deep and ch_failed:
        lines.append("### ❌ チャンネル上書き 失敗")
        for f in ch_failed[:30]:
            lines.append(f"- {f}")
    await ctx.reply("\n".join(lines))

@bot.event
async def on_ready():
    print(f"[起動] Bot名: {bot.user}")
    print(f"[起動] 参加サーバー数: {len(bot.guilds)}")
    print("[完了] 準備完了")

@bot.command(name="disable", help="管理者専用: ロール権限一括OFF --deepでチャンネル上書きも修正")
@admin_only
async def disable_cmd(ctx, *, args: str):
    await run_batch(ctx, args, disable=True)

@bot.command(name="enable", help="管理者専用: ロール権限一括ON --deepで復元")
@admin_only
async def enable_cmd(ctx, *, args: str):
    await run_batch(ctx, args, disable=False)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.reply("⛔ このコマンドはサーバー管理者のみ使用可能です。", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(
            "❌ 引数が必要です。例:\n"
            "`!disable @ユーザー` / `!disable all --deep` / `!disable all --deep --everyone --deny`"
        )
    else:
        await ctx.reply(f"❌ エラー: {error}")

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("環境変数 DISCORD_BOT_TOKEN が設定されていません。")
bot.run(TOKEN)