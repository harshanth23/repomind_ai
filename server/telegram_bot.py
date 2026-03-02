import os
import sys
import requests
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


# --- Helpers ---
def call_api(method: str, endpoint: str, payload: dict = None) -> dict:
    url = f"{SERVER_URL}{endpoint}"
    if method == 'GET':
        resp = requests.get(url)
    else:
        resp = requests.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()


def build_project_keyboard(projects: list) -> InlineKeyboardMarkup:
    buttons = []
    for p in projects[:10]:
        buttons.append([InlineKeyboardButton(p['name'], callback_data=f"analyze:{p['path']}")])
    return InlineKeyboardMarkup(buttons)


# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to *RepoMind AI*!\n\n"
        "Commands:\n"
        "/analyze `<path>` – Analyze a project\n"
        "/push `<path> <repo_name>` – Push project to GitHub\n"
        "/repos – List your GitHub repos\n"
        "/projects – List analyzed local projects\n"
        "/help – Show this message",
        parse_mode='Markdown'
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /analyze <project_path>")
        return
    path = ' '.join(context.args)
    await update.message.reply_text(f"🔍 Analyzing `{path}`...", parse_mode='Markdown')
    try:
        result = call_api('POST', '/analyze', {'project_path': path})
        scan = result['scan']
        analysis = result['analysis']
        decisions = result['decisions']

        msg = (
            f"*Project:* `{result['project_name']}`\n"
            f"*Total Size:* {scan['total_size_hr']}\n"
            f"*Total Files:* {scan['total_files']}\n"
            f"*Python Files:* {analysis['total_python_files']}\n"
            f"*Lines of Code:* {analysis['total_lines_of_code']}\n"
            f"*Frameworks:* {', '.join(analysis['detected_frameworks']) or 'None detected'}\n"
            f"*Requirements.txt:* {'✅' if analysis['requirements_found'] else '❌'}\n"
            f"*Git Initialized:* {'✅' if analysis['git_initialized'] else '❌'}\n"
            f"*Model Files:* {len(analysis['model_files'])}\n"
            f"*Large Files:* {len(scan['large_files'])}\n"
            f"*Dataset Folders:* {len(scan['dataset_folders'])}\n"
        )
        if decisions['warn_large_files']:
            msg += f"\n⚠️ *Warning:* {len(decisions['warn_large_files'])} large file(s) detected!\n"
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def push_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /push <project_path> <repo_name>")
        return
    repo_name = context.args[-1]
    path = ' '.join(context.args[:-1])
    await update.message.reply_text(f"🚀 Pushing `{path}` to GitHub as `{repo_name}`...", parse_mode='Markdown')
    try:
        result = call_api('POST', '/push', {
            'project_path': path,
            'repo_name': repo_name,
            'commit_message': 'Initial commit via RepoMind AI'
        })
        await update.message.reply_text(
            f"✅ *Pushed successfully!*\n🔗 {result.get('url', '')}",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Push failed: {e}")


async def repos_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📦 Fetching your GitHub repos...")
    try:
        repos = call_api('GET', '/repos')
        if not repos:
            await update.message.reply_text("No repositories found.")
            return
        msg = "*Your GitHub Repositories:*\n\n"
        for r in repos[:15]:
            lock = "🔒" if r.get('private') else "🌐"
            msg += f"{lock} [{r['name']}]({r['url']})\n"
        await update.message.reply_text(msg, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def projects_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    projects = db.get_all_projects()
    if not projects:
        await update.message.reply_text("No local projects analyzed yet. Use /analyze <path>")
        return
    keyboard = build_project_keyboard(projects)
    await update.message.reply_text("📁 *Analyzed Local Projects:*", parse_mode='Markdown', reply_markup=keyboard)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("analyze:"):
        path = data[len("analyze:"):]
        await query.edit_message_text(f"🔍 Analyzing `{path}`...", parse_mode='Markdown')
        try:
            result = call_api('POST', '/analyze', {'project_path': path})
            scan = result['scan']
            analysis = result['analysis']
            msg = (
                f"*Project:* `{result['project_name']}`\n"
                f"*Total Size:* {scan['total_size_hr']}\n"
                f"*Files:* {scan['total_files']} | *LOC:* {analysis['total_lines_of_code']}\n"
                f"*Frameworks:* {', '.join(analysis['detected_frameworks']) or 'None'}\n"
            )
            await query.edit_message_text(msg, parse_mode='Markdown')
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {e}")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle natural language commands using Groq LLM + fuzzy matching."""
    text = update.message.text
    projects = db.get_all_projects()
    project_names = [p['name'] for p in projects]

    # Send immediate acknowledgement so user isn't waiting silently
    thinking_msg = await update.message.reply_text("🤔 Processing your request...")

    # Try Groq LLM interpretation first
    try:
        intent = interpret_command(text, project_names)
        action = intent.get('action', 'unknown')
        params = intent.get('params', {})

        if action == 'analyze' and params.get('project_path'):
            path = params['project_path']
            await thinking_msg.edit_text(f"🔍 Analyzing `{path}`...", parse_mode='Markdown')
            try:
                result = call_api('POST', '/analyze', {'project_path': path})
                scan = result['scan']
                analysis = result['analysis']
                decisions = result['decisions']
                msg = (
                    f"*Project:* `{result['project_name']}`\n"
                    f"*Total Size:* {scan['total_size_hr']}\n"
                    f"*Total Files:* {scan['total_files']}\n"
                    f"*Python Files:* {analysis['total_python_files']}\n"
                    f"*Lines of Code:* {analysis['total_lines_of_code']}\n"
                    f"*Frameworks:* {', '.join(analysis['detected_frameworks']) or 'None detected'}\n"
                    f"*Requirements.txt:* {'✅' if analysis['requirements_found'] else '❌'}\n"
                    f"*Git Initialized:* {'✅' if analysis['git_initialized'] else '❌'}\n"
                    f"*Model Files:* {len(analysis['model_files'])}\n"
                    f"*Large Files:* {len(scan['large_files'])}\n"
                    f"*Dataset Folders:* {len(scan['dataset_folders'])}\n"
                )
                if decisions['warn_large_files']:
                    msg += f"\n⚠️ *Warning:* {len(decisions['warn_large_files'])} large file(s) detected!\n"
                await thinking_msg.edit_text(msg, parse_mode='Markdown')
            except Exception as e:
                await thinking_msg.edit_text(f"❌ Error analyzing `{path}`: {e}", parse_mode='Markdown')
            return

        elif action == 'push' and params.get('project_path') and params.get('repo_name'):
            path = params['project_path']
            repo_name = params['repo_name']
            await thinking_msg.edit_text(f"🚀 Pushing `{path}` as `{repo_name}`...", parse_mode='Markdown')
            try:
                result = call_api('POST', '/push', {
                    'project_path': path,
                    'repo_name': repo_name,
                    'commit_message': 'Commit via RepoMind AI'
                })
                await thinking_msg.edit_text(
                    f"✅ *Pushed!*\n🔗 {result.get('url', '')}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                await thinking_msg.edit_text(f"❌ Push failed: {e}", parse_mode='Markdown')
            return

        elif action == 'list_repos':
            await thinking_msg.delete()
            await repos_cmd(update, context)
            return
        elif action == 'list_projects':
            await thinking_msg.delete()
            await projects_cmd(update, context)
            return
        elif action == 'help':
            await thinking_msg.delete()
            await help_cmd(update, context)
            return
    except Exception:
        pass

    # Fallback: fuzzy match project name
    matches = fuzzy_match_all(text.lower(), project_names, threshold=60, limit=3)
    if matches:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(m, callback_data=f"analyze:{next(p['path'] for p in projects if p['name']==m)}")]
            for m in matches
        ])
        await thinking_msg.edit_text("Did you mean one of these projects?", reply_markup=keyboard)
    else:
        await thinking_msg.edit_text("I didn't understand that. Use /help to see available commands.")


def run_bot():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_cmd))
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
