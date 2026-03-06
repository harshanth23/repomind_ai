import asyncio
import os
import sys
import re
import requests
from functools import partial
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from utils.fuzzy_match import fuzzy_match_all
from utils.llm import interpret_command
from database.db import DatabaseManager

SERVER_URL = f"http://localhost:{os.getenv('SERVER_PORT', 8000)}"
db = DatabaseManager()
ALLOWED_ROOT = os.path.normcase(os.path.normpath('D:\\'))


def _is_allowed_path(path: str) -> bool:
    if not path:
        return False
    try:
        normalized = os.path.normcase(os.path.normpath(path))
        return normalized.startswith(ALLOWED_ROOT)
    except Exception:
        return False

# ─── Path Registry ────────────────────────────────────────────────────────────
# Telegram callback_data max = 64 bytes, so we store paths in bot_data by index
_path_counter = 0

def _register_path(bot_data: dict, path: str) -> int:
    global _path_counter
    registry = bot_data.setdefault('paths', {})
    for idx, p in registry.items():
        if p == path:
            return idx
    _path_counter += 1
    registry[_path_counter] = path
    return _path_counter

def _get_path(bot_data: dict, idx: int) -> str:
    return bot_data.get('paths', {}).get(idx, '')

# ─── Markdown Escape Helper ─────────────────────────────────────────────────
def _esc(text: str) -> str:
    """Escape Markdown v1 special characters in dynamic text (names, paths)."""
    for ch in ['_', '*', '[', '`']:
        text = text.replace(ch, f'\\{ch}')
    return text

# ─── API Helper ───────────────────────────────────────────────────────────────
def _call_api_sync(method: str, endpoint: str, payload: dict = None, timeout: int = 180) -> dict:
    url = f"{SERVER_URL}{endpoint}"
    resp = requests.get(url, timeout=timeout) if method == 'GET' else requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def call_api(method: str, endpoint: str, payload: dict = None) -> dict:
    """Sync wrapper kept for backward compat."""
    return _call_api_sync(method, endpoint, payload)

async def call_api_async(method: str, endpoint: str, payload: dict = None, timeout: int = 180) -> dict:
    """Non-blocking version — runs the HTTP call in a thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_call_api_sync, method, endpoint, payload, timeout))

# ─── Shared UI Helpers ──────────────────────────────────────────────────────
HOME_BTN = InlineKeyboardButton("🏠 Main Menu", callback_data="mainmenu")

def _main_menu_text():
    return (
        "👋 *RepoMind AI – Main Menu*\n\n"
        "• 📂 Browse Folders – navigate your drive\n"
        "• 📦 GitHub Repos – view & get insights\n"
        "• 🗃️ Analyzed Projects – your history"
    )

def _main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Browse Folders", callback_data="browse_drives")],
        [InlineKeyboardButton("📦 GitHub Repos", callback_data="cmd:repos")],
        [InlineKeyboardButton("🗃️ Analyzed Projects", callback_data="cmd:projects")],
    ])

# ─── Folder Navigation Helpers ────────────────────────────────────────────────
FOLDER_PAGE_SIZE = 8
EMOJI_NUM = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣','7️⃣','8️⃣','9️⃣','🔟']

def _get_subfolders(path: str) -> list:
    try:
        return sorted([
            os.path.join(path, n) for n in os.listdir(path)
            if not n.startswith('.') and not n.startswith('$')
            and os.path.isdir(os.path.join(path, n))
        ])
    except PermissionError:
        return []

def _detect_drive(text: str) -> str | None:
    t = text.lower()
    patterns = [
        r'drive\s+([a-z])', r'go\s+to\s+(?:drive\s+)?([a-z])',
        r'([a-z])\s+drive', r'\b([a-z]):\b', r'\bopen\s+([a-z])\b',
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            drive = m.group(1).upper() + ':\\'
            if drive.upper() == 'D:\\':
                return drive
            return None
    return None

def _build_nav_keyboard(bot_data: dict, path: str, subfolders: list, page: int = 0):
    start = page * FOLDER_PAGE_SIZE
    page_folders = subfolders[start:start + FOLDER_PAGE_SIZE]
    folder_name = os.path.basename(path) or path
    lines = [f"📂 *{_esc(folder_name)}*\n"]
    buttons = []
    for i, fp in enumerate(page_folders):
        name = os.path.basename(fp)
        em = EMOJI_NUM[i] if i < len(EMOJI_NUM) else f"{start+i+1}."
        lines.append(f"{em} {_esc(name)}")
        idx = _register_path(bot_data, fp)
        buttons.append([InlineKeyboardButton(f"{em} {name}", callback_data=f"nav:{idx}")])
    # Pagination
    prow = []
    pidx = _register_path(bot_data, path)
    if page > 0:
        prow.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"navp:{pidx}:{page-1}"))
    if start + FOLDER_PAGE_SIZE < len(subfolders):
        prow.append(InlineKeyboardButton("➡️ Next", callback_data=f"navp:{pidx}:{page+1}"))
    if prow:
        buttons.append(prow)
    # Back
    parent = os.path.dirname(path)
    if parent and parent != path:
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data=f"nav:{_register_path(bot_data, parent)}")])
    # Select current
    buttons.append([InlineKeyboardButton("✅ Select this folder", callback_data=f"select:{pidx}")])
    buttons.append([HOME_BTN])
    text = "\n".join(lines) + "\n\n_Select a subfolder or choose this folder._"
    return text, InlineKeyboardMarkup(buttons)

def _build_action_keyboard(bot_data: dict, path: str):
    idx = _register_path(bot_data, path)
    name = os.path.basename(path) or path
    text = f"📁 *Selected:* `{_esc(path)}`\n\nWhat do you want to do with *{_esc(name)}*?"
    parent = os.path.dirname(path)
    back_target = _register_path(bot_data, parent) if parent and parent != path else None
    buttons = [
        [InlineKeyboardButton("🔍 1️⃣  Analyze", callback_data=f"act:analyze:{idx}")],
        [InlineKeyboardButton("🚀 2️⃣  Push to GitHub", callback_data=f"act:push:{idx}")],
        [InlineKeyboardButton("🗂️ 3️⃣  Show Structure", callback_data=f"act:structure:{idx}")],
    ]
    if back_target is not None:
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data=f"nav:{back_target}")])
    else:
        buttons.append([InlineKeyboardButton("🔙 Back to Drives", callback_data="browse_drives")])
    buttons.append([HOME_BTN])
    return text, InlineKeyboardMarkup(buttons)

# ─── Action Executors ─────────────────────────────────────────────────────────
async def _do_analyze(edit_fn, path: str, bot_data: dict = None, exclude_paths: list = None):
    try:
        payload = {'project_path': path}
        if exclude_paths:
            payload['exclude_paths'] = exclude_paths
        result = await call_api_async('POST', '/analyze', payload, timeout=120)
        scan, analysis, decisions = result['scan'], result['analysis'], result['decisions']
        text = (
            f"✅ *Analysis Complete*\n\n"
            f"📁 *Project:* `{_esc(result['project_name'])}`\n"
            f"💾 *Size:* {scan['total_size_hr']}\n"
            f"📄 *Files:* {scan['total_files']}\n"
            f"🐍 *Python Files:* {analysis['total_python_files']}\n"
            f"📝 *Lines of Code:* {analysis['total_lines_of_code']}\n"
            f"🧠 *Frameworks:* {', '.join(analysis['detected_frameworks']) or 'None'}\n"
            f"📋 *requirements.txt:* {'✅' if analysis['requirements_found'] else '❌'}\n"
            f"🔧 *Git:* {'✅' if analysis['git_initialized'] else '❌'}\n"
            f"🤖 *Model Files:* {len(analysis['model_files'])}\n"
            f"🗂️ *Dataset Folders:* {len(scan['dataset_folders'])}\n"
            f"⚠️ *Large Files:* {len(scan['large_files'])}\n"
        )
        if decisions['warn_large_files']:
            text += f"\n⚠️ {len(decisions['warn_large_files'])} large file(s) detected!\n"

        # Build post-analysis action buttons
        kb = None
        if bot_data is not None:
            idx = _register_path(bot_data, path)
            repo_name = os.path.basename(path).replace(' ', '-').lower()
            parent = os.path.dirname(path)
            back_idx = _register_path(bot_data, parent) if parent and parent != path else None
            rows = [
                [InlineKeyboardButton("🚀 Push to GitHub", callback_data=f"act:push:{idx}")],
                [InlineKeyboardButton("🗂️ Show Structure", callback_data=f"act:structure:{idx}")],
            ]
            if back_idx is not None:
                rows.append([InlineKeyboardButton("🔙 Back", callback_data=f"nav:{back_idx}")])
            else:
                rows.append([InlineKeyboardButton("🔙 Back to Drives", callback_data="browse_drives")])
            rows.append([HOME_BTN])
            kb = InlineKeyboardMarkup(rows)

        await edit_fn(text, parse_mode='Markdown', reply_markup=kb)
    except Exception as e:
        await edit_fn(f"❌ Error: {e}")

async def _do_push(edit_fn, path: str, repo_name: str = None, use_existing: bool = False, exclude_paths: list = None):
    if not repo_name:
        repo_name = os.path.basename(path).replace(' ', '-').lower()
    try:
        await edit_fn(f"🔄 *Preparing push...* _(generating README \& description — may take ~30s)_", parse_mode='Markdown')
        result = await call_api_async('POST', '/push', {
            'project_path': path, 'repo_name': repo_name,
            'commit_message': 'Commit via RepoMind AI',
            'use_existing': use_existing,
            'dataset_links': {p: '' for p in (exclude_paths or [])}
        }, timeout=180)
        url = result.get('url', '')
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open on GitHub", url=url)], [HOME_BTN]])
        await edit_fn(f"✅ *Pushed successfully!*\n🔗 {url}", parse_mode='Markdown', reply_markup=kb)
    except Exception as e:
        kb = InlineKeyboardMarkup([[HOME_BTN]])
        await edit_fn(f"❌ Push failed: {e}", reply_markup=kb)

async def _do_structure(edit_fn, path: str, bot_data: dict = None):
    lines = [f"🗂️ *Structure:* `{_esc(os.path.basename(path))}`\n"]
    count = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        level = dirpath.replace(path, '').count(os.sep)
        if level > 2:
            continue
        indent = '  ' * level
        lines.append(f"{indent}📁 `{os.path.basename(dirpath)}/`")
        for f in filenames[:4]:
            lines.append(f"{indent}  📄 `{f}`")
        if len(filenames) > 4:
            lines.append(f"{indent}  _+{len(filenames)-4} more_")
        count += 1
        if count > 25:
            lines.append("_(truncated)_")
            break

    kb = None
    if bot_data is not None:
        idx = _register_path(bot_data, path)
        parent = os.path.dirname(path)
        back_idx = _register_path(bot_data, parent) if parent and parent != path else None
        rows = [
            [InlineKeyboardButton("🚀 Push to GitHub", callback_data=f"act:push:{idx}")],
            [InlineKeyboardButton("🔍 Analyze", callback_data=f"act:analyze:{idx}")],
        ]
        if back_idx is not None:
            rows.append([InlineKeyboardButton("🔙 Back", callback_data=f"nav:{back_idx}")])
        else:
            rows.append([InlineKeyboardButton("🔙 Back to Drives", callback_data="browse_drives")])
        rows.append([HOME_BTN])
        kb = InlineKeyboardMarkup(rows)

    await edit_fn("\n".join(lines), parse_mode='Markdown', reply_markup=kb)

# ─── Exclusion Picker Helper ─────────────────────────────────────────────────

def _get_subfolders_for_excl(path: str) -> list:
    try:
        return sorted([os.path.join(path, n) for n in os.listdir(path)
            if os.path.isdir(os.path.join(path, n)) and not n.startswith('.') and not n.startswith('$')])
    except Exception:
        return []

def _build_excl_keyboard(bot_data: dict, user_data: dict, mode: str = 'push'):
    """mode = 'push' or 'analyze'"""
    key = 'push_excl' if mode == 'push' else 'analyze_excl'
    toggle_cb = 'excltoggle' if mode == 'push' else 'aexcltoggle'
    go_cb = 'pushgo' if mode == 'push' else 'analyzego'
    go_icon = '🚀 Push Now' if mode == 'push' else '🔍 Analyze Now'

    state = user_data.get(key, {})
    path = state.get('path', '')
    pidx = state.get('pidx', 0)
    label = state.get('repo_name', os.path.basename(path)) if mode == 'push' else os.path.basename(path)
    excluded: set = set(state.get('excluded', []))

    subfolders = _get_subfolders_for_excl(path)
    buttons = []
    for fp in subfolders[:15]:
        name = os.path.basename(fp)
        fidx = _register_path(bot_data, fp)
        icon = "🚫" if fp in excluded else "✅"
        buttons.append([InlineKeyboardButton(f"{icon} {name}", callback_data=f"{toggle_cb}:{fidx}")])

    excl_names = [os.path.basename(p) for p in excluded]
    excl_str = ', '.join(excl_names) if excl_names else 'None'
    n_excl = len(excluded)
    go_label = f"{go_icon} — {n_excl} folder(s) excluded" if n_excl else f"{go_icon} — all folders included"
    buttons.append([InlineKeyboardButton(go_label, callback_data=go_cb)])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data=f"act:{'push' if mode=='push' else 'analyze'}:{pidx}"), HOME_BTN])

    action_word = "push" if mode == 'push' else "analyse"
    text = (
        f"📦 *Choose folders to EXCLUDE from {action_word}:*\n\n"
        f"📁 `{_esc(os.path.basename(path))}`" +
        (f"  →  *{_esc(label)}*" if mode == 'push' else "") + "\n\n"
        f"✅ = included │ 🚫 = excluded \_(tap to toggle)\n\n"
        f"*Excluded:* {_esc(excl_str)}"
    )
    return text, InlineKeyboardMarkup(buttons)

# ─── Drive Browser ────────────────────────────────────────────────────────────
async def _show_drives(reply_fn, bot_data: dict):
    drives = ['D:\\'] if os.path.exists('D:\\') else []
    if not drives:
        await reply_fn("❌ *Drive D:* not found.", parse_mode='Markdown')
        return
    buttons = [[InlineKeyboardButton(f"💾 Drive {d[0]}:", callback_data=f"nav:{_register_path(bot_data, d)}")] for d in drives]
    await reply_fn("💾 *Available Drives:*\n\nSelect a drive to browse:",
                   parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))


# ─── Command Handlers ─────────────────────────────────────────────────────────
async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any ongoing flow and return to main menu."""
    context.user_data.clear()
    await update.message.reply_text(
        _main_menu_text(), parse_mode='Markdown', reply_markup=_main_menu_kb()
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Browse Folders", callback_data="browse_drives")],
        [InlineKeyboardButton("📦 GitHub Repos", callback_data="cmd:repos")],
        [InlineKeyboardButton("🗃️ Analyzed Projects", callback_data="cmd:projects")],
    ])
    await update.message.reply_text(
        "👋 Welcome to *RepoMind AI*!\n\n"
        "I can analyze your local projects and push them to GitHub.\n\n"
        "• Tap *Browse Folders* to navigate your drive step by step\n"
        "• Or type: `Go to Drive D`\n"
        "• Or type `/help` for all commands",
        parse_mode='Markdown', reply_markup=keyboard
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Browse Folders", callback_data="browse_drives")],
        [InlineKeyboardButton("📦 GitHub Repos", callback_data="cmd:repos")],
    ])
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        "🤖 *RepoMind AI – Commands*\n\n"
        "*/browse* – Browse folders interactively\n"
        "*/analyze* `<path>` – Analyze a project\n"
        "*/push* `<path> <repo>` – Push to GitHub\n"
        "*/repos* – List GitHub repos\n"
        "*/projects* – List analyzed projects\n\n"
        "💬 *Or just chat:*\n"
        "`Go to Drive D`\n"
        "`Analyze my drowsiness detection project`\n"
        "`Push D:\\Projects\\MyApp to GitHub`",
        parse_mode='Markdown', reply_markup=keyboard
    )

async def browse_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _show_drives(update.message.reply_text, context.bot_data)

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /analyze <project_path>")
        return
    project_path = ' '.join(context.args)
    if not _is_allowed_path(project_path):
        await update.message.reply_text("❌ Only `D:\\` is allowed.", parse_mode='Markdown')
        return
    msg = await update.message.reply_text(f"🔍 Analyzing...", parse_mode='Markdown')
    await _do_analyze(msg.edit_text, project_path, context.bot_data)

async def push_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /push <project_path> <repo_name>")
        return
    project_path = ' '.join(context.args[:-1])
    if not _is_allowed_path(project_path):
        await update.message.reply_text("❌ Only `D:\\` is allowed.", parse_mode='Markdown')
        return
    msg = await update.message.reply_text("🚀 Pushing...")
    await _do_push(msg.edit_text, project_path, context.args[-1])

async def repos_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_fn = update.message.reply_text if update.message else update.callback_query.edit_message_text
    try:
        repos = await call_api_async('GET', '/repos')
        if not repos:
            await reply_fn("No repositories found.")
            return
        buttons = []
        for r in repos[:20]:
            lock = '🔒' if r.get('private') else '🌐'
            buttons.append([InlineKeyboardButton(
                f"{lock} {r['name']}",
                callback_data=f"repoinfo:{r['name']}"
            )])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="browse_drives")])
        await reply_fn(
            f"*Your GitHub Repositories* ({len(repos)}):\n\nTap a repo to see insights.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        await reply_fn(f"❌ Error: {e}")

async def projects_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    projects = db.get_all_projects()
    reply_fn = update.message.reply_text if update.message else update.callback_query.edit_message_text
    if not projects:
        await reply_fn("No projects analyzed yet. Use /browse or /analyze <path>")
        return
    buttons = [[InlineKeyboardButton(
        f"📁 {p['name']}",
        callback_data=f"select:{_register_path(context.bot_data, p['path'])}"
    )] for p in projects[:10]]
    await reply_fn("🗃️ *Analyzed Projects:*", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

# ─── Button Handler ───────────────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "mainmenu":
        await query.edit_message_text(_main_menu_text(), parse_mode='Markdown', reply_markup=_main_menu_kb())

    elif data == "browse_drives":
        await _show_drives(query.edit_message_text, context.bot_data)

    elif data == "cmd:repos":
        await repos_cmd(update, context)

    elif data.startswith("repoinfo:"):
        repo_name = data.split(":", 1)[1]
        await query.edit_message_text(f"🔄 Loading info for *{_esc(repo_name)}*...", parse_mode='Markdown')
        try:
            r = await call_api_async('GET', f'/repo_info/{repo_name}')
            size_kb = r.get('size', 0)
            size_str = f"{size_kb / 1024:.1f} MB" if size_kb >= 1024 else f"{size_kb} KB"
            pushed = r.get('pushed_at', '')[:10] if r.get('pushed_at') else 'N/A'
            created = r.get('created_at', '')[:10] if r.get('created_at') else 'N/A'
            topics = ', '.join(r.get('topics', [])) or 'None'
            desc = r.get('description') or '_No description_'
            visibility = '🔒 Private' if r.get('private') else '🌐 Public'
            text = (
                f"📊 *Repository Insights*\n\n"
                f"📦 *Name:* {_esc(r.get('name', repo_name))}\n"
                f"📝 *Description:* {_esc(str(desc))}\n"
                f"🔏 *Visibility:* {visibility}\n"
                f"💻 *Language:* {r.get('language') or 'N/A'}\n"
                f"⭐ *Stars:* {r.get('stargazers_count', 0)}\n"
                f"🍴 *Forks:* {r.get('forks_count', 0)}\n"
                f"⚠️ *Open Issues:* {r.get('open_issues_count', 0)}\n"
                f"🌿 *Default Branch:* {r.get('default_branch', 'main')}\n"
                f"📅 *Created:* {created}\n"
                f"🔄 *Last Push:* {pushed}\n"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Open on GitHub", url=r.get('html_url', ''))],
                [InlineKeyboardButton("🔙 Back to Repos", callback_data="cmd:repos")],
                [HOME_BTN],
            ])
            await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)
        except Exception as e:
            await query.edit_message_text(f"❌ Failed to load repo info: {e}",
                reply_markup=InlineKeyboardMarkup([[HOME_BTN]]))

    elif data == "cmd:projects":
        await projects_cmd(update, context)

    elif data.startswith("nav:"):
        idx = int(data.split(":")[1])
        path = _get_path(context.bot_data, idx)
        if not _is_allowed_path(path):
            await query.edit_message_text("❌ Only `D:\\` is allowed.", parse_mode='Markdown')
            return
        if not path or not os.path.isdir(path):
            await query.edit_message_text(f"❌ Path not found: `{path}`", parse_mode='Markdown')
            return
        subfolders = _get_subfolders(path)
        if subfolders:
            text, kb = _build_nav_keyboard(context.bot_data, path, subfolders)
        else:
            text, kb = _build_action_keyboard(context.bot_data, path)
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)

    elif data.startswith("navp:"):
        _, idx_s, page_s = data.split(":")
        path = _get_path(context.bot_data, int(idx_s))
        if not _is_allowed_path(path):
            await query.edit_message_text("❌ Only `D:\\` is allowed.", parse_mode='Markdown')
            return
        text, kb = _build_nav_keyboard(context.bot_data, path, _get_subfolders(path), page=int(page_s))
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)

    elif data.startswith("select:"):
        idx = int(data.split(":")[1])
        path = _get_path(context.bot_data, idx)
        if not _is_allowed_path(path):
            await query.edit_message_text("❌ Only `D:\\` is allowed.", parse_mode='Markdown')
            return
        text, kb = _build_action_keyboard(context.bot_data, path)
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)

    elif data.startswith("act:"):
        _, action, idx_s = data.split(":", 2)
        path = _get_path(context.bot_data, int(idx_s))
        if not _is_allowed_path(path):
            await query.edit_message_text("❌ Only `D:\\` is allowed.", parse_mode='Markdown')
            return
        pidx = int(idx_s)

        if action == "analyze":
            # Show exclusion picker first
            context.user_data['analyze_excl'] = {'path': path, 'pidx': pidx, 'excluded': []}
            text, kb = _build_excl_keyboard(context.bot_data, context.user_data, mode='analyze')
            await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)

        elif action == "push":
            repo_name = os.path.basename(path).replace(' ', '-').lower()
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Create new repo", callback_data=f"pushnew:{pidx}:{repo_name}")],
                [InlineKeyboardButton("📂 Push to existing repo", callback_data=f"pushexist:{pidx}")],
                [InlineKeyboardButton("🔙 Back", callback_data=f"select:{pidx}")],
            ])
            await query.edit_message_text(
                f"🚀 *Push to GitHub*\n\n📁 `{_esc(path)}`\n\nHow do you want to push?",
                parse_mode='Markdown', reply_markup=kb
            )

        elif action == "structure":
            await query.edit_message_text(f"🗂️ Loading structure...", parse_mode='Markdown')
            await _do_structure(query.edit_message_text, path, context.bot_data)

    elif data.startswith("pushnew:"):
        # pushnew:{path_idx}:{suggested_repo_name}
        parts = data.split(":", 2)
        pidx = int(parts[1])
        path = _get_path(context.bot_data, pidx)
        repo_name = parts[2]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Use '{repo_name}'", callback_data=f"pushconfirm:{pidx}:{repo_name}:new")],
            [InlineKeyboardButton("✏️ Type a custom name", callback_data=f"pushtype:{pidx}")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"act:push:{pidx}")],
            [HOME_BTN],
        ])
        await query.edit_message_text(
            f"🚀 *Create New Repo*\n\n📁 `{_esc(path)}`\n📝 Suggested name: *{_esc(repo_name)}*",
            parse_mode='Markdown', reply_markup=kb
        )

    elif data.startswith("pushtype:"):
        pidx = int(data.split(":")[1])
        path = _get_path(context.bot_data, pidx)
        # Store state so text_handler knows what to do next
        context.user_data['awaiting_repo_name'] = {'pidx': pidx, 'path': path}
        await query.edit_message_text(
            f"✏️ *Type your repo name:*\n\n📁 `{_esc(path)}`\n\nSend the repo name as a message.\nType /cancel to go back to Main Menu.",
            parse_mode='Markdown'
        )

    elif data.startswith("pushexist:"):
        pidx = int(data.split(":")[1])
        path = _get_path(context.bot_data, pidx)
        await query.edit_message_text("🔄 Loading your repos...", parse_mode='Markdown')
        try:
            repos = await call_api_async('GET', '/repos')
            if not repos:
                await query.edit_message_text("❌ No GitHub repos found.")
                return
            buttons = []
            for r in repos[:20]:
                rname = r['name']
                lock = '🔒' if r.get('private') else '🌐'
                buttons.append([InlineKeyboardButton(
                    f"{lock} {rname}",
                    callback_data=f"pushconfirm:{pidx}:{rname}:exist"
                )])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data=f"act:push:{pidx}")])
            buttons.append([HOME_BTN])
            await query.edit_message_text(
                f"📂 *Select existing repo to push to:*",
                parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons)
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Failed to load repos: {e}",
                reply_markup=InlineKeyboardMarkup([[HOME_BTN]]))

    elif data.startswith("pushconfirm:"):
        parts = data.split(":", 3)
        pidx = int(parts[1])
        path = _get_path(context.bot_data, pidx)
        if not _is_allowed_path(path):
            await query.edit_message_text("❌ Only `D:\\` is allowed.", parse_mode='Markdown')
            return
        repo_name = parts[2]
        use_existing = len(parts) > 3 and parts[3] == 'exist'
        # Store push state and route to exclusion picker
        context.user_data['push_excl'] = {
            'path': path, 'repo_name': repo_name,
            'use_existing': use_existing, 'pidx': pidx, 'excluded': []
        }
        text, kb = _build_excl_keyboard(context.bot_data, context.user_data, mode='push')
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)

    elif data.startswith("excltoggle:"):
        fidx = int(data.split(":")[1])
        fp = _get_path(context.bot_data, fidx)
        state = context.user_data.get('push_excl', {})
        excluded: list = state.get('excluded', [])
        if fp in excluded:
            excluded.remove(fp)
        else:
            excluded.append(fp)
        state['excluded'] = excluded
        context.user_data['push_excl'] = state
        text, kb = _build_excl_keyboard(context.bot_data, context.user_data, mode='push')
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)

    elif data.startswith("aexcltoggle:"):
        fidx = int(data.split(":")[1])
        fp = _get_path(context.bot_data, fidx)
        state = context.user_data.get('analyze_excl', {})
        excluded: list = state.get('excluded', [])
        if fp in excluded:
            excluded.remove(fp)
        else:
            excluded.append(fp)
        state['excluded'] = excluded
        context.user_data['analyze_excl'] = state
        text, kb = _build_excl_keyboard(context.bot_data, context.user_data, mode='analyze')
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)

    elif data == "analyzego":
        state = context.user_data.pop('analyze_excl', {})
        path = state.get('path', '')
        if not _is_allowed_path(path):
            await query.edit_message_text("❌ Only `D:\\` is allowed.", parse_mode='Markdown')
            return
        excluded = state.get('excluded', [])
        n = len(excluded)
        await query.edit_message_text(
            f"🔍 Analyzing" + (f" (excluding {n} folder{'s' if n!=1 else ''})" if n else "") + "...",
            parse_mode='Markdown'
        )
        await _do_analyze(query.edit_message_text, path, context.bot_data,
                          exclude_paths=excluded if excluded else None)

    elif data == "pushgo":
        state = context.user_data.get('push_excl', {})
        path = state.get('path', '')
        if not _is_allowed_path(path):
            await query.edit_message_text("❌ Only `D:\\` is allowed.", parse_mode='Markdown')
            return
        repo_name = state.get('repo_name', '')
        use_existing = state.get('use_existing', False)
        excluded = state.get('excluded', [])
        context.user_data.pop('push_excl', None)
        n = len(excluded)
        await query.edit_message_text(
            f"🚀 Pushing *{_esc(repo_name)}*"
            + (f" (excluding {n} folder{'s' if n!=1 else ''})" if n else "") + "...",
            parse_mode='Markdown'
        )
        await _do_push(query.edit_message_text, path, repo_name,
                       use_existing=use_existing, exclude_paths=excluded if excluded else None)

# ─── Natural Language Handler ─────────────────────────────────────────────────
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # ── Awaiting custom repo name input ──────────────────────────────────────
    pending = context.user_data.get('awaiting_repo_name')
    if pending:
        # Allow cancel even while in this state
        if text.lower() in ('/cancel', 'cancel'):
            context.user_data.clear()
            await update.message.reply_text(_main_menu_text(), parse_mode='Markdown', reply_markup=_main_menu_kb())
            return
        del context.user_data['awaiting_repo_name']
        # Sanitise: replace spaces/underscores with hyphens, strip bad chars
        repo_name = re.sub(r'[^a-zA-Z0-9._-]', '-', text.strip()).strip('-') or 'my-repo'
        pidx = pending['pidx']
        path = pending['path']
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Confirm: create '{repo_name}'", callback_data=f"pushconfirm:{pidx}:{repo_name}:new")],
            [InlineKeyboardButton("✏️ Change name", callback_data=f"pushtype:{pidx}")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"act:push:{pidx}")],
            [HOME_BTN],
        ])
        await update.message.reply_text(
            f"🚀 *Create New Repo*\n\n📁 `{_esc(path)}`\nRepo: *{_esc(repo_name)}*\n\nTap Confirm to choose what to exclude before pushing.",
            parse_mode='Markdown', reply_markup=kb
        )
        return

    # Direct drive detection → start folder navigation
    drive = _detect_drive(text)
    if drive:
        if os.path.exists(drive):
            subfolders = _get_subfolders(drive)
            if subfolders:
                nav_text, kb = _build_nav_keyboard(context.bot_data, drive, subfolders)
                await update.message.reply_text(nav_text, parse_mode='Markdown', reply_markup=kb)
            else:
                t, kb = _build_action_keyboard(context.bot_data, drive)
                await update.message.reply_text(t, parse_mode='Markdown', reply_markup=kb)
        else:
            await update.message.reply_text(f"❌ Drive `{drive}` not found.", parse_mode='Markdown')
        return
    if re.search(r'\b(?:[a-ce-zA-CE-Z]):\\', text):
        await update.message.reply_text("❌ Only `D:\\` is allowed.", parse_mode='Markdown')
        return

    thinking = await update.message.reply_text("🤔 Processing...")
    projects = db.get_all_projects()
    project_names = [p['name'] for p in projects]

    try:
        intent = interpret_command(text, project_names)
        action = intent.get('action', 'unknown')
        params = intent.get('params', {})

        if action == 'analyze' and params.get('project_path'):
            if not _is_allowed_path(params['project_path']):
                await thinking.edit_text("❌ Only `D:\\` is allowed.", parse_mode='Markdown')
                return
            await thinking.edit_text(f"🔍 Analyzing...", parse_mode='Markdown')
            await _do_analyze(thinking.edit_text, params['project_path'], context.bot_data)
            return
        elif action == 'push' and params.get('project_path'):
            path = params['project_path']
            if not _is_allowed_path(path):
                await thinking.edit_text("❌ Only `D:\\` is allowed.", parse_mode='Markdown')
                return
            repo = params.get('repo_name', os.path.basename(path).replace(' ', '-').lower())
            await thinking.edit_text(f"🚀 Pushing...")
            await _do_push(thinking.edit_text, path, repo)
            return
        elif action == 'list_repos':
            await thinking.delete(); await repos_cmd(update, context); return
        elif action == 'list_projects':
            await thinking.delete(); await projects_cmd(update, context); return
        elif action == 'help':
            await thinking.delete(); await help_cmd(update, context); return
    except Exception:
        pass

    # Fuzzy match fallback
    matches = fuzzy_match_all(text.lower(), project_names, threshold=60, limit=3)
    if matches:
        buttons = [[InlineKeyboardButton(
            m, callback_data=f"select:{_register_path(context.bot_data, next(p['path'] for p in projects if p['name']==m))}"
        )] for m in matches]
        await thinking.edit_text("Did you mean one of these?", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 Browse Folders", callback_data="browse_drives")],
            [InlineKeyboardButton("📦 GitHub Repos", callback_data="cmd:repos")],
            [InlineKeyboardButton("🗃️ Analyzed Projects", callback_data="cmd:projects")],
        ])
        await thinking.edit_text("What would you like to do?", reply_markup=keyboard)

# ─── Bot Entry Point ──────────────────────────────────────────────────────────
def run_bot():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('cancel', cancel_cmd))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(CommandHandler('browse', browse_cmd))
    app.add_handler(CommandHandler('analyze', analyze_cmd))
    app.add_handler(CommandHandler('push', push_cmd))
    app.add_handler(CommandHandler('repos', repos_cmd))
    app.add_handler(CommandHandler('projects', projects_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print("RepoMind AI Telegram Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    run_bot()
