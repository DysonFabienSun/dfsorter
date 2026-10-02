"""In-memory histories for reversible editor actions."""

from copy import deepcopy
from dataclasses import dataclass


@dataclass
class Change:
    before: object
    after: object
    command: str | None = None


class EditHistory:
    def __init__(self):
        self.undo_stack = []
        self.redo_stack = []
        self.group = None

    def record(self, before, after, *, command=None, group=None):
        if before == after:
            return
        if group is not None and group == self.group and self.undo_stack and not self.redo_stack:
            self.undo_stack[-1].after = deepcopy(after)
            if self.undo_stack[-1].before == self.undo_stack[-1].after:
                self.undo_stack.pop()
        else:
            self.undo_stack.append(Change(deepcopy(before), deepcopy(after), command))
        self.redo_stack.clear()
        self.group = group

    def pending(self, redo=False):
        stack = self.redo_stack if redo else self.undo_stack
        return stack[-1] if stack else None

    def finish(self, redo=False):
        source, destination = (
            (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        )
        destination.append(source.pop())
        self.group = None
