# NoteShare — class demo guide

Run NoteShare on your own laptop and show it on screen. Everything works offline;
no internet or hosting is needed.

## 1. Before class (about 2 minutes)

Open the project in VS Code and use its terminal (`` Ctrl+` ``).

```powershell
# 1. Start the database (open Docker Desktop first and wait for "Engine running")
docker start noteshare-mysql

# 2. Turn on the project's Python environment
cd "C:\Users\srini\OneDrive\Desktop\NoteShare"
.\.venv\Scripts\Activate.ps1

# 3. Make sure the accounts, subjects and sample notes exist (safe to run every time)
python seed.py
python demo_seed.py

# 4. Start the website
python app.py
```

Open **http://127.0.0.1:5000** in your browser. You should see the Browse page with six
notes. Leave the terminal open; the site runs until you press **Ctrl+C**.

Tip: open the browser full-screen and increase the zoom a little so the class can read it.

## 2. Login accounts (development only)

| Role | Email | Password |
| ---- | ----- | -------- |
| Admin | `admin@noteshare.example.com` | `AdminDev#2026` |
| Moderator | `moderator@noteshare.example.com` | `ModDev#2026` |
| Student 1 | `student1@noteshare.example.com` | `Student1Dev#2026` |
| Student 2 | `student2@noteshare.example.com` | `Student2Dev#2026` |
| Student 3 | `student3@noteshare.example.com` | `Student3Dev#2026` |

Keep this table handy. The quickest way to switch roles is a normal browser window plus an
incognito window, so you can be a student in one and the moderator in the other.

## 3. Suggested walkthrough (about 5–7 minutes)

**A. Browse and find notes (no login needed)**
1. Start on the Browse page. Point out the note cards, the star ratings and the statistics
   bar (Total notes / downloads / subjects).
2. Type `algorithms` in Search and click Apply. Then filter by **Semester 5** and a subject.
3. Change **Sort by** to "Highest rated". Clear the filters.

**B. Register and upload (as a new student)**
4. Click **Register** and create a new student account live.
5. Go to **Upload**, fill in a title, pick a subject, and choose any small PDF or image.
   (To show validation, first try a `.txt` file — it is rejected with a clear message.)
6. After uploading, you land on the note page. Click **Download** to show the file opens.

**C. Rate and review (as another student)**
7. Open an existing note (for example *Graph Algorithms*). Give it a star rating and a short
   review, and submit. Point out that submitting again *updates* your rating.
8. Show that you cannot rate or report your **own** note.

**D. Reporting and automatic flagging**
9. As student 1, open the note student 2 just uploaded and **Report** it.
10. Switch to student 3 (and, if needed, another student) and report the same note.
11. On the **third** report the note is flagged and disappears from Browse — show that it no
    longer appears for an ordinary student.

**E. Moderation (as the moderator)**
12. Log in as the moderator and open **Reports**. The flagged note is at the top, with its
    reports grouped under it.
13. Show **Dismiss** (the note comes back) or **Remove** (it stays hidden). Try **Warn
    uploader**; mention that three warnings suspend the account automatically.
14. Open **Users**. Show the student list, then **Unban** or **Reset warnings** on an account
    you warned or banned.

**F. Administration (as the admin)**
15. Log in as the admin and open **Subjects**. Add a new subject, edit one, and show that a
    subject with notes cannot be deleted.

**G. Extras worth a mention**
16. Resize the browser narrow (or open on your phone on the same Wi-Fi) to show the mobile
    layout.
17. Visit a made-up URL to show the custom "Page not found" page.

## 4. If you want to mention the tests

```powershell
python -m pytest -v
```

291 automated tests run against a separate test database (about 4–5 minutes). See
`docs/test_cases.md` for the list and the latest results.

## 5. After the demo / starting fresh

- Stop the site with **Ctrl+C** in the terminal.
- The notes you added stay in the database for next time. `python demo_seed.py` only adds the
  sample notes that are missing, so it is always safe to run again.
- To remove everything you created during the demo and reload just the sample notes:

  ```powershell
  python reset_demo.py
  python demo_seed.py
  ```

`reset_demo.py` deletes all notes, ratings and reports and clears any warnings or bans on the
seeded student accounts. It does **not** touch the five seeded accounts or the six subjects.
It asks for confirmation first.
