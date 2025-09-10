#!/usr/bin/env python3
"""
AI CLI Agent
- Notes: CRUD, edit full/partial (edit lines / append / delete line)
- Tasks: CRUD, optional deadline. Overdue tasks auto-marked as 'missed' when listing/operating.
- Ask: arbitrary question to LLM
Uses SQLite for storage and OpenAI API (if OPENAI_API_KEY present).
"""

import os
import sqlite3
import datetime

from typing import Optional
from dateutil import parser as dateparser
import sys
import textwrap

# Try import openai (optional). If not present or key not set, we'll use a dummy LLM.
try:
    import openai
except Exception:
    openai = None

DB_PATH = os.path.expanduser("~/.ai_agent_db.sqlite3")

# ----------------------
# Database helpers
# ----------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            deadline TEXT,
            status TEXT NOT NULL, -- todo, done, missed
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        conn.commit()

# ----------------------
# LLM wrapper
# ----------------------
OPENAI_KEY = ""
def llm_query(user_prompt: str, system_prompt: Optional[str] = None, model: str = "gpt-4o-mini"):
    """
    Query LLM (OpenAI) if available; otherwise return a simple fallback.
    """
    if openai is None or not OPENAI_KEY:
        return "привет! я подключен, but no money no honey! :)"

    client = openai.OpenAI(api_key=OPENAI_KEY)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
            max_tokens=800
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return "привет! я подключен, but no money no honey! :)"

# ----------------------
# Notes operations
# ----------------------
def create_note():
    title = input("Title (optional): ").strip()
    print("Enter note content. Finish with a single line with only 'END'.")
    lines = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)
    content = "\n".join(lines).strip()
    now = datetime.datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute("INSERT INTO notes (title, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
                     (title, content, now, now))
        conn.commit()
    print("Note saved.")

def list_notes():
    with get_conn() as conn:
        cur = conn.execute("SELECT id, title, created_at, updated_at FROM notes ORDER BY updated_at DESC")
        rows = cur.fetchall()
    if not rows:
        print("No notes.")
        return
    for r in rows:
        print(f"[{r['id']}] {r['title'] or '<no title>'} (updated: {r['updated_at']})")

def view_note(note_id=None):
    if note_id is None:
        note_id = input("Note id: ").strip()
    try:
        nid = int(note_id)
    except:
        print("Invalid id.")
        return
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM notes WHERE id = ?", (nid,))
        r = cur.fetchone()
    if not r:
        print("Note not found.")
        return
    print(f"--- Note [{r['id']}] {r['title'] or ''} ---")
    print(r['content'])
    print("--- end ---")

def delete_note(note_id=None):
    if note_id is None:
        note_id = input("Note id to delete: ").strip()
    try:
        nid = int(note_id)
    except:
        print("Invalid id.")
        return
    with get_conn() as conn:
        cur = conn.execute("SELECT id, title FROM notes WHERE id = ?", (nid,))
        if cur.fetchone() is None:
            print("Not found.")
            return
        conn.execute("DELETE FROM notes WHERE id = ?", (nid,))
        conn.commit()
    print("Deleted.")

def edit_note(note_id=None):
    if note_id is None:
        note_id = input("Note id to edit: ").strip()
    try:
        nid = int(note_id)
    except:
        print("Invalid id.")
        return
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM notes WHERE id = ?", (nid,))
        r = cur.fetchone()
    if not r:
        print("Note not found.")
        return
    print("Edit whole note or part? (whole/part)")
    choice = input("> ").strip().lower()
    if choice in ("whole", "w"):
        print("Current content:")
        print(r["content"])
        print("Enter new content. Finish with single line 'END'.")
        new_lines = []
        while True:
            line = input()
            if line.strip() == "END":
                break
            new_lines.append(line)
        new_content = "\n".join(new_lines).strip()
        now = datetime.datetime.utcnow().isoformat()
        with get_conn() as conn:
            conn.execute("UPDATE notes SET content = ?, updated_at = ? WHERE id = ?", (new_content, now, nid))
            conn.commit()
        print("Note replaced.")
    else:
        # partial edit: show lines, let user choose line number(s)
        content = r["content"] or ""
        lines = content.splitlines()
        if not lines:
            print("[empty note] You can append lines.")
        print("Current note (lines numbered):")
        for i, line in enumerate(lines, start=1):
            print(f"{i:3}: {line}")
        print("Options: 'replace N' 'replace N-M' 'delete N' 'append' 'insert N' 'llm-refactor' 'cancel'")
        cmd = input("> ").strip()
        if cmd.startswith("replace"):
            _, rng = cmd.split(None, 1)
            if "-" in rng:
                a,b = rng.split("-",1)
                try:
                    a_i = int(a)-1
                    b_i = int(b)-1
                except:
                    print("Bad range.")
                    return
                print("Enter replacement text (END on its own line):")
                new = []
                while True:
                    line = input()
                    if line.strip()=="END":
                        break
                    new.append(line)
                new_chunk = "\n".join(new)
                new_lines = lines[:a_i] + new_chunk.splitlines() + lines[b_i+1:]
            else:
                try:
                    idx = int(rng)-1
                except:
                    print("Bad index.")
                    return
                print(f"Old: {lines[idx] if 0<=idx<len(lines) else '<no line>'}")
                new_text = input("New text: ")
                if 0<=idx<len(lines):
                    lines[idx] = new_text
                else:
                    lines.append(new_text)
                new_lines = lines
            new_content = "\n".join(new_lines)
            now = datetime.datetime.utcnow().isoformat()
            with get_conn() as conn:
                conn.execute("UPDATE notes SET content = ?, updated_at = ? WHERE id = ?", (new_content, now, nid))
                conn.commit()
            print("Updated.")
        elif cmd.startswith("delete"):
            try:
                _, n = cmd.split(None,1)
                idx = int(n)-1
                if 0<=idx<len(lines):
                    lines.pop(idx)
                    new_content = "\n".join(lines)
                    now = datetime.datetime.utcnow().isoformat()
                    with get_conn() as conn:
                        conn.execute("UPDATE notes SET content = ?, updated_at = ? WHERE id = ?", (new_content, now, nid))
                        conn.commit()
                    print("Line deleted.")
                else:
                    print("Index out of range.")
            except Exception as e:
                print("Error:", e)
                return
        elif cmd=="append":
            print("Enter text lines to append (END to finish):")
            new = []
            while True:
                line = input()
                if line.strip()=="END":
                    break
                new.append(line)
            new_content = content + ("\n" if content and new else "") + "\n".join(new)
            now = datetime.datetime.utcnow().isoformat()
            with get_conn() as conn:
                conn.execute("UPDATE notes SET content = ?, updated_at = ? WHERE id = ?", (new_content, now, nid))
                conn.commit()
            print("Appended.")
        elif cmd.startswith("insert"):
            try:
                _, n = cmd.split(None,1)
                idx = int(n)-1
                print("Enter lines to insert BEFORE that line (END to finish):")
                new = []
                while True:
                    line = input()
                    if line.strip()=="END":
                        break
                    new.append(line)
                if idx < 0:
                    idx = 0
                if idx > len(lines):
                    idx = len(lines)
                new_lines = lines[:idx] + new + lines[idx:]
                new_content = "\n".join(new_lines)
                now = datetime.datetime.utcnow().isoformat()
                with get_conn() as conn:
                    conn.execute("UPDATE notes SET content = ?, updated_at = ? WHERE id = ?", (new_content, now, nid))
                    conn.commit()
                print("Inserted.")
            except Exception as e:
                print("Error:", e)
                return
        elif cmd=="llm-refactor":
            # Use LLM to rewrite the note or part of it
            print("Choose scope: 'whole' or 'lines N-M' or 'lines N'")
            scope = input("> ").strip()
            if scope=="whole":
                prompt = ("Refactor or improve this note content for clarity and conciseness.\n\n"
                          f"Content:\n{content}\n\nProvide the improved version only.")
                out = llm_query(prompt, system_prompt="You are an assistant that rewrites notes to be clear and concise.")
                if out:
                    now = datetime.datetime.utcnow().isoformat()
                    with get_conn() as conn:
                        conn.execute("UPDATE notes SET content = ?, updated_at = ? WHERE id = ?", (out, now, nid))
                        conn.commit()
                    print("Note replaced with LLM result.")
            elif scope.startswith("lines"):
                parts = scope.split()
                if len(parts)==2 and "-" in parts[1]:
                    a,b = parts[1].split("-",1)
                    a_i = int(a)-1
                    b_i = int(b)-1
                    selection = "\n".join(lines[a_i:b_i+1])
                    prompt = ("Refactor or improve the following selection of the note for clarity and conciseness. "
                              "Return only the improved selection.\n\n" + selection)
                    out = llm_query(prompt, system_prompt="You are an assistant that rewrites snippets for clarity.")
                    if out:
                        new_lines = lines[:a_i] + out.splitlines() + lines[b_i+1:]
                        new_content = "\n".join(new_lines)
                        now = datetime.datetime.utcnow().isoformat()
                        with get_conn() as conn:
                            conn.execute("UPDATE notes SET content = ?, updated_at = ? WHERE id = ?", (new_content, now, nid))
                            conn.commit()
                        print("Selection replaced with LLM result.")
                else:
                    try:
                        n = int(parts[1])
                        idx = n-1
                        selection = lines[idx]
                        prompt = ("Refactor this line for clarity and conciseness. Return only the improved line.\n\n"
                                  + selection)
                        out = llm_query(prompt)
                        if out:
                            lines[idx] = out.splitlines()[0]
                            new_content = "\n".join(lines)
                            now = datetime.datetime.utcnow().isoformat()
                            with get_conn() as conn:
                                conn.execute("UPDATE notes SET content = ?, updated_at = ? WHERE id = ?", (new_content, now, nid))
                                conn.commit()
                            print("Line replaced with LLM result.")
                    except Exception as e:
                        print("Bad input.", e)
            else:
                print("Unknown scope.")
        else:
            print("Unknown command. Cancelled.")

# ----------------------
# Tasks operations
# ----------------------
def normalize_status_on_read():
    """Mark overdue tasks as missed when appropriate."""
    now = datetime.datetime.utcnow()
    with get_conn() as conn:
        cur = conn.execute("SELECT id, deadline, status FROM tasks WHERE deadline IS NOT NULL AND status NOT IN ('done','missed')")
        rows = cur.fetchall()
        for r in rows:
            dl = r["deadline"]
            try:
                dl_dt = dateparser.parse(dl)
                if dl_dt.tzinfo is None:
                    dl_dt = dl_dt.replace(tzinfo=datetime.timezone.utc)
                now_tz = now.replace(tzinfo=datetime.timezone.utc)
                if dl_dt < now_tz:
                    conn.execute("UPDATE tasks SET status = 'missed', updated_at = ? WHERE id = ?",
                                 (now.isoformat(), r["id"]))
            except Exception:
                continue
        conn.commit()

def create_task():
    desc = input("Task description: ").strip()
    if not desc:
        print("Empty description, cancelled.")
        return
    yn = input("Есть дедлайн? (y/n): ").strip().lower()
    deadline = None
    if yn in ("y","yes"):
        while True:
            s = input("Введите дедлайн (YYYY-MM-DD or YYYY-MM-DD HH:MM, e.g. 2025-09-12 18:00): ").strip()
            try:
                dt = dateparser.parse(s)
                # store ISO (UTC if no tz provided)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                deadline = dt.isoformat()
                break
            except Exception:
                print("Не удалось распознать дату. Попробуйте ещё.")
    now = datetime.datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute("INSERT INTO tasks (description, deadline, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                     (desc, deadline, "todo", now, now))
        conn.commit()
    print("Task created.")

def list_tasks(show_all=False):
    normalize_status_on_read()
    with get_conn() as conn:
        if show_all:
            cur = conn.execute("SELECT * FROM tasks ORDER BY updated_at DESC")
        else:
            cur = conn.execute("SELECT * FROM tasks WHERE status != 'done' ORDER BY deadline IS NULL, deadline")
        rows = cur.fetchall()
    if not rows:
        print("No tasks.")
        return
    for r in rows:
        dl = r["deadline"] or "-"
        print(f"[{r['id']}] ({r['status']}) {r['description']}  | deadline: {dl} | updated: {r['updated_at']}")

def view_task(task_id=None):
    if task_id is None:
        task_id = input("Task id: ").strip()
    try:
        tid = int(task_id)
    except:
        print("Invalid id.")
        return
    normalize_status_on_read()
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,))
        r = cur.fetchone()
    if not r:
        print("Not found.")
        return
    print(f"--- Task [{r['id']}] ---")
    print("Description:")
    print(r["description"])
    print("Status:", r["status"])
    print("Deadline:", r["deadline"] or "—")
    print("Created:", r["created_at"])
    print("Updated:", r["updated_at"])
    print("--- end ---")

def complete_task(task_id=None):
    if task_id is None:
        task_id = input("Task id to mark done: ").strip()
    try:
        tid = int(task_id)
    except:
        print("Invalid id.")
        return
    now = datetime.datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.execute("SELECT id FROM tasks WHERE id = ?", (tid,))
        if cur.fetchone() is None:
            print("Not found.")
            return
        conn.execute("UPDATE tasks SET status = 'done', updated_at = ? WHERE id = ?", (now, tid))
        conn.commit()
    print("Marked done.")

def delete_task(task_id=None):
    if task_id is None:
        task_id = input("Task id to delete: ").strip()
    try:
        tid = int(task_id)
    except:
        print("Invalid id.")
        return
    with get_conn() as conn:
        cur = conn.execute("SELECT id FROM tasks WHERE id = ?", (tid,))
        if cur.fetchone() is None:
            print("Not found.")
            return
        conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))
        conn.commit()
    print("Deleted.")

def edit_task(task_id=None):
    if task_id is None:
        task_id = input("Task id to edit: ").strip()
    try:
        tid = int(task_id)
    except:
        print("Invalid id.")
        return
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,))
        r = cur.fetchone()
    if not r:
        print("Not found.")
        return
    print("Current description:")
    print(r["description"])
    if input("Edit description? (y/n): ").strip().lower() in ("y","yes"):
        new = input("New description: ")
        now = datetime.datetime.utcnow().isoformat()
        with get_conn() as conn:
            conn.execute("UPDATE tasks SET description = ?, updated_at = ? WHERE id = ?", (new, now, tid))
            conn.commit()
        print("Description updated.")
    if input("Edit deadline? (y/n): ").strip().lower() in ("y","yes"):
        s = input("Enter new deadline (empty to remove): ").strip()
        if s=="":
            new_dl = None
        else:
            try:
                dt = dateparser.parse(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                new_dl = dt.isoformat()
            except Exception:
                print("Bad date. Skipping deadline edit.")
                new_dl = r["deadline"]
        now = datetime.datetime.utcnow().isoformat()
        with get_conn() as conn:
            conn.execute("UPDATE tasks SET deadline = ?, updated_at = ? WHERE id = ?", (new_dl, now, tid))
            conn.commit()
        print("Deadline updated.")

# ----------------------
# CLI & Help
# ----------------------
HELP_TEXT = """
Команды (вводите без кавычек):
 help                        - показать это сообщение
 notes create                - создать заметку
 notes list                  - список заметок
 notes view <id>             - посмотреть заметку
 notes edit <id>             - редактировать заметку (полностью/частично)
 notes delete <id>           - удалить заметку

 tasks create                - создать задачу
 tasks list                  - список незавершённых задач (штампирует missed автоматически)
 tasks list all              - все задачи
 tasks view <id>             - посмотреть задачу
 tasks edit <id>             - редактировать задачу
 tasks done <id>             - отметить задачу выполненной
 tasks delete <id>           - удалить задачу

 ask <вопрос>                - спросить у LLM (ответ будет выведен)
 exit / quit                 - выйти
"""

def repl():
    print("AI CLI Agent — запущен. Введите 'help' для списка команд.")
    while True:
        try:
            cmd = input("agent> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break
        if not cmd:
            continue
        parts = cmd.split()
        if parts[0] in ("exit","quit"):
            print("Bye.")
            break
        if parts[0]=="help":
            print(HELP_TEXT)
            continue
        # route commands
        if parts[0]=="notes":
            if len(parts)<2:
                print("notes: подкоманды create/list/view/edit/delete")
                continue
            sub = parts[1]
            if sub=="create":
                create_note()
            elif sub=="list":
                list_notes()
            elif sub=="view":
                if len(parts)>=3:
                    view_note(parts[2])
                else:
                    view_note()
            elif sub=="delete":
                if len(parts)>=3:
                    delete_note(parts[2])
                else:
                    delete_note()
            elif sub=="edit":
                if len(parts)>=3:
                    edit_note(parts[2])
                else:
                    edit_note()
            else:
                print("Unknown notes subcommand.")
            continue
        if parts[0]=="tasks":
            if len(parts)<2:
                print("tasks: subcommands create/list/view/edit/done/delete")
                continue
            sub = parts[1]
            if sub=="create":
                create_task()
            elif sub=="list":
                if len(parts)>=3 and parts[2]=="all":
                    list_tasks(show_all=True)
                else:
                    list_tasks()
            elif sub=="view":
                if len(parts)>=3:
                    view_task(parts[2])
                else:
                    view_task()
            elif sub=="edit":
                if len(parts)>=3:
                    edit_task(parts[2])
                else:
                    edit_task()
            elif sub=="done":
                if len(parts)>=3:
                    complete_task(parts[2])
                else:
                    complete_task()
            elif sub=="delete":
                if len(parts)>=3:
                    delete_task(parts[2])
                else:
                    delete_task()
            else:
                print("Unknown tasks subcommand.")
            continue
        if parts[0]=="ask":
            question = cmd[len("ask"):].strip()
            if not question:
                print("Введите вопрос после 'ask'.")
                continue
            print("Отправляю запрос в LLM...")
            out = llm_query(question, system_prompt="You are a helpful assistant.")
            print("--- LLM ответ ---")
            print(out)
            print("-----------------")
            continue
        print("Неизвестная команда. Введите 'help'.")

# ----------------------
# Entry point
# ----------------------
def main():
    init_db()
    repl()

if __name__=="__main__":
    main()
