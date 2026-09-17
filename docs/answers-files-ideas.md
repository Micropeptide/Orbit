# Answers, files and scheduled messages — 200 ideas

Ideas for how Orbit shows what models write, the files they make, and messages you
send later. ✅ = in Orbit now · ◻︎ = worth doing later · ✗ = considered and left out (why).

## A. Markdown the way models write it (1–40)

1. ✅ A real CommonMark/GFM parser (marked) instead of hand-written regexes.
2. ✅ Tables with column alignment (`:---:`, `---:`).
3. ✅ Nested bullet and numbered lists, blank lines between items.
4. ✅ Task lists (`- [x]`) as checkboxes.
5. ✅ `~~strikethrough~~`.
6. ✅ Headings h1–h6 sized as a chat, not a document.
7. ✅ Block quotes.
8. ✅ GitHub/Obsidian callouts `> [!NOTE]`, `[!TIP]`, `[!WARNING]`, `[!CAUTION]`, with custom titles.
9. ✅ Footnotes `[^1]` with hover text and click-to-jump.
10. ✅ `==highlight==`.
11. ✅ Horizontal rules.
12. ✅ Bare URLs become links (GFM autolinks).
13. ✅ Links open in a new tab, `noopener`.
14. ✅ Inline math `$…$`, `\(…\)`; display `$$…$$`, `\[…\]` — typeset while the answer streams.
15. ✅ Math protected from Markdown: `_`, `*`, `|` inside a formula are not emphasis or table cells.
16. ✅ Prices are not math: `$5 and $10`, `$5-$10`.
17. ✅ Math inside table cells.
18. ✅ Safe inline HTML: `<details>`, `<kbd>`, `<sub>`, `<sup>`, `<br>` in tables, `<mark>`.
19. ✅ Everything sanitised (DOMPurify): no scripts, event handlers, `javascript:` links, iframes, forms.
20. ✅ Single line breaks kept (models write addresses, poems, stacked lines).
21. ✅ Mermaid diagrams, including newer types (mindmap, timeline, quadrant, sankey, kanban…).
22. ✅ A diagram that fails to draw shows its error and source, not a blank box.
23. ✅ Syntax highlighting for ~40 languages, light and dark themes.
24. ✅ Language aliases models use (`py`, `sh`, `zsh`, `console`, `yml`, `snakemake`, `nextflow`, `R`…).
25. ✅ Code fence info strings: `python title=analysis.py`, `js filename=x.js`.
26. ✅ `~~~` fences as well as backticks.
27. ✅ Unclosed fences while streaming render as code, not as a broken page.
28. ✅ Broken images show their name and link instead of a torn icon.
29. ✅ Very long unbroken words wrap instead of widening the page.
30. ✅ The old renderer stays as a fallback if the libraries fail to load.
31. ◻︎ Definition lists (`Term\n: definition`).
32. ◻︎ Emoji shortcodes (`:tada:`) — models rarely use them.
33. ◻︎ Heading anchors with “copy link to section”.
34. ◻︎ Table of contents for very long answers.
35. ◻︎ `<abbr>` tooltips.
36. ◻︎ Chemical formulas via KaTeX mhchem (`\ce{H2O}`).
37. ◻︎ Render `csv` fenced blocks as tables by default (now one click).
38. ◻︎ Auto-detect unlabelled code for highlighting — wrong guesses look worse than plain.
39. ✗ Raw HTML pages inside the answer — shown as code with a sandboxed Preview instead.
40. ✗ Executing code blocks in the page — Run sends them to Terminal, where you see them.

## B. Code blocks (41–65)

41. ✅ Header with language or file name.
42. ✅ Copy (shell blocks copy without `$ ` prompts).
43. ✅ Wrap long lines, remembered.
44. ✅ Save as a file with the right extension.
45. ✅ Insert into your message (to ask about or change it).
46. ✅ ▶ Run in Terminal, in the chat’s folder, after you confirm the command.
47. ✅ Run on the SSH host for a remote chat (Terminal + ssh).
48. ✅ `open file.html` / `code src/x.py` blocks: one-click “Open file.html” with its icon.
49. ✅ Code titled with a file name that exists: an Open button for that file.
50. ✅ HTML/SVG: Preview, rendered in a sandbox.
51. ✅ Markdown blocks: Rendered view.
52. ✅ CSV/TSV blocks: Table view (sortable, copyable).
53. ✅ JSON / JSONL: Format (pretty-print) and back.
54. ✅ Diff blocks coloured.
55. ✅ Long blocks (>45 lines) fold with “Show all N lines”.
56. ✅ Buttons appear on hover (always on touch screens), so answers stay calm.
57. ◻︎ Line numbers toggle.
58. ◻︎ “Apply this patch” for diff blocks in a folder chat — needs a careful preview first.
59. ◻︎ Copy one line / a range by clicking line numbers.
60. ◻︎ Compare two code blocks side by side.
61. ◻︎ Open the code in VS Code as an untitled file.
62. ◻︎ Detect `python script.py` and offer Run for that file.
63. ◻︎ Run R/Python snippets in a scratch Jupyter kernel.
64. ✗ Auto-running anything — every run is your click and confirmation.
65. ✗ Editing a code block in place — Insert into the message is clearer.

## C. Files a chat names (66–110)

66. ✅ Relative names mean the chat’s folder (Claude Code chats), else the project folder, else Orbit’s workspace.
67. ✅ Bare names (`report.html`), `./x`, `../x`, `~/x`, absolute paths, `file://` URLs.
68. ✅ `file.py:42`, `file.py:42:7`, `#L42` — Open at that line in VS Code/Cursor/Zed when installed.
69. ✅ Names in inline code, in text, in Markdown links, in Markdown images, in shell blocks.
70. ✅ Names with spaces and accents in inline code (`with space/résumé final.txt`).
71. ✅ Only names that exist become links; a missing absolute path is marked “not found”.
72. ✅ Versions (`1.2.3`) and domains (`example.com`) are not taken for files.
73. ✅ Remote chats: names are looked up on the SSH host (one batched request).
74. ✅ Files the answer wrote count even when the text never names them.
75. ✅ Lookups are batched (one request per answer, cached per chat).
76. ✅ Click: open in the Mac’s app for that file.
77. ✅ ⌥/⌘-click: Show in Finder. ⇧-click: Preview in Orbit.
78. ✅ Right-click menu: Open, Preview, Quick Look, Open with…, Show in Finder, Open in Terminal (folders).
79. ✅ Copy path, Copy relative path, Copy as Markdown link, Copy scp command (remote).
80. ✅ Copy file — paste it into Finder, Mail, Slack; images copy as pictures.
81. ✅ Copy contents of text files.
82. ✅ Download (works from the phone too).
83. ✅ Attach to your next message (images as pictures).
84. ✅ Insert the path into your message.
85. ✅ Open with… lists only apps installed on this Mac that suit the file.
86. ✅ Apps, scripts, installers are only shown in Finder, never launched by a click.
87. ✅ “Files in this answer” cards under an answer: icon or thumbnail, size, folder.
88. ✅ Cards: images first, then pages, PDFs and tables; more than six fold.
89. ✅ Drag a card to Finder or the desktop to save a copy.
90. ✅ Drag a card onto the message box to attach it.
91. ✅ Space on a card: Quick Look.
92. ✅ Missing file: “Find files named …” (the chat’s folders, then Spotlight).
93. ✅ `/files`: every file the chat mentions or wrote, newest first.
94. ✅ Remote files: Download and open / show in Finder (copied to Orbit’s cache).
95. ✅ Folders are links but not “files in this answer”.
96. ◻︎ Recent files across all chats (a Files tab section).
97. ◻︎ Rename / move / trash a file from its menu (with undo).
98. ◻︎ Reveal in the chat’s folder panel inside Orbit.
99. ◻︎ Watch a file an answer made and show when it changes.
100. ◻︎ Compare two versions of a file the chat changed.
101. ◻︎ Upload a local file to the SSH host from its menu.
102. ◻︎ Open a remote folder in Finder via SSHFS when installed.
103. ◻︎ Pin files to a project.
104. ◻︎ Show git status for files in a repository.
105. ◻︎ Thumbnails for PDFs in cards.
106. ◻︎ Hover card with a small preview.
107. ◻︎ `@file` mentions in your message resolve with the same rules.
108. ✗ Linking every word with a dot — only file-like names with known extensions.
109. ✗ Looking up names in the whole home folder by default — wrong files in the wrong chat.
110. ✗ Showing secrets (`.ssh`, `.env`, keychains, `secrets.json`) in pages — refused.

## D. Previews in Orbit (111–135)

111. ✅ Images (PNG, JPEG, GIF, WebP, SVG, AVIF) with fit / actual size.
112. ✅ HEIC, TIFF, PSD, camera RAW via `sips`.
113. ✅ PDF in the browser’s viewer.
114. ✅ HTML pages in a sandbox that can load their own images, CSS and scripts but not Orbit’s API.
115. ✅ View source for HTML.
116. ✅ Markdown rendered, with math and tables.
117. ✅ CSV/TSV as a sortable, filterable table (first 5,000 rows).
118. ✅ Jupyter notebooks: Markdown cells, code, text and image outputs.
119. ✅ Code and text files highlighted; big files show the first 1 MB.
120. ✅ Word, RTF, ODT via `textutil`.
121. ✅ Excel sheets (every sheet, first 3,000 rows) via openpyxl.
122. ✅ Zip and tar contents listed.
123. ✅ Keynote, Pages, Numbers, PowerPoint and anything else Quick Look can draw, as a picture.
124. ✅ Audio and video players.
125. ✅ Esc closes; ← → move between an answer’s images.
126. ✅ Preview links are per folder, expire after 12 hours, and cannot climb out of their folder.
127. ◻︎ Multi-page PDF thumbnails strip.
128. ◻︎ FASTA/BED/VCF aware tables.
129. ◻︎ PDB/mmCIF structure viewer (3Dmol) for AlphaFold outputs.
130. ◻︎ Parquet / Feather tables via pyarrow when installed.
131. ◻︎ SQLite browser.
132. ◻︎ Side-by-side preview panel instead of a sheet.
133. ◻︎ Live-reload a previewed HTML file when it changes.
134. ✗ Running notebooks in the preview.
135. ✗ Same-origin HTML previews — would let a page act as you in Orbit.

## E. Images (136–150)

136. ✅ Hover toolbar: copy image, save, view larger, more.
137. ✅ Copy image as PNG (JPEG, WebP, SVG converted).
138. ✅ Right-click: copy, save, view, open, show in Finder, copy path, copy file.
139. ✅ Click an image in an answer: view larger.
140. ✅ Markdown images with local paths load from the chat’s folder.
141. ✅ Mermaid: copy SVG, copy as image, save SVG/PNG, copy source, enlarge.
142. ✅ Remote image URLs open or copy their address.
143. ✅ Notebook output images are copyable too.
144. ◻︎ Annotate an image and attach it to the next message.
145. ◻︎ Compare two images (slider).
146. ◻︎ Colour-blind simulation for figures.
147. ◻︎ Extract a figure’s data (vision model) into a table.
148. ◻︎ Image size / DPI shown in the viewer.
149. ◻︎ Save all images in an answer as a zip.
150. ✗ Auto-loading remote images through a proxy — plain loading is simpler and visible.

## F. Tables (151–165)

151. ✅ Copy with formatting — pastes as a real table into Word, Excel, Numbers, Google Docs.
152. ✅ Copy as Markdown (alignment kept, pipes escaped).
153. ✅ Copy as CSV / TSV.
154. ✅ Download CSV (UTF-8 with BOM for Excel) and an Excel file.
155. ✅ Sort by any column; numbers sort as numbers (commas, %, units).
156. ✅ Numeric columns right-aligned.
157. ✅ Sticky header, zebra rows, horizontal scroll for wide tables.
158. ✅ Rows × columns shown.
159. ✅ Long tables fold after 25 rows.
160. ✅ Full screen with a row filter.
161. ✅ Math inside cells copies as LaTeX.
162. ◻︎ Column totals / mean for numeric columns.
163. ◻︎ Chart a table (bar/line) in one click.
164. ◻︎ Freeze first column.
165. ◻︎ Send a table to a new CSV file in the chat’s folder.

## G. Copying and exporting answers (166–180)

166. ✅ Copy as Markdown (what the model wrote).
167. ✅ Copy with formatting (headings, lists, tables, code, math as MathML).
168. ✅ Copy as plain text (math as `$LaTeX$`, tables as TSV).
169. ✅ Save an answer as Markdown or HTML.
170. ✅ Print or save as PDF.
171. ✅ Copying a selection leaves out Orbit’s buttons and keeps formatting.
172. ✅ Right-click a formula: copy LaTeX (with or without delimiters) or MathML.
173. ✅ Select text in any message: Quote it into your reply, or Copy.
174. ◻︎ Export the whole chat as HTML/PDF with rendered formatting.
175. ◻︎ Share an answer as a private Artifact page.
176. ◻︎ Copy an answer as rich text with images embedded.
177. ◻︎ Copy for Slack (mrkdwn) / for Notion.
178. ◻︎ Save an answer into the chat’s folder as `.md`.
179. ◻︎ Citations: copy as BibTeX when DOIs are present.
180. ✗ Auto-copy on select — surprising.

## H. Scheduled messages (181–200)

181. ✅ ⏱ beside Send: send this message later (right-click Send does the same; phones use `/later`).
182. ✅ Quick picks: in 30 min, in 1 hour, this evening, tomorrow morning, Monday morning.
183. ✅ Any date and time.
184. ✅ Repeat every day, every weekday, or every week, at the same clock time (daylight saving safe).
185. ✅ `/later 21:30 …`, `/later tomorrow 9am …`, `/later in 2h …`, `/later daily 8:00 …`, `/later fri 5pm …`.
186. ✅ Scheduled messages sit in the chat’s queue under “Scheduled”, with the time.
187. ✅ Change the time, send now, edit, remove; stopping a repeat asks first.
188. ✅ A queued message can be given a time (⏱ on its row); a scheduled one can go back to the queue.
189. ✅ They go out on time (checked every 15 s), in the chat, with its model, folder and approvals — as if you sent them.
190. ✅ A scheduled message doesn’t hold back what you send now.
191. ✅ Stop pauses queued messages but not scheduled ones.
192. ✅ Kept across restarts; the chat stays loaded while something is scheduled.
193. ✅ Missed while the Mac slept: sent when Orbit is back if under 6 h late (`schedule_send_grace_h`); a one-off older than that is marked missed for you; a repeat waits for its next time.
194. ✅ Sending a repeating one early keeps the series.
195. ✅ `/scheduled`: everything scheduled in every chat; send now, remove, open the chat.
196. ✅ Sidebar rows show ⏱ for chats with something scheduled, and such chats are listed even before their first message.
197. ◻︎ “Only if the chat has been quiet” condition.
198. ◻︎ Scheduled messages from the iPhone app.
199. ◻︎ A notification a minute before one goes out, with Skip.
200. ◻︎ Send later into a new chat each time (today: Settings → Scheduler tasks).
