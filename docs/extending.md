# Extending Orbit

Everything on this page is a plain file you drop into a folder. You don't need
to restart anything: tools and plugins are picked up before the next answer
begins.

## A tool in one file

Put a Python file in `tools/` inside the Orbit folder. Every chat can use it.

```python
# tools/word_count.py
SPEC = {
    "name": "word_count",
    "description": "Count the words in a piece of text.",
    "parameters": {"type": "object",
                   "properties": {"text": {"type": "string"}},
                   "required": ["text"]},
}
SAFE = True          # run without asking; leave it out to be asked each time

def run(text):
    return f"{len(text.split())} words"
```

One file can also define several tools:

```python
TOOLS = [
    {"name": "c_to_f", "description": "Celsius to Fahrenheit",
     "parameters": {"type": "object", "properties": {"c": {"type": "number"}}, "required": ["c"]},
     "run": lambda c: c * 9 / 5 + 32, "safe": True},
]
```

How it works:
- `run` can return a string or anything JSON-serialisable.
- A tool whose name clashes with a built-in is ignored.
- A file that fails to import is shown in Settings → Tools, on the same line as MCP server errors. It never breaks a chat.
- Files whose names start with `_` are skipped, so you can keep helper modules next to your tools.

## A project that points at a folder

In the project editor, set **Folder** to a directory, e.g. `~/code/my-analysis`.
Chats in that project then work there:

- **Relative paths resolve against the folder.** This applies to `read_file`, `edit_file` and `write_file`, and writes inside the folder are allowed.
- **The folder's rules file joins the system prompt.** Orbit uses the first of `ORBIT.md`, `AGENTS.md` or `CLAUDE.md` it finds. The rules file suits things like "run the tests before calling it done" or "never touch `data/raw`".
- **`<folder>/.orbit/tools/*.py` become tools for that project only.** They use the same format as above, but they are not even imported until you tick **Trust tools** for the project, because importing a Python file runs it and a folder may be a repository you cloned. Until then the chat is told that tool files are waiting. Once the project is trusted, a tool marked `SAFE` runs without asking and any other tool asks each time.
- **A folder must be specific.** `/`, your home folder and top-level folders are refused, because a project folder is somewhere Orbit may write.

## Plugins

A Python file in `plugins/` can define any of these hooks:

```python
# plugins/audit.py
def tool_before(name, args):
    """Called before every tool call. Return the (possibly changed) args,
    or raise PermissionError("why") to refuse the call."""
    if name == "run_shell" and "prod" in args.get("command", ""):
        raise PermissionError("no commands against prod from Orbit")
    return args

def tool_after(name, args, output):
    """Called with each tool's output; return what the model should see."""
    return output

def system_transform(text):
    """Called with the full system prompt before each answer."""
    return text + "\nAlways answer in British English."
```

A hook that raises anything other than `PermissionError` is logged to
`logs/plugins.log` and skipped. A broken plugin never stops an answer.

## Saved prompts with arguments

Save a prompt under **Library → Prompts**, e.g. the name `cite` with this text:

```
Find three peer-reviewed sources for: $ARGUMENTS. Start with $1.
```

Typing `/cite "sea ice" arctic` then sends:

```
Find three peer-reviewed sources for: "sea ice" arctic. Start with sea ice.
```

Placeholders:
- `$ARGUMENTS` is everything after the name.
- `$1`, `$2`, … are single words. Quotes group words, so `"sea ice"` counts as one.
- If the prompt has no placeholders, the arguments are appended to the end.

## Headless: `orbit run`

Answer once and exit, for scripts, cron jobs or CI:

```bash
bin/orbit run "summarise today's log in logs/app.log"
bin/orbit run --json --project "My analysis" "rerun the pipeline and report failures"
echo "what changed in git today?" | bin/orbit run
```

With `--json`, Orbit prints one JSON object per line. Each tool call, tool result and retry is its own line, and a final `result` line carries the text, time taken, token use and tool count.

Nobody is there to approve anything, so actions that would normally ask are refused, just as for a scheduled task. `--save` keeps the conversation as a chat you can open in the app.

## The `task` tool

The model can hand a self-contained sub-task to a helper: another instance with
the same tools and an empty context. Only the helper's report comes back.

This keeps a long side-investigation, such as searching papers or reading logs,
from filling the main conversation's window. A helper cannot start helpers of
its own. It follows the same approval rules as the chat that started it.
