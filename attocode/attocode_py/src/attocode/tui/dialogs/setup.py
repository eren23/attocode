"""First-run setup wizard and API key dialog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from attocode.config import (
    PROVIDER_MODEL_DEFAULTS,
    PROVIDER_MODEL_OPTIONS,
    save_global_config,
)


@dataclass(slots=True)
class SetupResult:
    """Result of the setup wizard."""

    provider: str
    api_key: str
    model: str
    completed: bool  # False if user ESC'd


class SetupWizard(ModalScreen[SetupResult]):
    """3-step setup wizard: provider -> API key -> model.

    Navigation:
    - Steps 1 & 3: number keys to select, ESC to go back (or cancel on step 1)
    - Step 2: type API key, Enter to submit, ESC to go back
    - Step 3: also has a [Custom] button for entering a custom model name
    """

    AUTO_FOCUS = ""  # Disable auto-focus — we manage focus manually per step

    DEFAULT_CSS = """
    SetupWizard {
        align: center middle;
    }

    #setup-container {
        width: 70;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: double $accent;
        background: $surface;
        padding: 1 2;
    }

    .step-indicator {
        text-align: center;
        color: $text-muted;
        padding: 0 0 1 0;
    }

    SetupWizard Input {
        margin: 1 0;
    }

    SetupWizard Button {
        margin: 1 0 0 0;
        min-width: 16;
    }

    SetupWizard #button-row {
        height: auto;
        align: center middle;
        layout: horizontal;
    }

    SetupWizard #button-row Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("1", "pick_1", "1", show=False),
        Binding("2", "pick_2", "2", show=False),
        Binding("3", "pick_3", "3", show=False),
        Binding("4", "pick_4", "4", show=False),
        Binding("escape", "back_or_cancel", "Back/Cancel", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._step = 1
        self._provider = ""
        self._api_key = ""
        self._model = ""
        self._custom_model_mode = False

    def compose(self) -> ComposeResult:
        with Vertical(id="setup-container"):
            yield Static("", id="step-indicator", classes="step-indicator")
            yield Static("", id="title", classes="dialog-title")
            yield Static("", id="content", classes="dialog-content")
            yield Input(placeholder="", id="key-input", password=True)
            yield Input(placeholder="Custom model name", id="model-input")
            from textual.containers import Horizontal
            with Horizontal(id="button-row"):
                yield Button("Custom", id="btn-custom", variant="default")
                yield Button("Back", id="btn-back", variant="default")
            yield Static("", id="shortcuts", classes="dialog-shortcuts")

    def on_mount(self) -> None:
        self._render_step()

    def _render_step(self) -> None:
        indicator = self.query_one("#step-indicator", Static)
        title = self.query_one("#title", Static)
        content = self.query_one("#content", Static)
        shortcuts = self.query_one("#shortcuts", Static)
        key_input = self.query_one("#key-input", Input)
        model_input = self.query_one("#model-input", Input)
        btn_custom = self.query_one("#btn-custom", Button)
        btn_back = self.query_one("#btn-back", Button)
        button_row = self.query_one("#button-row")

        # Hide everything by default
        key_input.display = False
        model_input.display = False
        button_row.display = False
        self._custom_model_mode = False

        # Clear focus from any widget
        self.set_focus(None)

        indicator.update(f"Step {self._step} of 3")

        if self._step == 1:
            self._render_provider_step(title, content, shortcuts)
        elif self._step == 2:
            self._render_apikey_step(title, content, shortcuts, key_input)
        elif self._step == 3:
            self._render_model_step(title, content, shortcuts, button_row, btn_custom, btn_back)

    def _render_provider_step(
        self, title: Static, content: Static, shortcuts: Static
    ) -> None:
        title_text = Text()
        title_text.append("Welcome to Attocode!", style="bold")
        title.update(title_text)

        body = Text()
        body.append("Choose your LLM provider:\n\n")
        body.append("  [1] ", style="bold cyan")
        body.append("Anthropic")
        body.append("  (Claude models)\n", style="dim")
        body.append("  [2] ", style="bold cyan")
        body.append("OpenRouter")
        body.append("  (multi-provider gateway)\n", style="dim")
        body.append("  [3] ", style="bold cyan")
        body.append("OpenAI")
        body.append("  (GPT models)\n", style="dim")
        body.append("  [4] ", style="bold cyan")
        body.append("Z.AI")
        body.append("  (GLM-5)\n", style="dim")
        content.update(body)

        shortcuts.update("[1/2/3/4] Select provider  [ESC] Cancel")

    def _render_apikey_step(
        self, title: Static, content: Static, shortcuts: Static, key_input: Input
    ) -> None:
        from attocode.config import PROVIDER_ENV_VARS

        title_text = Text()
        title_text.append("API Key", style="bold")
        title.update(title_text)

        env_var = PROVIDER_ENV_VARS.get(self._provider, "")
        body = Text()
        body.append("Provider: ", style="dim")
        body.append(f"{self._provider}\n", style="bold")
        body.append("\nEnter your API key below.\n", style="dim")
        body.append(f"(You can also set {env_var} in your environment)\n", style="dim italic")
        content.update(body)

        key_input.display = True
        key_input.placeholder = "sk-..."
        key_input.value = ""
        key_input.focus()

        shortcuts.update("[Enter] Submit  [ESC] Back")

    def _render_model_step(
        self,
        title: Static,
        content: Static,
        shortcuts: Static,
        button_row: Any,
        btn_custom: Button,
        btn_back: Button,
    ) -> None:
        title_text = Text()
        title_text.append("Model Selection", style="bold")
        title.update(title_text)

        models = PROVIDER_MODEL_OPTIONS.get(self._provider, [])
        default = PROVIDER_MODEL_DEFAULTS.get(self._provider, "")

        body = Text()
        body.append("Provider: ", style="dim")
        body.append(f"{self._provider}\n\n", style="bold")
        body.append("Choose a model:\n\n")
        for i, m in enumerate(models, 1):
            body.append(f"  [{i}] ", style="bold cyan")
            body.append(m)
            if m == default:
                body.append("  (default)", style="dim green")
            body.append("\n")
        content.update(body)

        # Show buttons for custom and back
        button_row.display = True

        shortcuts.update("[1/2/3] Select  [ESC] Back  or use buttons below")

    # --- Conditional binding control ---

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Disable number bindings when an Input is focused."""
        if action == "back_or_cancel":
            return True
        # Step 2 (API key input): disable all number bindings
        if self._step == 2:
            return False
        # Step 3 custom model input: disable all number bindings
        if self._custom_model_mode:
            return False
        return True

    # --- Input handlers ---

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "key-input" and self._step == 2:
            key = event.value.strip()
            if key:
                self._api_key = key
                self._step = 3
                self._render_step()
        elif event.input.id == "model-input" and self._custom_model_mode:
            model = event.value.strip()
            if model:
                self._model = model
                self._finish()

    # --- Button handlers ---

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-custom":
            if self._step == 3 and not self._custom_model_mode:
                self._custom_model_mode = True
                model_input = self.query_one("#model-input", Input)
                model_input.display = True
                model_input.value = ""
                model_input.focus()
                self.query_one("#button-row").display = False
                self.query_one("#shortcuts", Static).update("[Enter] Submit  [ESC] Back")
        elif event.button.id == "btn-back":
            self._go_back()

    # --- Binding actions (step-aware) ---

    def _select_provider(self, provider: str) -> None:
        if self._step == 1:
            self._provider = provider
            self._step = 2
            self._render_step()

    def _select_model_index(self, index: int) -> None:
        if self._step != 3 or self._custom_model_mode:
            return
        models = PROVIDER_MODEL_OPTIONS.get(self._provider, [])
        if index < len(models):
            self._model = models[index]
            self._finish()

    def action_pick_1(self) -> None:
        if self._step == 1:
            self._select_provider("anthropic")
        elif self._step == 3:
            self._select_model_index(0)

    def action_pick_2(self) -> None:
        if self._step == 1:
            self._select_provider("openrouter")
        elif self._step == 3:
            self._select_model_index(1)

    def action_pick_3(self) -> None:
        if self._step == 1:
            self._select_provider("openai")
        elif self._step == 3:
            self._select_model_index(2)

    def action_pick_4(self) -> None:
        if self._step == 1:
            self._select_provider("zai")

    def action_back_or_cancel(self) -> None:
        """ESC: go back one step, or cancel on step 1."""
        if self._custom_model_mode:
            # Exit custom model input, return to step 3 normal
            self._custom_model_mode = False
            self._render_step()
        elif self._step > 1:
            self._step -= 1
            self._render_step()
        else:
            # Step 1: cancel the wizard
            self.dismiss(SetupResult(
                provider="",
                api_key="",
                model="",
                completed=False,
            ))

    def _go_back(self) -> None:
        """Go back one step."""
        if self._custom_model_mode:
            self._custom_model_mode = False
            self._render_step()
        elif self._step > 1:
            self._step -= 1
            self._render_step()

    def _finish(self) -> None:
        self.dismiss(SetupResult(
            provider=self._provider,
            api_key=self._api_key,
            model=self._model,
            completed=True,
        ))


class ApiKeyDialog(ModalScreen[str]):
    """Standalone API key entry dialog for /config api-key.

    Keyboard shortcuts:
    - Enter: Save and dismiss
    - ESC: Cancel
    """

    DEFAULT_CSS = """
    ApiKeyDialog {
        align: center middle;
    }

    #apikey-container {
        width: 60;
        max-width: 80%;
        height: auto;
        border: double $accent;
        background: $surface;
        padding: 1 2;
    }

    ApiKeyDialog Input {
        margin: 1 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="apikey-container"):
            yield Static(
                Text.from_markup("[bold]Update API Key[/bold]"),
                classes="dialog-title",
            )
            yield Static(
                "Enter your new API key. It will be saved to ~/.attocode/config.json.",
                classes="dialog-content",
            )
            yield Input(placeholder="sk-...", password=True, id="apikey-input")
            yield Static("[Enter] Save  [ESC] Cancel", classes="dialog-shortcuts")

    def on_mount(self) -> None:
        self.query_one("#apikey-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        key = event.value.strip()
        if key:
            save_global_config({"api_key": key})
            self.dismiss(key)
        else:
            self.dismiss("")

    def action_cancel(self) -> None:
        self.dismiss("")
