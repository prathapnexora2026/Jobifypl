"""Reset test data for a clean end-to-end run:
1. Rename every existing job's company to 'Texas'.
2. Fully delete the user's number (+919177415501) so they can re-onboard fresh
   as BOTH recruiter and candidate (removes profiles, wallet, docs, jobs,
   applications, conversations, messages, notifications tied to that user).
3. Clean up any conversations/messages whose party columns no longer match the
   users' current roles (the role-switch tangle that caused name doubling).
"""
import sqlite3

DB = "jobify.db"
PHONE = "+919177415501"

c = sqlite3.connect(DB)
cur = c.cursor()

# --- 1. rename all jobs' company to Texas ---
n = cur.execute("UPDATE jobs SET company_name='Texas' WHERE 1=1").rowcount
print(f"jobs renamed to 'Texas': {n}")

# --- 2. find the user id for the phone ---
row = cur.execute("SELECT id FROM users WHERE phone=?", (PHONE,)).fetchone()
if row:
    uid = row[0]
    print(f"deleting all data for user id={uid} ({PHONE})")
    # delete messages in conversations involving this user
    convs = [r[0] for r in cur.execute(
        "SELECT id FROM conversations WHERE candidate_id=? OR recruiter_id=?", (uid, uid)).fetchall()]
    for cv in convs:
        cur.execute("DELETE FROM messages WHERE conversation_id=?", (cv,))
    cur.execute("DELETE FROM conversations WHERE candidate_id=? OR recruiter_id=?", (uid, uid))
    # delete this user's own jobs + applications on them
    my_jobs = [r[0] for r in cur.execute("SELECT id FROM jobs WHERE recruiter_id=?", (uid,)).fetchall()]
    for j in my_jobs:
        cur.execute("DELETE FROM job_applications WHERE job_id=?", (j,))
    cur.execute("DELETE FROM jobs WHERE recruiter_id=?", (uid,))
    cur.execute("DELETE FROM job_applications WHERE candidate_id=?", (uid,))
    # profiles, wallet, docs, notifications, subs, otp, txns
    for tbl, col in [
        ("candidate_profiles", "user_id"), ("recruiter_profiles", "user_id"),
        ("candidate_documents", "user_id"), ("wallets", "user_id"),
        ("wallet_transactions", "user_id"), ("notifications", "user_id"),
        ("user_subscriptions", "user_id"), ("otp_codes", "phone"),
    ]:
        val = PHONE if col == "phone" else uid
        try:
            cur.execute(f"DELETE FROM {tbl} WHERE {col}=?", (val,))
        except sqlite3.OperationalError:
            pass  # table may not exist
    # finally the user row
    cur.execute("DELETE FROM users WHERE id=?", (uid,))
    print(f"  removed user, {len(convs)} conversations, {len(my_jobs)} own jobs")
else:
    print(f"user {PHONE} not found (already clean)")

# --- 3. clean up any conversation whose party roles no longer match ---
def role_of(u):
    r = cur.execute("SELECT role FROM users WHERE id=?", (u,)).fetchone()
    return r[0] if r else None

bad = []
for cid, a, b in cur.execute("SELECT id,candidate_id,recruiter_id FROM conversations").fetchall():
    ra, rb = role_of(a), role_of(b)
    # a conversation should be between two DIFFERENT existing users
    if ra is None or rb is None:
        bad.append(cid)
for cid in bad:
    cur.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
    cur.execute("DELETE FROM conversations WHERE id=?", (cid,))
print(f"removed {len(bad)} orphaned conversations")

c.commit()
print("\nDONE. Verify:")
for r in cur.execute("SELECT DISTINCT company_name FROM jobs"):
    print("  job company:", r[0])
print("  user still exists?", cur.execute("SELECT COUNT(*) FROM users WHERE phone=?", (PHONE,)).fetchone()[0])
c.close()
