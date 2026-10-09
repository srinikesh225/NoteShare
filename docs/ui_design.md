# NoteShare UI design: the three golden rules

These are the three golden rules of user-interface design. For each rule this page gives a
simple definition, the screens where NoteShare uses it, real examples from the website,
and how each example helps the user. Every example below exists in the current version.

---

## Rule 1: Place the user in control

**In simple words:** the user decides what happens. They can see what is going on, change
their mind, undo or cancel, and they are never surprised by a big action they didn't mean
to take.

**Screens:** My Notes, note page, moderation dashboard, subject administration, home page
(search and filters), every page with messages, error pages.

| Example (real) | Where | How it helps |
| -------------- | ----- | ------------ |
| **Confirmation before costly actions.** Clicking *Delete* opens a panel asking "Delete … permanently?" with a separate red *Yes, delete* button. The same happens for *Remove note* ("Are you sure you want to remove this note? …"), *Ban uploader* ("They will not be able to log in.") and deleting a subject. | My Notes, note page, moderation, subjects | A slip of the mouse can't delete or ban anything. The user has to confirm on purpose, and can simply close the panel to cancel. |
| **You can change your rating.** If you rated a note before, the form is filled in with your stars and comment, and the button says *Update your rating*. Sending it again replaces your old rating instead of adding a second one. | Note page | A rating isn't final; the user can fix a mistake or change their opinion. |
| **Clear feedback after every action.** Green, red, yellow or blue messages such as "Your note has been uploaded.", "Report submitted.", "Uma Uploader has been warned. Warning count: 2 of 3." Each message can be closed with its × button. | Every page | The user always knows whether their action worked and what changed. |
| **Easy ways back.** *Clear filters*, *Back to results*, *Cancel* on the subject form, and error pages with *Go to the home page* or *Browse notes* buttons. | Home, note page, subject form, 403/404 pages | The user is never stuck and can leave a screen without losing their place. |
| **The user chooses what to see.** Search, semester, subject and sort options are all in one form, and the URL keeps them, so a result list can be bookmarked or shared. | Home page | The user controls the list instead of scrolling through everything. |
| **Their own content.** Students can delete their own notes and see each note's status (Active, Flagged / Under Review, Removed). | My Notes | Students stay in charge of what they have shared and know what happened to it. |

---

## Rule 2: Reduce the user's memory load

**In simple words:** the user shouldn't have to remember things. The screen shows the
options, the rules and the next step, so they can recognise rather than recall.

**Screens:** registration and login, upload page, home page, note page, My Notes, account
page, moderation dashboard, subject forms, empty pages.

| Example (real) | Where | How it helps |
| -------------- | ----- | ------------ |
| **Labels and hints next to each field.** "Password: At least 8 characters", "File: PDF, Word (.docx), PowerPoint (.pptx), JPG or PNG. Maximum 10 MiB.", "Subject code: For example, CS501." | Register, upload, subject form | The rules are on screen, so the user doesn't have to guess or remember them. |
| **Choices loaded from the database.** The subject list shows code, name and semester ("CS501 — Design and Analysis of Algorithms (Semester 5)"), grouped by semester. | Upload, home filters | The user picks from a list instead of remembering subject codes. |
| **Typed values are kept after an error.** If one field is wrong, everything else stays filled in (never the password), and the error appears right under the field it belongs to. | Register, login, upload, rating and report forms, subject form | The user only fixes the problem instead of re-typing the whole form. |
| **Filters are kept while paging.** Moving to page 2 keeps the search word, semester, subject and sort order. "Showing 1–12 of 37 notes" says where you are. | Home page | The user doesn't have to set the filters again on every page. |
| **Helpful empty states.** "No notes yet. Be the first to upload!", "No notes match your search. Try changing your search or filters.", "You haven't uploaded any notes yet. Upload your first note to get started.", "No reviews yet. Be the first to rate this note.", "No open reports. Everything is clear.", "No subjects found." Most come with the right button (Upload a note, Clear search, Add subject), shown only to users allowed to use it. | Home, My Notes, note page, moderation, subjects | An empty page explains why it is empty and what to do next. |
| **The system remembers for you.** Your existing rating is shown in the form; after reporting, the page says "You reported this note on 09 Oct 2026 (Unreadable)…"; moderation cards show the uploader's warning count ("1 of 3 warnings"); the account page shows your own warnings. | Note page, moderation, account | Nobody has to remember what they did earlier or look it up elsewhere. |
| **Breadcrumbs and statistics.** "Browse notes / CS501 Design and Analysis of Algorithms / Graph Algorithms Notes" shows where you are; the home page shows Total notes, Total downloads and Total subjects. | Note page and other inner pages, home | The user always knows where they are and how much is available. |

---

## Rule 3: Make the interface consistent

**In simple words:** things that do the same job look and work the same everywhere. Once
the user learns one screen, they can use the others.

**Screens:** every page, because they all use the same base template, components and
styles.

| Example (real) | Where | How it helps |
| -------------- | ----- | ------------ |
| **One shared layout.** Every page is built on `base.html`: the same header with the NoteShare logo, search box, navigation (Browse, Upload, My Notes, plus Reports for moderators and Subjects for admins), account button and footer. | All pages | Navigation is always in the same place. |
| **The same button styles everywhere.** Black = main action (*Upload note*, *Apply*, *Submit rating*); white with a border = secondary (*View details*, *Cancel*, *Dismiss reports*); red outline that opens a confirmation = destructive (*Delete*, *Remove note*, *Ban uploader*). | All pages | The colour and style tell the user what a button will do before they click. |
| **The same form pattern.** Label above the field, hint in grey, red message below the field when something is wrong, and, on forms with several fields, the same "Please correct the highlighted fields." message at the top. | All forms | Every form is filled in and corrected the same way. |
| **The same confirmation pattern** for every destructive action (a panel with a red "Yes, …" button). | My Notes, note page, moderation, subjects | Users recognise the safety step everywhere. |
| **The same status labels.** Active, Flagged / Under Review and Removed always look the same and always include the words, not just a colour. | My Notes, note page, moderation | Status is clear even for colour-blind users, and means the same everywhere. |
| **Matching error pages.** 403 "Access denied", 404 "Page not found" and other errors share one layout: an error code, a heading, a short message and a button back. | Error pages | Errors feel familiar and always offer a way out. |
| **Consistent details.** Dates always appear as "09 Oct 2026"; ratings always appear as a star with a number or "No ratings yet"; one lime highlight colour marks subject codes, the current page and role badges. | All pages | The user reads information the same way on every screen. |

---

## Accessibility and mobile support (part of all three rules)

- **Every page works on phones, tablets and desktops.** It was checked at 320, 375, 768 and
  1366 pixels wide: no sideways scrolling, buttons big enough to tap, and tables that turn
  into cards on small screens.
- **Every field has a visible label.**
- **The keyboard focus is always visible.**
- **The star rating uses real radio buttons**, so it works with the keyboard and with screen
  readers.
- **Pages work without JavaScript.**
