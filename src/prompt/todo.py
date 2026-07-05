
TODO_TOOL_DESC_PROMPT = """
Use this tool to create and manage a structured task list for your current session. This helps you track progress, organize complex user inquiries, and demonstrate thoroughness to the user.
It also helps the user understand the progress of their requests and overall progress of tasks.

## When to Use This Tool
Use this tool proactively in these scenarios:

1. Complex multi-step user inquiries - When handling user issues that require 3 or more distinct steps or actions
2. Non-trivial user tasks - Tasks that require careful analysis, research, or multiple operations
3. User explicitly requests todo list - When the user directly asks you to use the todo list
4. User provides multiple requests - When users provide a list of questions, issues, or tasks (numbered or comma-separated)
5. After receiving new user instructions - Immediately capture user requirements as todos
6. When you start working on a user issue - Mark it as in_progress BEFORE beginning work. Ideally you should only have one todo as in_progress at a time
7. After completing a user task - Mark it as completed and add any new follow-up tasks discovered during resolution

## When NOT to Use This Tool

Skip using this tool when:
1. There is only a single, straightforward user question
2. The inquiry is trivial and tracking it provides no organizational benefit
3. The response can be completed in less than 3 trivial steps
4. The task is purely conversational or informational

NOTE that you should not use this tool if there is only one trivial user inquiry to handle. In this case you are better off just answering the question directly.

## Examples of When to Use the Todo List

<example>
User: How do I cut a clip in Premiere Pro?
Assistant: In Adobe Premiere Pro, you can cut a clip by placing the playhead at the desired position and pressing the Razor Tool (C), or by using the shortcut Ctrl+K (Cmd+K on Mac) to split the clip at the playhead.

<reasoning>
The assistant did not use the todo list because this is a single, straightforward editing operation that can be explained in one step. There is no need to track multiple actions or manage a workflow for such a basic editing task.
</reasoning>
</example>

<example>
User: Can you show me how to add a fade-out at the end of a video clip?
Assistant: Sure. To add a fade-out, apply a Cross Dissolve transition to the end of the clip, or keyframe the Opacity value to gradually reduce it to zero over the last few seconds of the clip.

<reasoning>
The assistant did not use the todo list because this request involves a single, localized editing action with an immediate result. It does not require multi-step planning, investigation, or task tracking.
</reasoning>
</example>

## Task States and Management

1. **Task States**: Use these states to track progress:
   - pending: Task not yet started
   - in_progress: Currently working on (limit to ONE task at a time)
   - completed: Task finished successfully

2. **Task Management**:
   - Update task status in real-time as you work
   - Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
   - Only have ONE task in_progress at any time
   - Complete current tasks before starting new ones
   - Remove tasks that are no longer relevant from the list entirely
   - Every todo update will remind you to complete ALL todos before providing final response to the user

3. **Task Completion Requirements**:
   - ONLY mark a task as completed when you have FULLY accomplished it
   - If you encounter errors, blockers, or cannot finish, keep the task as in_progress
   - When blocked, create a new task describing what needs to be resolved
   - Never mark a task as completed if:
     - Tests are failing
     - Implementation is partial
     - You encountered unresolved errors
     - You couldn't find necessary files or dependencies
   - You MUST complete ALL todos and call TodoWrite tool to mark them all as completed before providing your final response to the user

4. **Task Breakdown**:
   - Create specific, actionable items
   - Break complex tasks into smaller, manageable steps
   - Use clear, descriptive task names

When in doubt, use this tool. Being proactive with task management demonstrates attentiveness and ensures you complete all requirements successfully.
"""

TODO_TOOL_SYSTEM_REMINDER_ONLY_ONE_PROMPT = """<system-reminder>
IMPORTANT: When you need to call the TodoWrite tool to complete all todos, you MUST only call the TodoWrite tool without generating any additional content. Only after I respond with "update successful" should you begin summarizing the content.

When you need to complete all remaining todos:
1. ONLY call the TodoWrite tool to mark all todos as completed
2. DO NOT generate any response content simultaneously 
3. WAIT for the system confirmation message "Todos have been modified successfully"
4. ONLY AFTER receiving confirmation, then provide your summary to the user

DO NOT mention the todo system explicitly to the user - this is for internal task management only.
</system-reminder>"""

TODO_TOOL_RESPONSE_PROMPT = """Todos have been modified successfully. Ensure that you continue to use the todo list to track your progress. Please proceed with the current tasks if applicable"""