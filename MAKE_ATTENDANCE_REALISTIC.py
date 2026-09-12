"""
Make existing seeded attendance realistic without replacing accounts or documents.

Only rows whose note starts with "Historical attendance" are changed.
Saturday/Sunday are weekly offs. Weekday check-in, work duration and notes vary.
"""
from pathlib import Path
import sqlite3, random, os
from datetime import datetime, timedelta, timezone

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get("PORTAL_DATA_DIR",str(ROOT/"data")))
DB=DATA/"workspace.db"
IST=timezone(timedelta(hours=5,minutes=30))

if not DB.exists():
    raise SystemExit("No data/workspace.db found. Start the portal first.")

def shift_for(c,uid):
    r=c.execute("SELECT start_time,end_time FROM shift_settings WHERE user_id=?",(uid,)).fetchone()
    return (r["start_time"],r["end_time"]) if r else ("21:00","06:00")

def window(day,start,end):
    s=datetime.fromisoformat(f"{day}T{start}").replace(tzinfo=IST)
    e=datetime.fromisoformat(f"{day}T{end}").replace(tzinfo=IST)
    if e<=s:e+=timedelta(days=1)
    return s,e

with sqlite3.connect(DB) as c:
    c.row_factory=sqlite3.Row
    people=c.execute("SELECT id,employee_id FROM users WHERE role='employee' AND is_active=1").fetchall()
    latest=datetime.now(IST).date()-timedelta(days=1)
    first=latest-timedelta(days=29)
    changed=0
    for p in people:
        st,et=shift_for(c,p["id"])
        for i in range(30):
            day=first+timedelta(days=i)
            old=c.execute("SELECT * FROM attendance WHERE user_id=? AND date=?",(p["id"],str(day))).fetchone()
            if old and not str(old["note"] or "").lower().startswith("historical attendance"): continue
            ss,se=window(day,st,et)
            if day.weekday()>=5:
                vals=(p["id"],str(day),None,None,0,0,int((se-ss).total_seconds()),"Weekly off — Saturday/Sunday",ss.isoformat(),se.isoformat())
            else:
                rng=random.Random(f"attendance-v2:{p['id']}:{day.isoformat()}")
                late=rng.choice([0,0,0,3,5,8,12,18,25,32])
                mins=rng.randint(485,560)
                ci=ss+timedelta(minutes=late); co=ci+timedelta(minutes=mins)
                note=rng.choice(["Historical attendance record","Regular shift","Worked from office","Night-shift attendance"])
                vals=(p["id"],str(day),ci.isoformat(),co.isoformat(),mins*60,late*60,0,note,ss.isoformat(),se.isoformat())
            c.execute("""INSERT INTO attendance(user_id,date,clock_in,clock_out,worked_seconds,late_seconds,off_seconds,note,shift_start,shift_end)
                         VALUES(?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(user_id,date) DO UPDATE SET clock_in=excluded.clock_in,clock_out=excluded.clock_out,
                         worked_seconds=excluded.worked_seconds,late_seconds=excluded.late_seconds,off_seconds=excluded.off_seconds,
                         note=excluded.note,shift_start=excluded.shift_start,shift_end=excluded.shift_end""",vals)
            changed+=1
print(f"Updated {changed} historical attendance rows for {len(people)} active employees.")
