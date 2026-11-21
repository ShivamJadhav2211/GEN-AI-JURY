import csv
import io
import json
import os
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types
import streamlit as st

load_dotenv()

st.set_page_config(
    page_title="To-Do List from Text (PS 46)", page_icon="✅", layout="wide"
)

st.markdown(
    """
    <style>
        .main-banner {
            background: linear-gradient(135deg, #1e1b4b 0%, #312e81 45%, #0f766e 100%);
            padding: 18px 24px;
            border-radius: 14px;
            color: white;
            margin-bottom: 18px;
            box-shadow: 0 6px 18px rgba(30, 27, 75, 0.18);
        }
        .main-banner h1 {
            margin: 0;
            font-size: 1.9rem;
            color: #ffffff;
        }
        .main-banner p {
            margin: 6px 0 0 0;
            color: #e0e7ff;
            font-size: 0.95rem;
        }
        .task-card {
            padding: 10px 14px;
            border-radius: 10px;
            margin-bottom: 6px;
            border: 1px solid #e2e8f0;
        }
        .prio-high {
            background-color: #fef2f2;
            border-left: 5px solid #ef4444;
        }
        .prio-medium {
            background-color: #fffbeb;
            border-left: 5px solid #f59e0b;
        }
        .prio-low {
            background-color: #f0fdf4;
            border-left: 5px solid #22c55e;
        }
        .done-text {
            text-decoration: line-through;
            opacity: 0.65;
        }
        .stButton > button {
            border-radius: 8px;
            font-weight: 600;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

PRIORITY_ORDER = {"High": 1, "Medium": 2, "Low": 3}
PRIORITY_EMOJI = {
    "High": "🔴 High",
    "Medium": "🟡 Medium",
    "Low": "🟢 Low",
}
PRIORITY_CLASS = {
    "High": "prio-high",
    "Medium": "prio-medium",
    "Low": "prio-low",
}

SYSTEM_PROMPT = """
You are a helpful productivity assistant. Extract actionable tasks from messy free-text notes.
For each task, return a JSON object with:
- "task": short actionable task starting with a verb
- "priority": one of "High", "Medium", or "Low"
- "deadline": mentioned deadline or timeframe, or "No deadline" if none is given

Return ONLY a JSON list of these objects.
"""

PRESETS = {
    "🎯 Project & Deadlines": (
        "Submit lab report by tomorrow 10 AM (urgent).\n"
        "Push mini project code to GitHub before 22 Nov 11:30 AM.\n"
        "Buy milk and fruits on the way back home.\n"
        "Email faculty mentor sometime this week about viva dates."
    ),
    "💼 Work & Meetings": (
        "Fix login page CSS bug before Friday evening, client waiting.\n"
        "Review pull requests from team today.\n"
        "Book dentist appointment next month.\n"
        "Prepare 5-minute demo slides for Monday standup."
    ),
    "⚡ Exam & Viva Prep": (
        "Upload 2-page Report.pdf to Drive before 22 Nov 11:30 AM (urgent).\n"
        "Verify Code.zip has no .env or venv inside today.\n"
        "Practice 10 viva questions on prompt engineering tomorrow.\n"
        "Backup screenshots folder to OneDrive this weekend."
    ),
}


def instant_fallback_tasks(notes: str) -> list:
  """Zero-wait rule-based task extractor for instant testing or API 503 spikes."""
  lines = [
      line.strip(" -•*\t")
      for line in re.split(r"[\n.;]+", notes)
      if line.strip(" -•*\t")
  ]
  results = []
  for line in lines:
    lower = line.lower()

    if any(
        word in lower
        for word in [
            "urgent",
            "asap",
            "today",
            "tomorrow",
            "11:30",
            "10 am",
            "8 pm",
            "before 22 nov",
        ]
    ):
      priority = "High"
    elif any(
        word in lower
        for word in [
            "week",
            "friday",
            "monday",
            "weekend",
            "before",
            "submit",
            "fix",
            "prepare",
            "verify",
            "practice",
        ]
    ):
      priority = "Medium"
    else:
      priority = "Low"

    deadline_match = re.search(
        r"\b(?:today|tomorrow|tonight|this week|next"
        r" week|this"
        r" weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}\s*(?:am|pm)|\d{1,2}\s+[a-z]{3}(?:\s+\d{1,2}:\d{2}\s*(?:am|pm)?)?)\b",
        lower,
    )
    deadline = (
        deadline_match.group(0).title() if deadline_match else "No deadline"
    )

    clean_task = line[0].upper() + line[1:] if line else "Task"
    results.append(
        {"task": clean_task, "priority": priority, "deadline": deadline}
    )
  return results


def extract_tasks(
    notes: str, api_key: str, model_name: str = "gemini-3.8-flash"
) -> list:
  client = genai.Client(api_key=api_key)
  response = client.models.generate_content(
      model=model_name,
      contents=f"Extract tasks from these notes:\n\n{notes}",
      config=types.GenerateContentConfig(
          system_instruction=SYSTEM_PROMPT,
          response_mime_type="application/json",
          temperature=0.2,
      ),
  )
  return json.loads(response.text.strip())


def sort_tasks(tasks: list) -> list:
  return sorted(
      tasks,
      key=lambda item: PRIORITY_ORDER.get(item.get("priority", "Low"), 3),
  )


def to_csv(tasks: list, done_map: dict) -> str:
  buf = io.StringIO()
  writer = csv.DictWriter(
      buf, fieldnames=["task", "priority", "deadline", "completed"]
  )
  writer.writeheader()
  for idx, t in enumerate(tasks):
    writer.writerow({
        "task": t.get("task", ""),
        "priority": t.get("priority", "Low"),
        "deadline": t.get("deadline", "No deadline"),
        "completed": "Yes" if done_map.get(idx, False) else "No",
    })
  return buf.getvalue()


def clear_task_keys():
  for k in list(st.session_state.keys()):
    if k.startswith("todo_item_") or k.startswith("prio_sel_"):
      del st.session_state[k]


def sync_tasks_and_done(items_with_done: list):
  sorted_items = sort_tasks(items_with_done)
  clear_task_keys()
  st.session_state.tasks = [
      {k: v for k, v in item.items() if k != "_done"} for item in sorted_items
  ]
  st.session_state.done_map = {
      i: bool(item.get("_done", False)) for i, item in enumerate(sorted_items)
  }
  for i, item in enumerate(sorted_items):
    st.session_state[f"todo_item_{i}"] = bool(item.get("_done", False))
    st.session_state[f"prio_sel_{i}"] = item.get("priority", "Low")


def set_new_tasks(new_list: list):
  sync_tasks_and_done([{**t, "_done": False} for t in new_list])
  st.session_state["priority_filter_box"] = ["High", "Medium", "Low"]
  st.session_state["status_filter_box"] = "All"
  st.session_state["search_tasks_box"] = ""


def on_checkbox_change(idx: int):
  st.session_state.done_map[idx] = bool(
      st.session_state.get(f"todo_item_{idx}", False)
  )


def on_priority_change(idx: int):
  new_prio = st.session_state.get(f"prio_sel_{idx}")
  if new_prio and 0 <= idx < len(st.session_state.tasks):
    st.session_state.tasks[idx]["priority"] = new_prio
    combined = [
        {
            **t,
            "_done": bool(
                st.session_state.get(
                    f"todo_item_{i}", st.session_state.done_map.get(i, False)
                )
            ),
        }
        for i, t in enumerate(st.session_state.tasks)
    ]
    sync_tasks_and_done(combined)


# Session state setup
if "tasks" not in st.session_state:
  st.session_state.tasks = []
if "notes_editor" not in st.session_state:
  st.session_state.notes_editor = PRESETS["🎯 Project & Deadlines"]
if "done_map" not in st.session_state:
  st.session_state.done_map = {}
if "status_msg" not in st.session_state:
  st.session_state.status_msg = None
if "priority_filter_box" not in st.session_state:
  st.session_state.priority_filter_box = ["High", "Medium", "Low"]

st.markdown(
    """
    <div class="main-banner">
        <h1>✅ To-Do List from Text</h1>
        <p>Roll No. 46 — PS 46 | Transform messy free-text notes into a colourful, prioritised to-do list with deadlines</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
  st.header("🎨 Controls & Settings")
  mode = st.radio(
      "Engine Mode",
      options=["Instant Local (Fast)", "Gemini API (LLM)"],
      index=0,
  )
  api_key = st.text_input(
      "Gemini API Key", value=os.getenv("GEMINI_API_KEY", ""), type="password"
  )
  model_name = st.selectbox("Gemini Model", options=["gemini-3.8-flash"], index=0)
  auto_fallback = st.checkbox("Auto-fallback if Gemini returns 503", value=True)

  st.divider()
  st.subheader("➕ Add Custom Task")
  new_task_text = st.text_input(
      "Task description", placeholder="e.g., Take final UI screenshot"
  )
  new_task_prio = st.selectbox("Priority", ["High", "Medium", "Low"], index=0)
  new_task_due = st.text_input("Deadline", value="Today 9 AM")
  if st.button("➕ Add to List", type="primary", use_container_width=True):
    if new_task_text.strip():
      existing = [
          {
              **t,
              "_done": bool(
                  st.session_state.get(
                      f"todo_item_{i}", st.session_state.done_map.get(i, False)
                  )
              ),
          }
          for i, t in enumerate(st.session_state.tasks)
      ]
      existing.append({
          "task": new_task_text.strip(),
          "priority": new_task_prio,
          "deadline": new_task_due.strip() or "No deadline",
          "_done": False,
      })
      sync_tasks_and_done(existing)
      st.session_state.status_msg = ("success", "Added custom task to list!")
      st.rerun()
    else:
      st.warning("Type a task description first.")

col_left, col_right = st.columns([1, 1.15], gap="large")

with col_left:
  st.subheader("📝 1. Paste or Pick Notes")

  p_cols = st.columns(len(PRESETS))
  for idx, (label, sample_str) in enumerate(PRESETS.items()):
    if p_cols[idx].button(label, use_container_width=True, key=f"preset_{idx}"):
      st.session_state.notes_editor = sample_str
      st.session_state.status_msg = ("info", f"Loaded preset: {label}")
      st.rerun()

  st.text_area(
      "Messy notes:",
      height=230,
      key="notes_editor",
  )

  b1, b2 = st.columns([2, 1])
  generate_clicked = b1.button(
      "🚀 Generate To-Do List", type="primary", use_container_width=True
  )
  if b2.button("🧹 Clear Notes", use_container_width=True, key="clear_notes_btn"):
    st.session_state.notes_editor = ""
    st.session_state.status_msg = ("info", "Notes cleared.")
    st.rerun()

  if generate_clicked:
    current_notes = st.session_state.notes_editor
    if not current_notes.strip():
      st.session_state.status_msg = (
          "warning",
          "Please enter or pick some notes first.",
      )
    elif mode == "Gemini API (LLM)":
      if not api_key:
        st.session_state.status_msg = (
            "error",
            (
                "Enter a Gemini API key in the sidebar or switch to Instant"
                " Local (Fast)."
            ),
        )
      else:
        try:
          with st.spinner("Calling Gemini API..."):
            raw_tasks = extract_tasks(
                current_notes, api_key, model_name=model_name
            )
          set_new_tasks(raw_tasks)
          st.session_state.status_msg = (
              "success",
              f"Generated {len(st.session_state.tasks)} tasks via Gemini.",
          )
          st.rerun()
        except Exception as exc:
          msg = str(exc)
          if auto_fallback and ("503" in msg or "UNAVAILABLE" in msg):
            set_new_tasks(instant_fallback_tasks(current_notes))
            st.session_state.status_msg = (
                "info",
                (
                    "Gemini API hit 503 high demand — loaded instant tasks so"
                    " you aren't blocked."
                ),
            )
            st.rerun()
          elif "503" in msg or "UNAVAILABLE" in msg:
            st.session_state.status_msg = (
                "warning",
                (
                    "Gemini is temporarily overloaded (503). Try again or switch"
                    " to Instant Local (Fast)."
                ),
            )
          else:
            st.session_state.status_msg = ("error", f"Error: {exc}")
    else:
      set_new_tasks(instant_fallback_tasks(current_notes))
      st.session_state.status_msg = (
          "success",
          f"Generated {len(st.session_state.tasks)} tasks instantaneously.",
      )
      st.rerun()

  if st.session_state.status_msg:
    kind, text = st.session_state.status_msg
    getattr(st, kind)(text)

with col_right:
  st.subheader(" 2. Prioritised To-Do List")

  tasks = st.session_state.tasks
  if not tasks:
    st.info(
        "Click **🚀 Generate To-Do List** or pick a preset on the left to see"
        " colourful sorted tasks."
    )
  else:
    for i in range(len(tasks)):
      if f"todo_item_{i}" in st.session_state:
        st.session_state.done_map[i] = bool(st.session_state[f"todo_item_{i}"])
      else:
        st.session_state.done_map[i] = bool(
            st.session_state.done_map.get(i, False)
        )

    high_cnt = sum(1 for t in tasks if t.get("priority") == "High")
    done_cnt = sum(1 for i in range(len(tasks)) if st.session_state.done_map[i])

    m1, m2, m3 = st.columns(3)
    m1.metric("📌 Total Tasks", len(tasks))
    m2.metric("🔥 High Priority", high_cnt)
    m3.metric("✅ Completed", f"{done_cnt}/{len(tasks)}")

    st.progress(done_cnt / len(tasks) if tasks else 0.0)

    f1, f2, f3 = st.columns([1.3, 1, 1.2])
    selected_priorities = f1.multiselect(
        "Filter by priority",
        options=["High", "Medium", "Low"],
        key="priority_filter_box",
    )
    status_filter = f2.selectbox(
        "Filter by status",
        options=["All", "Pending", "Completed"],
        index=0,
        key="status_filter_box",
    )
    search_query = f3.text_input(
        "Search tasks",
        placeholder="Keyword...",
        key="search_tasks_box",
    ).strip().lower()

    # Quick bulk actions
    a1, a2, a3 = st.columns(3)
    if a1.button("☑️ Mark All Done", use_container_width=True, key="mark_all_btn"):
      for i in range(len(tasks)):
        st.session_state.done_map[i] = True
        st.session_state[f"todo_item_{i}"] = True
      st.rerun()

    if a2.button("↩️ Unmark All", use_container_width=True, key="unmark_all_btn"):
      for i in range(len(tasks)):
        st.session_state.done_map[i] = False
        st.session_state[f"todo_item_{i}"] = False
      st.rerun()

    if a3.button("🎯 Reset Filters", use_container_width=True, key="reset_filters_btn"):
      st.session_state["priority_filter_box"] = ["High", "Medium", "Low"]
      st.session_state["status_filter_box"] = "All"
      st.session_state["search_tasks_box"] = ""
      st.rerun()

    active_priorities = (
        selected_priorities if selected_priorities else ["High", "Medium", "Low"]
    )

    visible_count = 0
    for i, item in enumerate(tasks):
      prio = item.get("priority", "Low")
      is_done = st.session_state.done_map[i]
      task_name = item.get("task", "Task")
      due = item.get("deadline", "No deadline")

      if prio not in active_priorities:
        continue
      if status_filter == "Pending" and is_done:
        continue
      if status_filter == "Completed" and not is_done:
        continue
      if search_query and search_query not in f"{task_name} {due} {prio}".lower():
        continue

      visible_count += 1
      badge = PRIORITY_EMOJI.get(prio, prio)
      card_cls = PRIORITY_CLASS.get(prio, "prio-low")
      text_cls = "done-text" if is_done else ""

      c_card, c_prio = st.columns([3.2, 1])
      with c_card:
        st.markdown(
            f'<div class="task-card {card_cls}">'
            f"<strong>{badge}</strong> &nbsp;|&nbsp; 📅 <em>{due}</em><br>"
            f'<span class="{text_cls}">{task_name}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
        st.checkbox(
            "Done",
            value=is_done,
            key=f"todo_item_{i}",
            on_change=on_checkbox_change,
            args=(i,),
            label_visibility="collapsed",
        )
      with c_prio:
        st.selectbox(
            "Priority",
            options=["High", "Medium", "Low"],
            index=["High", "Medium", "Low"].index(prio)
            if prio in ["High", "Medium", "Low"]
            else 2,
            key=f"prio_sel_{i}",
            on_change=on_priority_change,
            args=(i,),
        )

    if visible_count == 0:
      st.caption("No tasks match the active filters or search keyword.")

    st.divider()
    d1, d2, d3 = st.columns(3)
    d1.download_button(
        "⬇️ Download CSV",
        data=to_csv(tasks, st.session_state.done_map),
        file_name="todo_list_ps46.csv",
        mime="text/csv",
        use_container_width=True,
        key="dl_csv_btn",
    )
    txt_lines = [
        f"[{'x' if st.session_state.done_map.get(i, False) else ' '}]"
        f" [{t.get('priority')}] {t.get('task')} (Deadline:"
        f" {t.get('deadline')})"
        for i, t in enumerate(tasks)
    ]
    d2.download_button(
        "⬇️ Download TXT",
        data="\n".join(txt_lines),
        file_name="todo_list_ps46.txt",
        mime="text/plain",
        use_container_width=True,
        key="dl_txt_btn",
    )
    if d3.button("🔄 Reset List", use_container_width=True, key="reset_list_btn"):
      clear_task_keys()
      st.session_state.tasks = []
      st.session_state.done_map = {}
      st.session_state.status_msg = ("info", "To-do list reset.")
      st.rerun()    