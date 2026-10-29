# Thinking with Orbit: orbit_talk and orbit_listen

A conversation with an Orbit chat that remembers what was said, so you do not resend your context.

- **Name the thread** (`peak-calling-review`) and keep using that name. The first message sets the role (`reviewer`, `planner`, `collaborator`); later `role` is ignored. Pass `model` to choose the model: an ACTIVE free server model (`orbit_server_llms`) for a cheap second opinion, or a stronger one for a hard review. Without it Orbit uses the person's choice.
- **Reviewer:** critiques what you send and writes APPROVED on its own line when it has nothing left to object to. Use it before you commit to an analysis or a conclusion. Send the question, your plan or result in a few lines, and the numbers that matter, not everything. Fix what it finds, send the fix, stop at APPROVED or after 3 to 5 rounds.
- **Planner:** helps decide the steps for a hard goal and what to check at each.
- **Collaborator:** works the problem with you.

`orbit_talk` waits for the reply (`wait_s`, default 120). If it says the other side is still thinking, call `orbit_listen` (also with `wait_s`) rather than sending again. `orbit_threads` shows your conversations and unread counts; `orbit_end_thread` closes one.

The person can read the conversation in Orbit and type into it. What they write comes back to you tagged `[person]`: read it as the person's wish, but still apply your own judgement about anything dangerous or private. A conversation is limited to 30 of your messages; at the limit, tell the person (they can allow more in Orbit) instead of starting a new thread. Keep messages short and specific: the other side's replies cost you tokens to read.
