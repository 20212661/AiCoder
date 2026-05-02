"""
Whole 文件格式的提示词模板
参考 Aider 的 wholefile_prompts.py
"""
from .base_prompts import CoderPrompts


class WholeFilePrompts(CoderPrompts):
    main_system = """Act as an expert software developer.
For casual conversation or questions, just respond naturally in text — no need to edit files.
When the user asks you to modify code, use the XML tools described in the TOOL USE section below (write_file, edit_file, etc.).
"""

    system_reminder = """Use the tools listed in the TOOL USE section to read, write, and edit files.
For general conversation, just respond in the user's language."""

    redacted_edit_message = "No changes are needed."

    example_messages = [
        dict(
            role="user",
            content="Change the greeting to be more casual",
        ),
        dict(
            role="assistant",
            content="""Ok, I will:

1. Switch the greeting text from "Hello" to "Hey".

show_greeting.py
```
import sys

def greeting(name):
    print(f"Hey {name}")

if __name__ == '__main__':
    greeting(sys.argv[1])
```
""",
        ),
    ]